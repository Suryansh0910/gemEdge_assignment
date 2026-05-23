"""
app.py — GemEdge Streamlit Dashboard
Run: streamlit run app.py
"""
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

OUTPUT = __import__("pathlib").Path(__file__).parent / "output"

st.set_page_config(
    page_title="GemEdge — Procurement Intelligence",
    page_icon="🏛️",
    layout="wide",
)

# ── load data ─────────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    bids    = pd.read_csv(OUTPUT / "bids_clean.csv")
    vendors = pd.read_csv(OUTPUT / "vendors_clean.csv")
    insights_path = OUTPUT / "insights.json"
    insights = json.loads(insights_path.read_text()) if insights_path.exists() else {}
    val_path = OUTPUT / "validation_report.json"
    val_report = json.loads(val_path.read_text()) if val_path.exists() else {}
    return bids, vendors, insights, val_report

bids, vendors, insights, val_report = load_data()

# ── sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.title("🏛️ GemEdge Filters")

ministries = ["All"] + sorted(bids["ministry"].dropna().unique().tolist())
sel_min    = st.sidebar.selectbox("Ministry", ministries)

categories = ["All"] + sorted(bids["category"].dropna().unique().tolist())
sel_cat    = st.sidebar.selectbox("Category", categories)

min_price, max_price = 0, int(bids["winner_price"].max()) if bids["winner_price"].max() > 0 else 1000000
price_range = st.sidebar.slider("Winner Price (₹)", min_price, max_price, (min_price, max_price))

anomaly_only = st.sidebar.checkbox("Show anomalies only")

# apply filters
df = bids.copy()
if sel_min != "All":
    df = df[df["ministry"] == sel_min]
if sel_cat != "All":
    df = df[df["category"] == sel_cat]
df = df[(df["winner_price"] >= price_range[0]) & (df["winner_price"] <= price_range[1])]
if anomaly_only:
    df = df[df["anomaly_flag"] != "ok"]

# ── header ────────────────────────────────────────────────────────────────────
st.title("🏛️ GemEdge — GeM Procurement Intelligence Dashboard")
st.caption(f"Source: bidplus.gem.gov.in/all-bids  |  {len(bids):,} awarded bids scraped")

# ── KPI cards ─────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Bids",         f"{len(df):,}")
k2.metric("Avg Winner Price",   f"₹{df['winner_price'][df['winner_price']>0].mean():,.0f}" if (df['winner_price']>0).any() else "N/A")
k3.metric("Avg Bidders/Bid",    f"{df['num_bidders'][df['num_bidders']>0].mean():.1f}" if (df['num_bidders']>0).any() else "N/A")
k4.metric("Repeat Winners",     f"{df['is_repeat_winner'].sum():,}")
k5.metric("Anomalies",          f"{(df['anomaly_flag'] != 'ok').sum():,}")

st.divider()

# ── DATA QUALITY & VALIDATION ─────────────────────────────────────────────────
st.header("🔍 Data Quality & Validation")

vq1, vq2, vq3, vq4 = st.columns(4)
bids_status   = val_report.get("bids", {}).get("status", "N/A")
vendors_status = val_report.get("vendors", {}).get("status", "N/A")
bids_errors   = len(val_report.get("bids", {}).get("errors", []))
bids_warnings = len(val_report.get("bids", {}).get("warnings", []))

vq1.metric("Bids Schema",    bids_status,    delta="0 errors" if bids_status == "PASS" else f"{bids_errors} errors",
           delta_color="normal" if bids_status == "PASS" else "inverse")
vq2.metric("Vendors Schema", vendors_status, delta="0 errors" if vendors_status == "PASS" else "FAIL",
           delta_color="normal" if vendors_status == "PASS" else "inverse")
vq3.metric("Duplicate Rows Removed", "17", delta="vendor rows", delta_color="off")
vq4.metric("Schema Warnings", str(bids_warnings), delta="null-rate alerts", delta_color="off")

# null rates table
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Bids — Column Null Rates")
    null_rates = val_report.get("bids", {}).get("null_rates", {})
    if null_rates:
        nr_df = pd.DataFrame(list(null_rates.items()), columns=["Column", "Null Rate"])
        st.dataframe(nr_df, use_container_width=True, hide_index=True)
    # show any warnings
    warnings = val_report.get("bids", {}).get("warnings", [])
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warnings"):
            for w in warnings:
                st.warning(w)

with col_b:
    st.subheader("Vendors — Column Null Rates")
    vnull = val_report.get("vendors", {}).get("null_rates", {})
    if vnull:
        vn_df = pd.DataFrame(list(vnull.items()), columns=["Column", "Null Rate"])
        st.dataframe(vn_df, use_container_width=True, hide_index=True)

    st.subheader("Deduplication Summary")
    dedup_data = {
        "Stage": ["Raw vendor rows", "After exact dedup", "After rank-level dedup", "Rows removed"],
        "Count": ["28,918", "~28,918", "28,901", "17"],
    }
    st.dataframe(pd.DataFrame(dedup_data), use_container_width=True, hide_index=True)

st.divider()

# ── row 1: top winners + bidder distribution ──────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    st.subheader("🏆 Top 15 Repeat Winners")
    top_w = (df[df["winner_name_clean"].notna()]
             .groupby("winner_name_clean").size()
             .sort_values(ascending=False).head(15).reset_index())
    top_w.columns = ["Winner", "Bids Won"]
    fig = px.bar(top_w, x="Bids Won", y="Winner", orientation="h",
                 color="Bids Won", color_continuous_scale="Blues",
                 title="")
    fig.update_layout(height=450, showlegend=False, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.subheader("👥 Bidder Count Distribution")
    bd = df[df["num_bidders"] > 0]["num_bidders"].clip(upper=20)
    fig2 = px.histogram(bd, nbins=20, labels={"value": "Number of Bidders"},
                        color_discrete_sequence=["#1f77b4"])
    fig2.add_vline(x=3, line_dash="dash", line_color="red",
                   annotation_text=">3 threshold")
    fig2.update_layout(height=450, showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)

# ── row 2: ministry bid count + L1-L2 gap ────────────────────────────────────
c3, c4 = st.columns(2)

with c3:
    st.subheader("🏢 Bids by Ministry (Top 15)")
    top_m = df["ministry"].value_counts().head(15).reset_index()
    top_m.columns = ["Ministry", "Count"]
    fig3 = px.bar(top_m, x="Count", y="Ministry", orientation="h",
                  color="Count", color_continuous_scale="Oranges")
    fig3.update_layout(height=450, showlegend=False, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig3, use_container_width=True)

with c4:
    st.subheader("📊 L1 vs L2 Price Gap %")
    gap_df = df[(df["price_gap_pct"].notna()) & (df["price_gap_pct"].abs() < 200)]
    if len(gap_df):
        fig4 = px.box(gap_df, y="price_gap_pct",
                      labels={"price_gap_pct": "Gap % (L2-L1)/L2"},
                      color_discrete_sequence=["#2ca02c"])
        fig4.add_hline(y=gap_df["price_gap_pct"].median(), line_dash="dash",
                       annotation_text=f"Median {gap_df['price_gap_pct'].median():.1f}%")
        fig4.update_layout(height=450)
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("No gap data available for current filter.")

st.divider()

# ── MINISTRY-WISE BREAKDOWN ───────────────────────────────────────────────────
st.header("🏢 Ministry-wise Intelligence Breakdown")

min_grp = df[df["ministry"] != "Unknown Ministry"].groupby("ministry")
min_rows = []
for ministry, grp in min_grp:
    priced  = grp[grp["winner_price"] > 0]
    nb_grp  = grp[grp["num_bidders"] > 0]
    pct_comp = round(len(nb_grp[nb_grp["num_bidders"] > 3]) / len(nb_grp) * 100, 1) if len(nb_grp) else 0
    known_g  = grp[grp["winner_name_clean"].notna()]
    top_winner = (known_g["winner_name_clean"].value_counts().index[0]
                  if len(known_g) > 0 else "—")
    top_wins = int(known_g["winner_name_clean"].value_counts().iloc[0]) if len(known_g) > 0 else 0
    min_rows.append({
        "Ministry"             : ministry,
        "Total Bids"           : len(grp),
        "Avg Winner Price (₹)" : int(priced["winner_price"].mean()) if len(priced) else 0,
        "Median Winner Price (₹)": int(priced["winner_price"].median()) if len(priced) else 0,
        "Competitive % (>3 bidders)": pct_comp,
        "Top Winner"           : top_winner,
        "Top Winner Wins"      : top_wins,
    })

min_df = pd.DataFrame(min_rows).sort_values("Total Bids", ascending=False)

# two charts side by side
m1, m2 = st.columns(2)
with m1:
    st.subheader("Avg Contract Size by Ministry (Top 12)")
    plot_m = min_df[min_df["Avg Winner Price (₹)"] > 0].head(12).copy()
    fig_m1 = px.bar(
        plot_m.sort_values("Avg Winner Price (₹)", ascending=True),
        x="Avg Winner Price (₹)", y="Ministry", orientation="h",
        color="Avg Winner Price (₹)", color_continuous_scale="Teal",
        labels={"Avg Winner Price (₹)": "Avg Price (₹)"},
    )
    fig_m1.update_layout(height=420, showlegend=False)
    st.plotly_chart(fig_m1, use_container_width=True)

with m2:
    st.subheader("Competitiveness % by Ministry (Top 12)")
    fig_m2 = px.bar(
        min_df.head(12).sort_values("Competitive % (>3 bidders)", ascending=True),
        x="Competitive % (>3 bidders)", y="Ministry", orientation="h",
        color="Competitive % (>3 bidders)", color_continuous_scale="RdYlGn",
        range_color=[0, 100],
    )
    fig_m2.add_vline(x=38.5, line_dash="dash", line_color="gray",
                     annotation_text="Overall avg 38.5%")
    fig_m2.update_layout(height=420, showlegend=False)
    st.plotly_chart(fig_m2, use_container_width=True)

st.subheader("Full Ministry Breakdown Table")
st.dataframe(
    min_df.style.format({
        "Avg Winner Price (₹)": "₹{:,.0f}",
        "Median Winner Price (₹)": "₹{:,.0f}",
        "Competitive % (>3 bidders)": "{:.1f}%",
    }),
    use_container_width=True, height=400,
)

st.divider()

# ── REPEAT WINNER DEEP DIVE ───────────────────────────────────────────────────
st.header("🔁 Repeat Winner Deep Dive")

deep = insights.get("repeat_winners_deep", [])
if deep:
    # summary cards for top 5
    cols = st.columns(len(deep))
    for col, r in zip(cols, deep):
        with col:
            st.metric(r["winner"][:30], f"{r['total_wins']} wins")
            st.caption(
                f"Avg price: ₹{r['avg_winner_price']:,.0f}\n"
                f"L1-L2 advantage: {r['avg_l1_l2_adv_pct']}%\n"
                f"Single-bidder wins: {r['single_bidder_wins']}"
                if r["avg_winner_price"] else
                f"Single-bidder wins: {r['single_bidder_wins']}"
            )

    st.divider()

    # detailed table
    deep_rows = []
    for r in deep:
        top_cat = ", ".join(list(r["top_categories"].keys())[:2])
        top_min = ", ".join(list(r["top_ministries"].keys())[:2])
        deep_rows.append({
            "Winner"            : r["winner"],
            "Total Wins"        : r["total_wins"],
            "Top Categories"    : top_cat,
            "Top Ministries"    : top_min,
            "Avg Winner Price"  : f"₹{r['avg_winner_price']:,.0f}" if r["avg_winner_price"] else "—",
            "L1-L2 Advantage %": r["avg_l1_l2_adv_pct"],
            "Single-Bidder Wins": r["single_bidder_wins"],
        })
    st.subheader("Top 5 Repeat Winners — Enriched Profile")
    st.dataframe(pd.DataFrame(deep_rows), use_container_width=True, hide_index=True)

    # ministry concentration of repeat winners
    st.subheader("Ministries with Most Repeat Winners")
    conc = insights.get("repeat_winner_ministry_concentration", {})
    if conc:
        conc_df = pd.DataFrame(list(conc.items()), columns=["Ministry", "Unique Repeat Winners"])
        fig_conc = px.bar(conc_df, x="Unique Repeat Winners", y="Ministry", orientation="h",
                          color="Unique Repeat Winners", color_continuous_scale="Purples")
        fig_conc.update_layout(height=300, showlegend=False, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_conc, use_container_width=True)

    # scatter: winner wins vs avg price advantage
    if len(deep) > 1:
        adv_df = pd.DataFrame([
            {"Winner": r["winner"][:25], "Wins": r["total_wins"],
             "Avg Price (₹)": r["avg_winner_price"] or 0,
             "L1-L2 Adv %": r["avg_l1_l2_adv_pct"] or 0}
            for r in deep
        ])
        fig_adv = px.scatter(adv_df, x="Wins", y="L1-L2 Adv %",
                             size="Avg Price (₹)", text="Winner",
                             title="Win Count vs Price Advantage (bubble = avg contract size)",
                             labels={"Wins": "Number of Wins", "L1-L2 Adv %": "Avg L1-L2 Gap %"})
        fig_adv.update_traces(textposition="top center")
        fig_adv.update_layout(height=400)
        st.plotly_chart(fig_adv, use_container_width=True)
else:
    st.info("Run insights.py first to populate repeat winner deep dive data.")

st.divider()

# ── row 3: scatter + category treemap ────────────────────────────────────────
c5, c6 = st.columns(2)

with c5:
    st.subheader("💰 Winner Price vs Bidder Count")
    scatter_df = df[(df["winner_price"] > 0) & (df["num_bidders"] > 0)].copy()
    if len(scatter_df):
        fig5 = px.scatter(scatter_df, x="num_bidders", y="winner_price",
                          hover_data=["category", "ministry", "winner_name_clean"],
                          color="anomaly_flag", log_y=True,
                          labels={"num_bidders": "Bidders", "winner_price": "Winner Price (₹, log)"})
        fig5.update_layout(height=400)
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("No data for current filters.")

with c6:
    st.subheader("📦 Top Categories")
    top_c = df["category"].value_counts().head(20).reset_index()
    top_c.columns = ["Category", "Count"]
    fig6 = px.treemap(top_c, path=["Category"], values="Count",
                      color="Count", color_continuous_scale="Viridis")
    fig6.update_layout(height=400)
    st.plotly_chart(fig6, use_container_width=True)

# ── anomaly table ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("⚠️ Anomalous Bids")
anom_df = df[df["anomaly_flag"] != "ok"][
    ["bid_number", "category", "ministry", "winner_name_clean",
     "winner_price", "num_bidders", "anomaly_flag"]
].head(100)
if len(anom_df):
    st.dataframe(anom_df, use_container_width=True)
else:
    st.success("No anomalies in current filter.")

# ── full data table ───────────────────────────────────────────────────────────
st.divider()
with st.expander(f"📋 Full Data Table ({len(df):,} rows)"):
    show_cols = ["bid_number", "category", "ministry", "department",
                 "quantity", "winner_name_clean", "winner_price",
                 "l2_price", "price_gap_pct", "num_bidders",
                 "award_date", "anomaly_flag"]
    st.dataframe(df[show_cols], use_container_width=True)
    csv = df.to_csv(index=False).encode()
    st.download_button("⬇️ Download CSV", csv, "gemedge_export.csv", "text/csv")

st.caption("Built with Playwright · BeautifulSoup4 · Pandas · Streamlit · Plotly | GemEdge Assignment")
