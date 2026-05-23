"""
insights.py — Assignment-required analytics.
Input:  output/bids_clean.csv + output/vendors_clean.csv
Output: prints summary + saves output/insights.json
"""
import json
import pandas as pd

OUTPUT = __import__("pathlib").Path(__file__).parent / "output"


def run():
    bids    = pd.read_csv(OUTPUT / "bids_clean.csv")
    vendors = pd.read_csv(OUTPUT / "vendors_clean.csv")

    print("=" * 60)
    print("GemEdge — Procurement Intelligence Insights")
    print("=" * 60)

    results = {}

    # ── 1. % bids with more than 3 participants ───────────────────
    bids_with_data  = bids[bids["num_bidders"] > 0]
    pct_gt3         = round(len(bids_with_data[bids_with_data["num_bidders"] > 3])
                            / len(bids_with_data) * 100, 1) if len(bids_with_data) else 0
    results["pct_bids_gt3_bidders"] = pct_gt3
    print(f"\n[1] Bids with >3 participants : {pct_gt3}%")
    print(f"    Avg bidders per bid        : {bids_with_data['num_bidders'].mean():.1f}")
    print(f"    Max bidders in one bid     : {int(bids_with_data['num_bidders'].max())}")

    # ── 2. L1 vs L2 price gap ─────────────────────────────────────
    gap_df = bids[(bids["winner_price"] > 0) & (bids["l2_price"] > 0) & (bids["price_gap_pct"].notna())]
    avg_gap = round(gap_df["price_gap_pct"].mean(), 2) if len(gap_df) else 0
    med_gap = round(gap_df["price_gap_pct"].median(), 2) if len(gap_df) else 0
    results["avg_l1_l2_gap_pct"] = avg_gap
    results["median_l1_l2_gap_pct"] = med_gap
    print(f"\n[2] L1 vs L2 Price Gap")
    print(f"    Average gap  : {avg_gap}%")
    print(f"    Median gap   : {med_gap}%")
    print(f"    Bids with gap data: {len(gap_df):,}")

    # ── 3. Repeat winners (basic + deep) ─────────────────────────
    known = bids[bids["winner_name_clean"].notna()].copy()
    win_counts = known["winner_name_clean"].value_counts()
    repeat_winners = win_counts[win_counts > 1]

    top10 = win_counts.head(10)
    results["top_10_repeat_winners"] = top10.to_dict()
    print(f"\n[3] Top 10 Repeat Winners")
    for name, count in top10.items():
        print(f"    {count:>3}x  {name}")

    # deep: categories each repeat winner dominates
    repeat_names = set(repeat_winners.index)
    repeat_df = known[known["winner_name_clean"].isin(repeat_names)]

    # top 5 by win count with enriched stats
    deep_repeat = []
    for name in win_counts.head(5).index:
        w = known[known["winner_name_clean"] == name]
        top_cats = w["category"].value_counts().head(3).to_dict()
        top_mins = w["ministry"].value_counts().head(3).to_dict()
        prices = w[w["winner_price"] > 0]["winner_price"]
        # avg price advantage vs L2 for this winner
        gap_rows = w[(w["winner_price"] > 0) & (w["l2_price"] > 0) & w["price_gap_pct"].notna()]
        avg_adv = round(gap_rows["price_gap_pct"].mean(), 2) if len(gap_rows) else None
        deep_repeat.append({
            "winner"           : name,
            "total_wins"       : int(win_counts[name]),
            "top_categories"   : top_cats,
            "top_ministries"   : top_mins,
            "avg_winner_price" : round(float(prices.mean()), 2) if len(prices) else None,
            "avg_l1_l2_adv_pct": avg_adv,
            "single_bidder_wins": int((w["num_bidders"] == 1).sum()),
        })

    results["repeat_winners_deep"] = deep_repeat
    print(f"\n[3b] Deep Repeat Winner Analysis (top 5)")
    for r in deep_repeat:
        cats = ", ".join(list(r["top_categories"].keys())[:2])
        mins = ", ".join(list(r["top_ministries"].keys())[:2])
        print(f"    {r['winner'][:45]}")
        print(f"      wins={r['total_wins']}  single_bidder={r['single_bidder_wins']}  "
              f"avg_price=₹{r['avg_winner_price']:,.0f}  l1-l2_adv={r['avg_l1_l2_adv_pct']}%"
              if r["avg_winner_price"] else
              f"      wins={r['total_wins']}  single_bidder={r['single_bidder_wins']}")
        print(f"      categories: {cats}")
        print(f"      ministries: {mins}")

    # ministry concentration of repeat winners
    repeat_by_ministry = (repeat_df.groupby("ministry")["winner_name_clean"]
                          .nunique()
                          .sort_values(ascending=False)
                          .head(5))
    results["repeat_winner_ministry_concentration"] = repeat_by_ministry.to_dict()
    print(f"\n[3c] Ministries with most repeat winners")
    for m, cnt in repeat_by_ministry.items():
        print(f"    {cnt:>3} repeat winners  {m}")

    # ── 4. Bid value stats ────────────────────────────────────────
    price_df = bids[bids["winner_price"] > 0]["winner_price"]
    results["bid_value_stats"] = {
        "min"   : round(float(price_df.min()), 2),
        "max"   : round(float(price_df.max()), 2),
        "avg"   : round(float(price_df.mean()), 2),
        "median": round(float(price_df.median()), 2),
    }
    print(f"\n[4] Winner Price (L1) Distribution")
    print(f"    Min    : ₹{price_df.min():,.2f}")
    print(f"    Max    : ₹{price_df.max():,.2f}")
    print(f"    Avg    : ₹{price_df.mean():,.2f}")
    print(f"    Median : ₹{price_df.median():,.2f}")

    # ── 5. Top categories ─────────────────────────────────────────
    top_cats = bids["category"].value_counts().head(10)
    results["top_10_categories"] = top_cats.to_dict()
    print(f"\n[5] Top 10 Categories")
    for cat, cnt in top_cats.items():
        print(f"    {cnt:>5}  {str(cat)[:70]}")

    # ── 6. Top ministries (basic) ─────────────────────────────────
    top_min = bids["ministry"].value_counts().head(10)
    results["top_10_ministries"] = top_min.to_dict()
    print(f"\n[6] Top 10 Ministries by bid count")
    for m, cnt in top_min.items():
        print(f"    {cnt:>5}  {m}")

    # ── 7. Ministry-wise breakdown ────────────────────────────────
    min_grp = bids.groupby("ministry")
    ministry_stats = []
    for ministry, grp in min_grp:
        if ministry == "Unknown Ministry":
            continue
        priced = grp[grp["winner_price"] > 0]
        nb_grp = grp[grp["num_bidders"] > 0]
        pct_comp = round(len(nb_grp[nb_grp["num_bidders"] > 3]) / len(nb_grp) * 100, 1) if len(nb_grp) else 0
        known_g = grp[grp["winner_name_clean"].notna()]
        top_winner = (known_g["winner_name_clean"].value_counts().index[0]
                      if len(known_g) > 0 else None)
        top_winner_wins = int(known_g["winner_name_clean"].value_counts().iloc[0]) if len(known_g) > 0 else 0
        ministry_stats.append({
            "ministry"          : ministry,
            "total_bids"        : int(len(grp)),
            "avg_winner_price"  : round(float(priced["winner_price"].mean()), 2) if len(priced) else None,
            "median_winner_price": round(float(priced["winner_price"].median()), 2) if len(priced) else None,
            "pct_competitive"   : pct_comp,
            "top_winner"        : top_winner,
            "top_winner_wins"   : top_winner_wins,
        })

    ministry_stats.sort(key=lambda x: x["total_bids"], reverse=True)
    results["ministry_breakdown"] = ministry_stats

    print(f"\n[7] Ministry-wise Breakdown (top 10 by bid count)")
    print(f"    {'Ministry':<45} {'Bids':>5} {'Avg Price':>14} {'Competitive%':>13} {'Top Winner Wins':>15}")
    print(f"    {'-'*45} {'-'*5} {'-'*14} {'-'*13} {'-'*15}")
    for row in ministry_stats[:10]:
        avg_p = f"₹{row['avg_winner_price']:>12,.0f}" if row["avg_winner_price"] else "            N/A"
        print(f"    {str(row['ministry'])[:45]:<45} {row['total_bids']:>5} {avg_p} {row['pct_competitive']:>12.1f}% {row['top_winner_wins']:>15}")

    # ── 8. Anomaly summary ────────────────────────────────────────
    anom = bids["anomaly_flag"].value_counts()
    results["anomaly_summary"] = anom.to_dict()
    print(f"\n[8] Anomaly Flags")
    for flag, cnt in anom.items():
        print(f"    {cnt:>5}  {flag}")

    # ── 9. Dataset summary ────────────────────────────────────────
    results["dataset_summary"] = {
        "total_bids"       : len(bids),
        "bids_with_vendors": int((bids["winner_price"] > 0).sum()),
        "total_vendor_rows": len(vendors),
        "unique_vendors"   : int(vendors["vendor_name_clean"].nunique()),
        "unique_ministries": int(bids["ministry"].nunique()),
        "date_range_start" : str(bids["award_date"].min()),
        "date_range_end"   : str(bids["award_date"].max()),
    }
    print(f"\n[9] Dataset Summary")
    for k, v in results["dataset_summary"].items():
        print(f"    {k:<25} {v}")

    with open(OUTPUT / "insights.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✅ insights.json saved. Run: streamlit run app.py")
    return results


if __name__ == "__main__":
    run()
