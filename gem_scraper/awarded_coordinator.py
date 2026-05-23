"""
awarded_coordinator.py
─────────────────────────────────────────────────────────────
Scrapes AWARDED bids (bidStatusType=bidrastatus, byStatus=bid_awarded).
Target: 5,000 bids (500 pages).
20 workers × 25 pages each.
Output: output/awarded_bids.csv
─────────────────────────────────────────────────────────────
"""
import asyncio, json, math, os, re, subprocess, sys, time
from pathlib import Path
import requests, pandas as pd
from playwright.async_api import async_playwright

BASE    = Path(__file__).parent
SHARED  = BASE / "shared"
OUTPUT  = BASE / "output"
WORKERS = BASE / "workers"

URL      = "https://bidplus.gem.gov.in/all-bids"
API_URL  = "https://bidplus.gem.gov.in/all-bids-data"

NUM_WORKERS   = 20
TARGET_PAGES  = 500        # 500 pages × 10 records = 5,000 bids
STAGGER_SECS  = 2
PYTHON        = sys.executable

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type"    : "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer"         : URL,
    "Origin"          : "https://bidplus.gem.gov.in",
}

# ── Phase 1 : browser session ─────────────────────────────────────────────────
async def get_session():
    result = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()

        def on_req(req):
            if "all-bids-data" in req.url and req.method == "POST":
                m = re.search(r"csrf_bd_gem_nk=([a-f0-9]+)", req.post_data or "")
                if m:
                    result["csrf"] = m.group(1)

        page.on("request", on_req)
        print("  [browser] Loading site...")
        await page.goto(URL, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(1500)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(3000)
        result["cookies"] = {c["name"]: c["value"] for c in await ctx.cookies()}
        await browser.close()
    print(f"  [browser] CSRF: {result.get('csrf')}")
    return result

# ── Phase 2 : probe total awarded records ─────────────────────────────────────
def probe_total(session):
    payload = {
        "param" : {"searchBid": "", "searchType": "fullText"},
        "filter": {
            "bidStatusType": "bidrastatus",
            "byType"       : "all",
            "highBidValue" : "",
            "byEndDate"    : {"from": "", "to": ""},
            "sort"         : "Bid-End-Date-Latest",
            "byStatus"     : "bid_awarded",
        },
        "page": 1,
    }
    pj   = json.dumps(payload, separators=(",", ":"))
    data = f"payload={requests.utils.quote(pj)}&csrf_bd_gem_nk={session['csrf']}"
    sess = requests.Session()
    sess.headers.update(HEADERS)
    for k, v in session["cookies"].items():
        sess.cookies.set(k, v)
    r     = sess.post(API_URL, data=data, timeout=30)
    total = r.json()["response"]["response"]["numFound"]
    print(f"  [probe]   Total awarded bids available: {total:,}")
    return total

# ── Phase 3 : write configs ───────────────────────────────────────────────────
def write_configs(session, total_records):
    pages_each = math.ceil(TARGET_PAGES / NUM_WORKERS)
    SHARED.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

    # stamp the session with awarded filter flag
    session["filter"] = "bid_awarded"
    with open(SHARED / "session.json", "w") as f:
        json.dump(session, f, indent=2)

    ranges = []
    for wid in range(1, NUM_WORKERS + 1):
        start = (wid - 1) * pages_each + 1
        end   = min(wid * pages_each, TARGET_PAGES)
        cfg   = {"worker_id": wid, "start_page": start, "end_page": end,
                 "filter": "bid_awarded"}
        wdir  = WORKERS / f"worker_{wid:02d}"
        with open(wdir / "config.json", "w") as f:
            json.dump(cfg, f, indent=2)
        ranges.append((wid, start, end))
        print(f"  [config]  worker_{wid:02d} → pages {start:>4} – {end:<4}")
    return ranges

# ── Phase 4 : launch workers ──────────────────────────────────────────────────
def launch_workers(ranges):
    procs = {}
    for wid, start, end in ranges:
        wdir     = WORKERS / f"worker_{wid:02d}"
        log_path = OUTPUT / f"worker_{wid:02d}.log"
        lf       = open(log_path, "w")
        proc     = subprocess.Popen([PYTHON, str(wdir / "worker.py")],
                                    cwd=str(wdir), stdout=lf, stderr=lf)
        procs[wid] = (proc, lf)
        print(f"  [launch]  worker_{wid:02d} pid={proc.pid}  pages {start}–{end}")
        if wid < NUM_WORKERS:
            time.sleep(STAGGER_SECS)
    return procs

# ── Phase 5 : monitor + merge ─────────────────────────────────────────────────
def monitor_and_merge(procs):
    print(f"\n  [monitor] All {len(procs)} workers running...")
    while True:
        time.sleep(10)
        done    = {wid for wid, (p, _) in procs.items() if p.poll() is not None}
        running = set(procs) - done
        for wid in sorted(running):
            try:
                lines = (OUTPUT / f"worker_{wid:02d}.log").read_text().strip().splitlines()
                print(f"    worker_{wid:02d} | {lines[-1] if lines else '...'}")
            except Exception:
                pass
        print(f"  [monitor] Done={len(done)}/{len(procs)}  Running={sorted(running)}")
        if not running:
            break
    for _, (_, lf) in procs.items():
        lf.close()

    print("\n  [merge] Combining CSVs...")
    frames = []
    for wid in range(1, NUM_WORKERS + 1):
        p = OUTPUT / f"worker_{wid:02d}.csv"
        if p.exists() and p.stat().st_size > 0:
            df = pd.read_csv(p)
            frames.append(df)
            print(f"    worker_{wid:02d}.csv → {len(df)} rows")
    if frames:
        merged = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["id"])
        merged.to_csv(OUTPUT / "awarded_bids.csv", index=False)
        print(f"\n  [merge] awarded_bids.csv → {len(merged):,} rows")
    return len(merged) if frames else 0

async def main():
    print("=" * 65)
    print("GemEdge — Awarded Bids Scraper (20 workers)")
    print("=" * 65)
    print("\n[PHASE 1] Browser session")
    session = await get_session()
    print("\n[PHASE 2] Probe total awarded records")
    total   = probe_total(session)
    print(f"\n[PHASE 3] Write configs (targeting {TARGET_PAGES} pages = {TARGET_PAGES*10:,} bids)")
    ranges  = write_configs(session, total)
    print(f"\n[PHASE 4] Launch {NUM_WORKERS} workers")
    procs   = launch_workers(ranges)
    print("\n[PHASE 5] Monitor + merge")
    monitor_and_merge(procs)
    print("\n✅ Done. Run: python3 detail_coordinator.py")

if __name__ == "__main__":
    asyncio.run(main())
