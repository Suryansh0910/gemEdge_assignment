"""
inspect_site.py — Open bidplus.gem.gov.in/all-bids, read page count,
total records, and print a sample card's raw HTML fields.
No filter applied — show default view first.
"""
import asyncio, json, re
from playwright.async_api import async_playwright

URL = "https://bidplus.gem.gov.in/all-bids"

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()

        captured_api = {}

        def on_response(resp):
            if "all-bids-data" in resp.url:
                captured_api["url"]    = resp.url
                captured_api["status"] = resp.status

        async def on_response_body(resp):
            if "all-bids-data" in resp.url:
                try:
                    body = await resp.json()
                    captured_api["body"] = body
                except Exception:
                    pass

        page.on("response", on_response)
        page.on("response", on_response_body)

        print("Loading site (default, no filter)...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)

        # ── Grab the record count text shown on screen ─────────────────────
        page_text = await page.inner_text("body")

        # Look for "Showing X - Y records of Z records"
        m = re.search(r"Showing[\s\S]{0,50}?(\d[\d,]+)\s+records", page_text)
        total_text = m.group(0).strip() if m else "Not found in page text"

        # Grab pagination info
        pagination = await page.query_selector_all(".pagination li")
        page_labels = []
        for p in pagination:
            page_labels.append(await p.inner_text())

        # Count visible bid cards
        cards = await page.query_selector_all(".card, .bid-card, [class*='bid']")
        card_count = len(cards)

        # Get first card HTML
        first_card = await page.query_selector(".card")
        first_html = ""
        if first_card:
            first_html = await first_card.inner_html()

        # Check available filter options (status, type)
        filter_options = {}
        for sel in ["#bidStatusType", "#bidStatus", "#byType", "select"]:
            opts = await page.query_selector_all(f"{sel} option")
            if opts:
                vals = [await o.inner_text() for o in opts]
                filter_options[sel] = vals

        print(f"\n{'='*65}")
        print("SITE INSPECTION — DEFAULT VIEW (no filter)")
        print(f"{'='*65}")
        print(f"Record count text : {total_text}")
        print(f"Pagination labels : {page_labels}")
        print(f"Visible cards     : {card_count}")
        print(f"\nFilter options found:")
        for k, v in filter_options.items():
            print(f"  {k}: {v}")

        # ── Now check what the API returned ────────────────────────────────
        if "body" in captured_api:
            body = captured_api["body"]
            try:
                inner = body["response"]["response"]
                num_found = inner.get("numFound", "?")
                docs = inner.get("docs", [])
                print(f"\nAPI numFound (all bids, no filter): {num_found:,}")
                print(f"API docs on page 1: {len(docs)}")
                print(f"\nFirst doc fields:")
                for k, v in docs[0].items():
                    print(f"  {k:<45} = {v}")
            except Exception as e:
                print(f"API parse error: {e}")
                print(json.dumps(body, indent=2)[:2000])
        else:
            print("\nNo API call captured yet.")

        # ── Now apply the awarded filter and check count ───────────────────
        print(f"\n{'='*65}")
        print("Applying bid_awarded filter...")
        print(f"{'='*65}")
        captured_api.clear()

        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(4000)

        page_text2 = await page.inner_text("body")
        m2 = re.search(r"Showing[\s\S]{0,80}?(\d[\d,]+)\s+records", page_text2)
        print(f"Record text after awarded filter: {m2.group(0).strip() if m2 else 'not found'}")

        if "body" in captured_api:
            body2 = captured_api["body"]
            try:
                inner2 = body2["response"]["response"]
                print(f"API numFound (awarded only): {inner2.get('numFound', '?'):,}")
                print(f"API docs returned: {len(inner2.get('docs', []))}")
            except Exception as e:
                print(f"API parse error: {e}")

        # ── Also check ONGOING bids count ──────────────────────────────────
        print(f"\n{'='*65}")
        print("Checking ongoing bids count...")
        print(f"{'='*65}")
        captured_api.clear()
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusFilter('bid_ongoing')")
        await page.wait_for_timeout(4000)

        if "body" in captured_api:
            body3 = captured_api["body"]
            try:
                inner3 = body3["response"]["response"]
                print(f"API numFound (ongoing): {inner3.get('numFound', '?'):,}")
            except:
                pass

        page_text3 = await page.inner_text("body")
        m3 = re.search(r"Showing[\s\S]{0,80}?(\d[\d,]+)\s+records", page_text3)
        print(f"Record text (ongoing): {m3.group(0).strip() if m3 else 'not found'}")

        await browser.close()

asyncio.run(main())
