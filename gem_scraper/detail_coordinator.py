"""
detail_coordinator.py
─────────────────────────────────────────────────────────────
For every bid in awarded_bids.csv, fetch getBidResultView/{id}
and extract: winner_name, winner_price, num_bidders,
             all vendor rows (name, rank, price, status_flag)
20 detail workers run in parallel.
Output: output/awarded_with_vendors.csv
─────────────────────────────────────────────────────────────
"""
import json, math, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE    = Path(__file__).parent
SHARED  = BASE / "shared"
OUTPUT  = BASE / "output"
WORKERS = BASE / "workers"

NUM_WORKERS  = 20
STAGGER_SECS = 1
PYTHON       = sys.executable


def split_ids(ids, n):
    size   = math.ceil(len(ids) / n)
    chunks = [ids[i:i+size] for i in range(0, len(ids), size)]
    while len(chunks) < n:
        chunks.append([])
    return chunks


def write_detail_configs(ids):
    chunks = split_ids(ids, NUM_WORKERS)
    for wid in range(1, NUM_WORKERS + 1):
        chunk = chunks[wid - 1]
        cfg   = {"worker_id": wid, "mode": "detail", "bid_ids": chunk}
        wdir  = WORKERS / f"worker_{wid:02d}"
        with open(wdir / "config.json", "w") as f:
            json.dump(cfg, f, indent=2)
        print(f"  [config]  worker_{wid:02d} → {len(chunk)} bids")


def launch_workers():
    procs = {}
    for wid in range(1, NUM_WORKERS + 1):
        wdir     = WORKERS / f"worker_{wid:02d}"
        log_path = OUTPUT / f"worker_{wid:02d}.log"
        lf       = open(log_path, "w")
        proc     = subprocess.Popen(
            [PYTHON, str(wdir / "detail_worker.py")],
            cwd=str(wdir), stdout=lf, stderr=lf
        )
        procs[wid] = (proc, lf)
        print(f"  [launch]  worker_{wid:02d} pid={proc.pid}")
        if wid < NUM_WORKERS:
            time.sleep(STAGGER_SECS)
    return procs


def monitor_and_merge(procs, listing_df):
    print(f"\n  [monitor] {len(procs)} detail workers running...")
    while True:
        time.sleep(15)
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

    # merge all vendor CSVs
    print("\n  [merge] Combining vendor detail CSVs...")
    vendor_frames = []
    for wid in range(1, NUM_WORKERS + 1):
        p = OUTPUT / f"vendors_{wid:02d}.csv"
        if p.exists() and p.stat().st_size > 0:
            df = pd.read_csv(p)
            vendor_frames.append(df)
            print(f"    vendors_{wid:02d}.csv → {len(df)} rows")

    if not vendor_frames:
        print("  [merge] No vendor files found!")
        return

    vendors = pd.concat(vendor_frames, ignore_index=True)
    vendors.to_csv(OUTPUT / "all_vendors.csv", index=False)
    print(f"\n  [merge] all_vendors.csv → {len(vendors):,} vendor rows")

    # merge listing + vendor summary (one row per bid: winner, num_bidders, l1_price)
    summary = (vendors[vendors["vendor_rank"] == "L1"]
               .groupby("bid_id")
               .first()
               .reset_index()
               [["bid_id", "vendor_name", "vendor_price"]]
               .rename(columns={"vendor_name": "winner_name", "vendor_price": "winner_price"}))

    bidder_count = vendors.groupby("bid_id")["vendor_name"].count().reset_index()
    bidder_count.columns = ["bid_id", "num_bidders"]

    l2 = (vendors[vendors["vendor_rank"] == "L2"]
          .groupby("bid_id")["vendor_price"]
          .first()
          .reset_index()
          .rename(columns={"vendor_price": "l2_price"}))

    enriched = (listing_df
                .merge(summary,      left_on="id", right_on="bid_id", how="left")
                .merge(bidder_count, left_on="id", right_on="bid_id", how="left")
                .merge(l2,           left_on="id", right_on="bid_id", how="left"))

    enriched.to_csv(OUTPUT / "awarded_with_vendors.csv", index=False)
    print(f"  [merge] awarded_with_vendors.csv → {len(enriched):,} rows")
    print(f"          Bids with winner data: {enriched['winner_name'].notna().sum():,}")
    print(f"          Bids with no result yet: {enriched['winner_name'].isna().sum():,}")


def main():
    print("=" * 65)
    print("GemEdge — Detail Page Fetcher (20 workers)")
    print("=" * 65)

    listing_df = pd.read_csv(OUTPUT / "awarded_bids.csv")
    ids        = listing_df["id"].tolist()
    print(f"\n  Bids to fetch details for: {len(ids):,}")

    print("\n[PHASE 1] Write detail configs")
    write_detail_configs(ids)

    print(f"\n[PHASE 2] Launch {NUM_WORKERS} detail workers")
    procs = launch_workers()

    print("\n[PHASE 3] Monitor + merge")
    monitor_and_merge(procs, listing_df)

    print("\n✅ Done. Run: python3 cleaner.py")


if __name__ == "__main__":
    main()
