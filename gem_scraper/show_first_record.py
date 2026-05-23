"""
show_first_record.py — Show EVERYTHING about the very first record:
1. All API fields from the listing
2. The full detail/result page HTML parsed into structured data
"""
import asyncio, json, re, requests
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

URL     = "https://bidplus.gem.gov.in/all-bids"
API_URL = "https://bidplus.gem.gov.in/all-bids-data"
BID_URL = "https://bidplus.gem.gov.in/bidding/bid/getBidResultView/{}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": URL,
    "Origin": "https://bidplus.gem.gov.in",
}

async def get_session_and_first_record():
    captured = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        async def capture_response(resp):
            if "all-bids-data" in resp.url:
                try:
                    body = await resp.json()
                    captured["api_body"] = body
                except:
                    pass

        page.on("response", capture_response)

        print("[1] Loading site...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)

        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        captured["cookies"] = cookies

        # Intercept CSRF from any POST
        def on_req(req):
            if "all-bids-data" in req.url and req.method == "POST":
                body = req.post_data or ""
                m = re.search(r"csrf_bd_gem_nk=([a-f0-9]+)", body)
                if m:
                    captured["csrf"] = m.group(1)
        page.on("request", on_req)

        # Trigger a fresh API call to capture CSRF
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(3000)

        await browser.close()
    return captured

def fetch_detail_page(record_id, cookies):
    detail_url = BID_URL.format(record_id)
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Referer": URL,
    })
    for k, v in cookies.items():
        sess.cookies.set(k, v)
    print(f"\n[3] Fetching detail page: {detail_url}")
    r = sess.get(detail_url, timeout=30)
    print(f"    HTTP {r.status_code}")
    return r.text

def parse_detail_page(html, record_id):
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # Save raw HTML
    with open(f"output/detail_{record_id}.html", "w") as f:
        f.write(html)

    # Try to extract ALL tables on the page
    tables = soup.find_all("table")
    print(f"\n    Found {len(tables)} tables on detail page")

    all_table_data = []
    for ti, table in enumerate(tables):
        rows = table.find_all("tr")
        table_data = []
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if cells:
                table_data.append(cells)
        if table_data:
            all_table_data.append({"table_index": ti, "rows": table_data})

    # Extract key sections
    # Bid basic info
    info_divs = soup.find_all(["div", "p", "span"], class_=re.compile(r"bid|detail|info|label|value", re.I))

    # All visible text sections
    headings = soup.find_all(["h1","h2","h3","h4","h5","h6"])
    heading_texts = [h.get_text(strip=True) for h in headings]

    # dl/dt/dd pairs (common for detail pages)
    dl_pairs = {}
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            dl_pairs[dt.get_text(strip=True)] = dd.get_text(strip=True)

    # Key-value from tables (label: value pattern)
    kv_data = {}
    for table in tables:
        for row in table.find_all("tr"):
            cells = row.find_all(["td","th"])
            if len(cells) == 2:
                kv_data[cells[0].get_text(strip=True)] = cells[1].get_text(strip=True)

    return {
        "headings": heading_texts,
        "dl_pairs": dl_pairs,
        "kv_from_tables": kv_data,
        "all_tables": all_table_data,
    }

async def main():
    session_data = await get_session_and_first_record()

    api_body = session_data.get("api_body", {})
    cookies  = session_data.get("cookies", {})
    csrf     = session_data.get("csrf", "")

    # Get first record from API
    try:
        docs = api_body["response"]["response"]["docs"]
        num_found = api_body["response"]["response"]["numFound"]
        first = docs[0]
    except (KeyError, IndexError):
        print("Could not get first doc from API")
        return

    print(f"\n{'='*65}")
    print(f"TOTAL RECORDS ON SITE (default view): {num_found:,}")
    print(f"{'='*65}")
    print(f"\n[2] FIRST RECORD — ALL API FIELDS:")
    print(f"{'─'*65}")
    for k, v in first.items():
        print(f"  {k:<50} {v}")

    # Fetch detail page using the record id
    record_id = first["id"]
    html = fetch_detail_page(record_id, cookies)

    detail = parse_detail_page(html, record_id)

    print(f"\n{'='*65}")
    print(f"DETAIL PAGE DATA (id={record_id})")
    print(f"{'='*65}")

    if detail["headings"]:
        print(f"\nPage Headings:")
        for h in detail["headings"]:
            print(f"  • {h}")

    if detail["dl_pairs"]:
        print(f"\nKey-Value pairs (dl/dt/dd):")
        for k, v in detail["dl_pairs"].items():
            print(f"  {k:<40} {v}")

    if detail["kv_from_tables"]:
        print(f"\nKey-Value from tables (2-column rows):")
        for k, v in detail["kv_from_tables"].items():
            if k.strip():
                print(f"  {k:<40} {v}")

    print(f"\nAll Tables:")
    for t in detail["all_tables"]:
        print(f"\n  Table {t['table_index']}:")
        for row in t["rows"]:
            print(f"    {row}")

    print(f"\n[+] Raw detail HTML saved to output/detail_{record_id}.html")

asyncio.run(main())
