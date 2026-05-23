"""Retry the 4 missing RA detail pages using Playwright proper navigation."""
import asyncio, json, re, pandas as pd
from pathlib import Path
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

OUTPUT = Path(__file__).parent / "output"
RA_IDS = [9324859, 9317326, 9315648, 9315948]

def clean_price(raw):
    if not raw:
        return None
    c = re.sub(r"[`₹Rs,\s]", "", str(raw))
    c = re.sub(r"\(.*?\)", "", c).strip()
    try:
        v = float(c)
        return None if v > 1e12 else round(v, 2)
    except Exception:
        return None

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()

        print("Getting fresh session via proper navigation...")
        await page.goto("https://bidplus.gem.gov.in/all-bids", wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(2000)
        await page.evaluate("bidStatusTypeFilter('bidrastatus')")
        await page.wait_for_timeout(1500)
        await page.evaluate("bidStatusFilter('bid_awarded')")
        await page.wait_for_timeout(2000)

        all_rows = []
        for bid_id in RA_IDS:
            url = f"https://bidplus.gem.gov.in/bidding/bid/getBidResultView/{bid_id}"
            await page.goto(url, referer="https://bidplus.gem.gov.in/all-bids",
                            wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1000)

            final_url = page.url
            html      = await page.content()
            soup      = BeautifulSoup(html, "html.parser")
            tables    = soup.find_all("table")

            print(f"  id={bid_id} | url={final_url} | tables={len(tables)}")

            for table in tables:
                headers   = [th.get_text(strip=True).lower() for th in table.find_all("th")]
                rank_col  = next((i for i, h in enumerate(headers) if "rank" in h), None)
                price_col = next((i for i, h in enumerate(headers) if "price" in h), None)
                name_col  = next((i for i, h in enumerate(headers)
                                  if "seller" in h or "name" in h or "vendor" in h), None)

                for tr in table.find_all("tr")[1:]:
                    cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                    if not cells:
                        continue
                    def safe(i):
                        return cells[i].strip() if i is not None and i < len(cells) else ""
                    name  = safe(name_col)
                    rank  = safe(rank_col)
                    price = clean_price(safe(price_col))
                    if name or rank:
                        all_rows.append({"bid_id": bid_id, "vendor_name": name,
                                         "vendor_rank": rank, "vendor_price": price,
                                         "price_raw": safe(price_col), "status_flag": ""})
                        print(f"    {rank} | {name[:60]} | {price}")

        await browser.close()

    if all_rows:
        new_df   = pd.DataFrame(all_rows)
        existing = pd.read_csv(OUTPUT / "all_vendors.csv")
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.to_csv(OUTPUT / "all_vendors.csv", index=False)
        print(f"\nAdded {len(all_rows)} rows -> all_vendors.csv now {len(combined):,} rows")
    else:
        print("\nNo new vendor rows found for these 4 RAs.")

    # now mark the 694 SSO-locked bids in bids_clean.csv
    bids = pd.read_csv(OUTPUT / "bids_clean.csv")
    vendors = pd.read_csv(OUTPUT / "all_vendors.csv")
    have_data = set(vendors["bid_id"].unique())
    bids["result_accessible"] = bids["id"].apply(
        lambda x: "yes" if x in have_data else
                  ("login_required" if bids.loc[bids["id"]==x, "ra_or_bid"].values[0] == "Bid"
                   else "no_result_yet")
    )
    bids.to_csv(OUTPUT / "bids_clean.csv", index=False)
    print(f"\nresult_accessible column added:")
    print(bids["result_accessible"].value_counts().to_string())

asyncio.run(main())
