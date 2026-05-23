"""
worker.py — identical across all 20 worker folders.
Reads config.json (worker_id, start_page, end_page, filter)
Reads ../../shared/session.json (cookies, csrf)
Saves ../../output/worker_XX.csv
"""
import json, time
from pathlib import Path
import requests
import pandas as pd

HERE   = Path(__file__).parent
ROOT   = HERE.parent.parent
SHARED = ROOT / "shared"
OUTPUT = ROOT / "output"

API_URL = "https://bidplus.gem.gov.in/all-bids-data"
URL     = "https://bidplus.gem.gov.in/all-bids"

HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type"    : "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer"         : URL,
    "Origin"          : "https://bidplus.gem.gov.in",
}

RETRY_MAX  = 4
RETRY_WAIT = 5
PAGE_PAUSE = 0.4


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

def fetch_page(sess, csrf, page_no, bid_filter):
    # build filter block based on what coordinator set
    if bid_filter == "bid_awarded":
        filter_block = {
            "bidStatusType": "bidrastatus",
            "byType"       : "all",
            "highBidValue" : "",
            "byEndDate"    : {"from": "", "to": ""},
            "sort"         : "Bid-End-Date-Latest",
            "byStatus"     : "bid_awarded",
        }
    else:
        filter_block = {
            "bidStatusType": "ongoing_bids",
            "byType"       : "all",
            "highBidValue" : "",
            "byEndDate"    : {"from": "", "to": ""},
            "sort"         : "Bid-End-Date-Latest",
            "byStatus"     : "",
        }

    payload  = {"param": {"searchBid": "", "searchType": "fullText"},
                "filter": filter_block, "page": page_no}
    pj       = json.dumps(payload, separators=(",", ":"))
    postdata = f"payload={requests.utils.quote(pj)}&csrf_bd_gem_nk={csrf}"

    for attempt in range(1, RETRY_MAX + 1):
        try:
            r = sess.post(API_URL, data=postdata, timeout=30)
            if r.status_code == 200:
                return r.json()["response"]["response"]["docs"]
            print(f"  page {page_no} attempt {attempt}: HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"  page {page_no} attempt {attempt}: {e}", flush=True)
        time.sleep(RETRY_WAIT * attempt)

    print(f"  page {page_no}: FAILED — skipping", flush=True)
    return []

def doc_to_row(doc):
    def first(key, default=""):
        v = doc.get(key, [])
        return (v[0] if v else default) if isinstance(v, list) else (v or default)

    parent = doc.get("b_bid_number_parent", [])
    return {
        "id"           : doc.get("id", ""),
        "bid_number"   : first("b_bid_number"),
        "parent_bid"   : parent[0] if parent else "",
        "ra_or_bid"    : "RA" if first("b_bid_type") == 2 else "Bid",
        "category"     : first("b_category_name"),
        "full_category": first("bd_category_name"),
        "quantity"     : first("b_total_quantity", 0),
        "item_count"   : first("b_is_bunch", 1),
        "status"       : first("b_status"),
        "is_custom"    : first("b_is_custom_item"),
        "is_high_value": first("is_high_value"),
        "is_boq"       : first("bd_details_is_boq", False),
        "start_date"   : first("final_start_date_sort"),
        "end_date"     : first("final_end_date_sort"),
        "ministry"     : first("ba_official_details_minName"),
        "department"   : first("ba_official_details_deptName"),
        "buyer_id"     : first("b.b_created_by"),
        "category_id"  : first("b_cat_id"),
    }

def run():
    cfg        = load_config()
    session    = load_session()
    wid        = cfg["worker_id"]
    start_page = cfg["start_page"]
    end_page   = cfg["end_page"]
    bid_filter = cfg.get("filter", "")
    csrf       = session["csrf"]

    OUTPUT.mkdir(exist_ok=True)
    out_csv    = OUTPUT / f"worker_{wid:02d}.csv"
    total_pgs  = end_page - start_page + 1

    print(f"Worker {wid:02d} | filter={bid_filter} | pages {start_page}–{end_page} ({total_pgs} pages)", flush=True)

    sess = make_session(session)
    rows = []

    for i, page_no in enumerate(range(start_page, end_page + 1), 1):
        docs = fetch_page(sess, csrf, page_no, bid_filter)
        for doc in docs:
            rows.append(doc_to_row(doc))
        if i % 10 == 0 or i == total_pgs:
            print(f"  W{wid:02d} | page {page_no} | {i}/{total_pgs} ({i/total_pgs*100:.0f}%) | {len(rows)} rows", flush=True)
        time.sleep(PAGE_PAUSE)

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"Worker {wid:02d} DONE — {len(rows)} rows → {out_csv.name}", flush=True)

if __name__ == "__main__":
    run()
