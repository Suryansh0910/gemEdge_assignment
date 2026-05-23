"""
detail_worker.py — fetches getBidResultView/{id} for each assigned bid_id.
Parses vendor table → saves vendors_XX.csv
"""
import json, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import pandas as pd

HERE   = Path(__file__).parent
ROOT   = HERE.parent.parent
SHARED = ROOT / "shared"
OUTPUT = ROOT / "output"

RESULT_URL = "https://bidplus.gem.gov.in/bidding/bid/getBidResultView/{}"
URL        = "https://bidplus.gem.gov.in/all-bids"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer"   : URL,
}

RETRY_MAX  = 3
RETRY_WAIT = 4
PAGE_PAUSE = 0.5


def load_config():
    with open(HERE / "config.json") as f:
        return json.load(f)

def load_session():
    with open(SHARED / "session.json") as f:
        return json.load(f)

def make_session(session_data):
    sess = requests.Session()
    sess.headers.update(HEADERS)
    for k, v in session_data["cookies"].items():
        sess.cookies.set(k, v)
    return sess


def clean_price(raw):
    """Convert price string like '`11,000.00' → 11000.0"""
    if not raw:
        return None
    cleaned = re.sub(r"[`₹Rs,\s]", "", str(raw))
    cleaned = re.sub(r"\(.*?\)", "", cleaned).strip()
    try:
        val = float(cleaned)
        return None if val > 1e12 else val   # reject timestamp-like values
    except (ValueError, TypeError):
        return None


def parse_result_page(html, bid_id):
    """Extract vendor table rows from result page HTML."""
    soup   = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    rows   = []

    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

        # look for the vendor ranking table
        has_rank  = any("rank" in h for h in headers)
        has_price = any("price" in h or "amount" in h for h in headers)
        has_seller = any("seller" in h or "vendor" in h or "name" in h for h in headers)

        if not (has_rank or has_seller):
            continue

        # find column indices
        rank_col   = next((i for i, h in enumerate(headers) if "rank" in h), None)
        price_col  = next((i for i, h in enumerate(headers) if "price" in h or "amount" in h), None)
        name_col   = next((i for i, h in enumerate(headers) if "seller" in h or "vendor" in h or "name" in h), None)
        status_col = next((i for i, h in enumerate(headers) if "status" in h or "remark" in h or "disq" in h), None)

        for tr in table.find_all("tr")[1:]:   # skip header row
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not cells:
                continue

            def safe(idx):
                return cells[idx].strip() if idx is not None and idx < len(cells) else ""

            rank       = safe(rank_col)
            price_raw  = safe(price_col)
            name       = safe(name_col)
            status_flag = safe(status_col)

            # skip empty rows
            if not name and not rank:
                continue

            price = clean_price(price_raw)

            rows.append({
                "bid_id"      : bid_id,
                "vendor_name" : name,
                "vendor_rank" : rank,
                "vendor_price": price,
                "price_raw"   : price_raw,
                "status_flag" : status_flag,
            })

        if rows:
            break   # found the right table

    return rows


def fetch_detail(sess, bid_id):
    url = RESULT_URL.format(bid_id)
    for attempt in range(1, RETRY_MAX + 1):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            print(f"  id={bid_id} attempt {attempt}: HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  id={bid_id} attempt {attempt}: {e}", flush=True)
        time.sleep(RETRY_WAIT * attempt)
    return None


def run():
    cfg     = load_config()
    session = load_session()
    wid     = cfg["worker_id"]
    bid_ids = cfg.get("bid_ids", [])

    OUTPUT.mkdir(exist_ok=True)
    out_csv  = OUTPUT / f"vendors_{wid:02d}.csv"
    total    = len(bid_ids)

    print(f"Detail Worker {wid:02d} — {total} bids to fetch", flush=True)

    sess     = make_session(session)
    all_rows = []
    no_data  = 0

    for i, bid_id in enumerate(bid_ids, 1):
        html = fetch_detail(sess, bid_id)
        if html:
            rows = parse_result_page(html, bid_id)
            if rows:
                all_rows.extend(rows)
            else:
                no_data += 1
        else:
            no_data += 1

        if i % 50 == 0 or i == total:
            print(f"  DW{wid:02d} | {i}/{total} ({i/total*100:.0f}%) | {len(all_rows)} vendor rows | {no_data} no-data", flush=True)

        time.sleep(PAGE_PAUSE)

    df = pd.DataFrame(all_rows)
    df.to_csv(out_csv, index=False)
    print(f"Detail Worker {wid:02d} DONE — {len(all_rows)} vendor rows → {out_csv.name}", flush=True)


if __name__ == "__main__":
    run()
