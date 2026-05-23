"""
coordinator.py
─────────────────────────────────────────────────────────────
Phase 1 : One browser session → capture cookies + CSRF token
Phase 2 : Query API page 1 → get total records → compute page ranges
Phase 3 : Write shared/session.json  +  workers/worker_XX/config.json
Phase 4 : Launch all 20 workers as subprocesses (staggered 3 s apart)
Phase 5 : Monitor until all finish, then merge all CSVs → output/all_bids.csv
─────────────────────────────────────────────────────────────
"""

import asyncio, json, math, os, re, subprocess, sys, time
from pathlib import Path
import requests
import pandas as pd
from playwright.async_api import async_playwright

# ── paths ────────────────────────────────────────────────────────────────────
BASE    = Path(__file__).parent
SHARED  = BASE / "shared"
OUTPUT  = BASE / "output"
WORKERS = BASE / "workers"

URL     = "https://bidplus.gem.gov.in/all-bids"
API_URL = "https://bidplus.gem.gov.in/all-bids-data"

NUM_WORKERS    = 20
STAGGER_SECS   = 3          # seconds between launching each worker
PYTHON         = sys.executable

HEADERS = {
    "User-Agent"     : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type"   : "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer"        : URL,
    "Origin"         : "https://bidplus.gem.gov.in",
}

# ── Phase 1 : browser session ─────────────────────────────────────────────────
async def get_session() -> dict:
    result = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()

        def on_req(req):
            if "all-bids-data" in req.url and req.method == "POST":
                body = req.post_data or ""
                m = re.search(r"csrf_bd_gem_nk=([a-f0-9]+)", body)
                if m:
                    result["csrf"] = m.group(1)

        page.on("request", on_req)

        print("  [browser] Loading site...")
        await page.goto(URL, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(2000)

        # trigger a POST so we capture CSRF
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(1500)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(3000)

        result["cookies"] = {c["name"]: c["value"] for c in await ctx.cookies()}
        await browser.close()

    print(f"  [browser] CSRF : {result.get('csrf')}")
    print(f"  [browser] Cookies: {list(result['cookies'].keys())}")
    return result


# ── Phase 2 : probe page 1 → total records ───────────────────────────────────
def probe_total(session: dict) -> int:
    csrf    = session["csrf"]
    cookies = session["cookies"]

    payload = {
        "param" : {"searchBid": "", "searchType": "fullText"},
        "filter": {
            "bidStatusType": "ongoing_bids",
            "byType"       : "all",
            "highBidValue" : "",
            "byEndDate"    : {"from": "", "to": ""},
            "sort"         : "Bid-End-Date-Latest",
            "byStatus"     : "",
        },
        "page": 1,
    }
    pj       = json.dumps(payload, separators=(",", ":"))
    postdata = f"payload={requests.utils.quote(pj)}&csrf_bd_gem_nk={csrf}"

    sess = requests.Session()
    sess.headers.update(HEADERS)
    for k, v in cookies.items():
        sess.cookies.set(k, v)

    r = sess.post(API_URL, data=postdata, timeout=30)
    data  = r.json()
    inner = data["response"]["response"]
    total = inner["numFound"]
    print(f"  [probe]   numFound = {total:,}")
    return total


# ── Phase 3 : write configs ───────────────────────────────────────────────────
def write_configs(session: dict, total_records: int):
    total_pages  = math.ceil(total_records / 10)
    pages_each   = math.ceil(total_pages / NUM_WORKERS)

    SHARED.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

    # write shared session
    with open(SHARED / "session.json", "w") as f:
        json.dump(session, f, indent=2)
    print(f"  [config]  session.json written")

    # write per-worker config
    ranges = []
    for wid in range(1, NUM_WORKERS + 1):
        start = (wid - 1) * pages_each + 1
        end   = min(wid * pages_each, total_pages)
        cfg   = {
            "worker_id"   : wid,
            "start_page"  : start,
            "end_page"    : end,
            "total_pages" : total_pages,
            "total_records": total_records,
        }
        wdir = WORKERS / f"worker_{wid:02d}"
        with open(wdir / "config.json", "w") as f:
            json.dump(cfg, f, indent=2)
        ranges.append((wid, start, end))
        print(f"  [config]  worker_{wid:02d} → pages {start:>5} – {end:>5}  ({end-start+1} pages)")

    return ranges


# ── Phase 4 : launch workers ──────────────────────────────────────────────────
def launch_workers(ranges):
    procs = {}
    for wid, start, end in ranges:
        wdir     = WORKERS / f"worker_{wid:02d}"
        log_path = OUTPUT / f"worker_{wid:02d}.log"
        log_file = open(log_path, "w")

        proc = subprocess.Popen(
            [PYTHON, str(wdir / "worker.py")],
            cwd    = str(wdir),
            stdout = log_file,
            stderr = log_file,
        )
        procs[wid] = (proc, log_file)
        print(f"  [launch]  worker_{wid:02d} started  (pid={proc.pid})  pages {start}–{end}")

        if wid < NUM_WORKERS:
            time.sleep(STAGGER_SECS)

    return procs


# ── Phase 5 : monitor + merge ─────────────────────────────────────────────────
def monitor_and_merge(procs):
    print(f"\n  [monitor] Waiting for {len(procs)} workers...")
    while True:
        time.sleep(10)
        done    = {wid for wid, (p, _) in procs.items() if p.poll() is not None}
        running = set(procs) - done
        # print latest line from each running worker's log
        for wid in sorted(running):
            log_path = OUTPUT / f"worker_{wid:02d}.log"
            try:
                lines = log_path.read_text().strip().splitlines()
                last  = lines[-1] if lines else "…"
                print(f"    worker_{wid:02d} | {last}")
            except Exception:
                pass
        print(f"  [monitor] Done: {len(done)}/{len(procs)}  Running: {sorted(running)}")
        if not running:
            break

    # close log files
    for _, (_, lf) in procs.items():
        lf.close()

    # merge CSVs
    print("\n  [merge]   Combining all worker CSVs...")
    frames = []
    for wid in range(1, NUM_WORKERS + 1):
        csv_path = OUTPUT / f"worker_{wid:02d}.csv"
        if csv_path.exists() and csv_path.stat().st_size > 0:
            df = pd.read_csv(csv_path)
            frames.append(df)
            print(f"    worker_{wid:02d}.csv  →  {len(df):>6} rows")
        else:
            print(f"    worker_{wid:02d}.csv  →  missing / empty")

    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["id"])
        merged.to_csv(OUTPUT / "all_bids.csv", index=False)
        print(f"\n  [merge]   all_bids.csv written  ({len(merged):,} unique records)")
    else:
        print("  [merge]   No CSV files found — nothing to merge")


# ── main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 65)
    print("GemEdge Coordinator — 20-Worker Parallel Scraper")
    print("=" * 65)

    print("\n[PHASE 1] Browser session (CSRF + cookies)")
    session = await get_session()

    print("\n[PHASE 2] Probing API for total record count")
    total   = probe_total(session)

    print(f"\n[PHASE 3] Writing session + worker configs  ({math.ceil(total/10):,} pages / {NUM_WORKERS} workers)")
    ranges  = write_configs(session, total)

    print(f"\n[PHASE 4] Launching {NUM_WORKERS} workers  (stagger={STAGGER_SECS}s each)")
    procs   = launch_workers(ranges)

    print(f"\n[PHASE 5] Monitoring + merging")
    monitor_and_merge(procs)

    print("\n" + "=" * 65)
    print("All done. Check output/all_bids.csv")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
