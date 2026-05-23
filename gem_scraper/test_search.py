"""
test_search.py — Test site search with RA number vs Bid number.
Capture exactly what request gets sent and what comes back.
"""
import asyncio, json, re
from playwright.async_api import async_playwright

URL = "https://bidplus.gem.gov.in/all-bids"

RA_NO  = "GEM/2026/R/670103"   # RA number
BID_NO = "GEM/2026/B/7484220"  # Parent bid number

async def try_search(page, search_term, label):
    captured = {}

    async def capture(resp):
        if "all-bids-data" in resp.url:
            try:
                body = await resp.json()
                captured["body"] = body
                captured["status"] = resp.status
            except:
                pass

    page.on("response", capture)

    print(f"\n{'─'*60}")
    print(f"Searching: {label} → '{search_term}'")

    # Clear the search box and type
    search_box = await page.query_selector("#searchBid")
    if not search_box:
        # Try finding by inspecting all inputs
        inputs = await page.query_selector_all("input")
        print(f"  Found {len(inputs)} input elements:")
        for i, inp in enumerate(inputs):
            attrs = await inp.evaluate("el => ({type: el.type, name: el.name, id: el.id, placeholder: el.placeholder, class: el.className})")
            print(f"    [{i}] {attrs}")
        search_box = inputs[0] if inputs else None

    if search_box:
        await search_box.click(click_count=3)
        await search_box.fill(search_term)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(4000)
    else:
        print("  No search box found!")
        return

    # Check what came back
    page_text = await page.inner_text("body")
    no_data = "no data" in page_text.lower() or "no record" in page_text.lower() or "not found" in page_text.lower()

    if "body" in captured:
        body = captured["body"]
        try:
            inner = body["response"]["response"]
            num = inner.get("numFound", 0)
            docs = inner.get("docs", [])
            print(f"  API numFound: {num}")
            print(f"  Docs returned: {len(docs)}")
            if docs:
                for i, d in enumerate(docs[:3]):
                    print(f"  Doc {i+1}: {d.get('b_bid_number')} | {d.get('b_category_name')}")
            else:
                print("  → EMPTY RESULT (no docs)")
        except Exception as e:
            print(f"  Parse error: {e}")
            print(f"  Raw: {json.dumps(body)[:500]}")
    else:
        print(f"  No API response captured")
        print(f"  'No data' text on page: {no_data}")

    # Also check what payload was sent
    print(f"  Status code: {captured.get('status', 'not captured')}")

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        # Capture all POST request bodies
        post_bodies = []
        def on_req(req):
            if "all-bids-data" in req.url and req.method == "POST":
                post_bodies.append(req.post_data or "")

        page.on("request", on_req)

        print("[1] Loading site...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2000)

        # Inspect search box
        print("\nInspecting search elements on page:")
        inputs = await page.query_selector_all("input")
        for inp in inputs:
            attrs = await inp.evaluate("el => ({type: el.type, name: el.name, id: el.id, placeholder: el.placeholder})")
            print(f"  Input: {attrs}")

        buttons = await page.query_selector_all("button, [type='submit']")
        for btn in buttons:
            txt = await btn.inner_text()
            if txt.strip():
                print(f"  Button: '{txt.strip()}'")

        # Try searching with RA number
        await try_search(page, RA_NO, "RA Number")
        print(f"\n  POST body sent: {post_bodies[-1][:300] if post_bodies else 'none'}")

        # Reload and try with Bid number
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2000)
        post_bodies.clear()

        await try_search(page, BID_NO, "Parent Bid Number")
        print(f"\n  POST body sent: {post_bodies[-1][:300] if post_bodies else 'none'}")

        # Also check: what does the search payload look like for the default load?
        print(f"\n{'─'*60}")
        print("Checking direct bid detail page URL:")
        detail_url = f"https://bidplus.gem.gov.in/bidding/bid/getBidResultView/9353678"
        await page.goto(detail_url, wait_until="networkidle", timeout=60000)
        title = await page.title()
        h1 = await page.query_selector("h1")
        h1_text = await h1.inner_text() if h1 else "no h1"
        print(f"  Page title: {title}")
        print(f"  H1: {h1_text}")

        await browser.close()

asyncio.run(main())
