"""
lookup_bid.py — Search for a specific bid number across ALL filter combinations.
"""
import asyncio, json, re, requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

URL     = "https://bidplus.gem.gov.in/all-bids"
API_URL = "https://bidplus.gem.gov.in/all-bids-data"
BID_DETAIL_URL = "https://bidplus.gem.gov.in/bidding/bid/getBidResultView/{}"
BID_VIEW_URL   = "https://bidplus.gem.gov.in/bidding/bid/showbidlist/{}"

SEARCH_TERM = "GEM/2026/B/7484476"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": URL,
    "Origin": "https://bidplus.gem.gov.in",
}

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        # Capture CSRF + cookies
        csrf    = {}
        cookies = {}

        def on_req(req):
            if "all-bids-data" in req.url and req.method == "POST":
                body = req.post_data or ""
                m = re.search(r"csrf_bd_gem_nk=([a-f0-9]+)", body)
                if m:
                    csrf["token"] = m.group(1)

        page.on("request", on_req)

        print(f"[1] Loading site...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2000)
        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}

        # Trigger a call to get CSRF
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(2000)

        print(f"   CSRF: {csrf.get('token', 'not captured')}")
        await browser.close()

    # ── Now search via API with different filter combos ───────────────────
    sess = requests.Session()
    sess.headers.update(HEADERS)
    for k, v in cookies.items():
        sess.cookies.set(k, v)

    token = csrf.get("token", "")

    filter_combos = [
        ("ongoing_bids",  "ongoing_bids",  "Ongoing"),
        ("bidrastatus",   "bid_awarded",   "Bid/RA → Awarded"),
        ("bidrastatus",   "bid_ongoing",   "Bid/RA → Ongoing"),
        ("bidrastatus",   "fin_evaluated", "Bid/RA → Fin Evaluated"),
        ("bidrastatus",   "tech_evaluated","Bid/RA → Tech Evaluated"),
        ("bidrastatus",   "",              "Bid/RA → All"),
        ("ongoing_bids",  "",              "All ongoing"),
    ]

    print(f"\n{'='*65}")
    print(f"Searching: {SEARCH_TERM}")
    print(f"{'='*65}")

    found_doc = None
    found_filter = None

    for status_type, by_status, label in filter_combos:
        payload = {
            "param": {"searchBid": SEARCH_TERM, "searchType": "fullText"},
            "filter": {
                "bidStatusType": status_type,
                "byType": "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": "Bid-End-Date-Latest",
                "byStatus": by_status,
            },
            "page": 1,
        }
        payload_json = json.dumps(payload, separators=(",", ":"))
        post_data    = f"payload={requests.utils.quote(payload_json)}&csrf_bd_gem_nk={token}"

        r = sess.post(API_URL, data=post_data, timeout=30)

        if r.status_code == 200:
            try:
                body  = r.json()
                inner = body["response"]["response"]
                num   = inner.get("numFound", 0)
                docs  = inner.get("docs", [])
                status_str = f"✅ FOUND {num} record(s)" if num > 0 else "❌ No data"
                print(f"\n  [{label}] → {status_str}")
                if docs:
                    found_doc    = docs[0]
                    found_filter = label
                    for k, v in docs[0].items():
                        print(f"    {k:<50} {v}")
            except Exception as e:
                print(f"\n  [{label}] → Parse error: {e} | Raw: {r.text[:200]}")
        else:
            print(f"\n  [{label}] → HTTP {r.status_code}: {r.text[:100]}")

    # ── If found, fetch its detail page ──────────────────────────────────
    if found_doc:
        rec_id = found_doc.get("id")
        print(f"\n{'='*65}")
        print(f"DETAIL PAGE for id={rec_id}")
        print(f"{'='*65}")

        # Try result view
        r2 = sess.get(BID_DETAIL_URL.format(rec_id), timeout=30)
        print(f"\nResult view HTTP {r2.status_code}")
        if r2.status_code == 200:
            soup   = BeautifulSoup(r2.text, "html.parser")
            tables = soup.find_all("table")
            print(f"Tables found: {len(tables)}")
            for ti, table in enumerate(tables):
                rows = table.find_all("tr")
                print(f"\n  Table {ti}:")
                for row in rows:
                    cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])]
                    if any(cells):
                        print(f"    {cells}")

        # Try bid list view
        r3 = sess.get(BID_VIEW_URL.format(rec_id), timeout=30)
        print(f"\nBid list view HTTP {r3.status_code} (len={len(r3.text)})")
        if r3.status_code == 200 and len(r3.text) > 500:
            soup2 = BeautifulSoup(r3.text, "html.parser")
            # Get all visible text sections
            for tag in soup2.find_all(["h1","h2","h3","h4","table","dl"]):
                txt = tag.get_text(strip=True)
                if txt and len(txt) > 3:
                    print(f"  <{tag.name}>: {txt[:200]}")
    else:
        print(f"\n{'='*65}")
        print(f"Bid '{SEARCH_TERM}' NOT FOUND in any filter combination.")
        print(f"It may be cancelled, deleted, or use a different search key.")
        print(f"{'='*65}")

asyncio.run(main())
