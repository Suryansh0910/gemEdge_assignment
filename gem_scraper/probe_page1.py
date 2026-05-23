"""
probe_page1.py — Fetch EXACTLY page 1 of awarded bids and print raw data.
No filtering, no cleaning, no assumptions. Just show what the API returns.
"""

import asyncio, json, re, requests
from playwright.async_api import async_playwright

TARGET  = "https://bidplus.gem.gov.in/all-bids"
API_URL = "https://bidplus.gem.gov.in/all-bids-data"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": TARGET,
    "Origin": "https://bidplus.gem.gov.in",
}

# ── Step 1: Browser session to get cookies + CSRF ───────────────────────────
async def get_session():
    captured = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()

        def on_request(req):
            if "all-bids-data" in req.url and req.method == "POST":
                body = req.post_data or ""
                m = re.search(r"csrf_bd_gem_nk=([a-f0-9]+)", body)
                if m:
                    captured["csrf"] = m.group(1)
                    print(f"  [+] CSRF captured: {m.group(1)}")

        page.on("request", on_request)
        print("[1] Loading page and applying awarded filter...")
        await page.goto(TARGET, wait_until="networkidle", timeout=60000)

        # Apply awarded filter via JS
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(1500)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(3000)

        # Grab cookies
        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        captured["cookies"] = cookies
        print(f"  [+] Cookies captured: {list(cookies.keys())}")

        await browser.close()
    return captured

# ── Step 2: Hit API for page 1 ───────────────────────────────────────────────
def fetch_page1(session_data):
    csrf    = session_data["csrf"]
    cookies = session_data["cookies"]

    payload = {
        "param": {"searchBid": "", "searchType": "fullText"},
        "filter": {
            "bidStatusType": "bidrastatus",
            "byType": "all",
            "highBidValue": "",
            "byEndDate": {"from": "", "to": ""},
            "sort": "Bid-End-Date-Latest",
            "byStatus": "bid_awarded",
        },
        "page": 1,
    }

    payload_json = json.dumps(payload, separators=(",", ":"))
    post_data    = f"payload={requests.utils.quote(payload_json)}&csrf_bd_gem_nk={csrf}"

    sess = requests.Session()
    sess.headers.update(HEADERS)
    for k, v in cookies.items():
        sess.cookies.set(k, v)

    print("\n[2] Posting to API for page 1...")
    r = sess.post(API_URL, data=post_data, timeout=30)
    print(f"  HTTP {r.status_code}")
    return r.json()

# ── Step 3: Print every field of every doc ───────────────────────────────────
def show_results(data):
    try:
        inner    = data["response"]["response"]
        num_found = inner["numFound"]
        docs     = inner["docs"]
    except (KeyError, TypeError) as e:
        print(f"Unexpected response shape: {e}")
        print(json.dumps(data, indent=2)[:3000])
        return

    print(f"\n{'='*70}")
    print(f"  Total awarded bids on GeM: {num_found:,}")
    print(f"  Records on page 1: {len(docs)}")
    print(f"{'='*70}\n")

    for i, doc in enumerate(docs, 1):
        print(f"── Record {i} ──────────────────────────────────────────")
        for key, val in doc.items():
            print(f"  {key:<45} = {val}")
        print()

    # Also save raw JSON for inspection
    with open("output/page1_raw.json", "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n[+] Raw JSON saved to output/page1_raw.json")

# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    session_data = await get_session()
    if "csrf" not in session_data:
        print("ERROR: CSRF token not captured. Check filters.")
        return
    raw = fetch_page1(session_data)
    show_results(raw)

asyncio.run(main())
