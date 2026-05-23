"""
cleaner.py — Validate schema, deduplicate, normalize, flag anomalies.
Input:  output/awarded_with_vendors.csv + output/all_vendors.csv
Output: output/bids_clean.csv + output/vendors_clean.csv
        output/validation_report.json
"""
import json, re
import pandas as pd

OUTPUT = __import__("pathlib").Path(__file__).parent / "output"

# ── schema definitions ────────────────────────────────────────────────────────
BIDS_SCHEMA = {
    "id"          : {"type": "int",    "required": True,  "unique": True},
    "bid_number"  : {"type": "str",    "required": True,  "unique": True,
                     "pattern": r"^GEM/\d{4}/[BR]/\d+$"},
    "category"    : {"type": "str",    "required": True},
    "quantity"    : {"type": "numeric","required": True,  "min": 0},
    "start_date"  : {"type": "date",   "required": False},
    "end_date"    : {"type": "date",   "required": False},
    "ministry"    : {"type": "str",    "required": False},
    "department"  : {"type": "str",    "required": False},
    "winner_price": {"type": "numeric","required": False, "min": 0, "max": 1e12},
    "l2_price"    : {"type": "numeric","required": False, "min": 0, "max": 1e12},
    "num_bidders" : {"type": "int",    "required": False, "min": 0},
    "ra_or_bid"   : {"type": "str",    "required": True,
                     "allowed": ["Bid", "RA"]},
}

VENDORS_SCHEMA = {
    "bid_id"      : {"type": "int",   "required": True},
    "vendor_name" : {"type": "str",   "required": True},
    "vendor_rank" : {"type": "str",   "required": False,
                     "pattern": r"^L\d+$"},
    "vendor_price": {"type": "numeric","required": False, "min": 0, "max": 1e12},
}


# ── schema validator ──────────────────────────────────────────────────────────
def validate_schema(df, schema, label):
    report = {"label": label, "rows": len(df), "errors": [], "warnings": [], "null_rates": {}}

    for col, rules in schema.items():
        if col not in df.columns:
            if rules.get("required"):
                report["errors"].append(f"MISSING required column: {col}")
            continue

        series = df[col]

        # null rate
        null_rate = round(series.isna().mean() * 100, 1)
        report["null_rates"][col] = f"{null_rate}%"
        if rules.get("required") and null_rate > 0:
            report["warnings"].append(f"{col}: {null_rate}% nulls in required field")

        # uniqueness
        if rules.get("unique"):
            dupes = series.dropna().duplicated().sum()
            if dupes:
                report["errors"].append(f"{col}: {dupes} duplicate values")

        # allowed values
        if "allowed" in rules:
            invalid = ~series.dropna().isin(rules["allowed"])
            if invalid.any():
                bad = series.dropna()[invalid].unique()[:3].tolist()
                report["errors"].append(f"{col}: invalid values {bad}")

        # pattern
        if "pattern" in rules and series.dtype == object:
            matches = series.dropna().str.match(rules["pattern"])
            bad_count = (~matches).sum()
            if bad_count:
                report["warnings"].append(f"{col}: {bad_count} rows don't match pattern {rules['pattern']}")

        # numeric range
        if rules.get("type") == "numeric" and pd.api.types.is_numeric_dtype(series):
            if "min" in rules:
                under = (series.dropna() < rules["min"]).sum()
                if under:
                    report["errors"].append(f"{col}: {under} values below min {rules['min']}")
            if "max" in rules:
                over = (series.dropna() > rules["max"]).sum()
                if over:
                    report["errors"].append(f"{col}: {over} values above max {rules['max']}")

    status = "PASS" if not report["errors"] else "FAIL"
    print(f"\n  Schema [{label}]: {status}")
    for e in report["errors"]:
        print(f"    ❌ {e}")
    for w in report["warnings"][:5]:
        print(f"    ⚠️  {w}")
    print(f"    Null rates: { {k:v for k,v in list(report['null_rates'].items())[:6]} }")
    report["status"] = status
    return report


# ── price cleaning ────────────────────────────────────────────────────────────
def clean_price(val):
    if pd.isna(val):
        return None
    cleaned = re.sub(r"[`₹Rs,\s]", "", str(val))
    cleaned = re.sub(r"\(.*?\)", "", cleaned).strip()
    try:
        f = float(cleaned)
        return None if f > 1e12 else round(f, 2)
    except (ValueError, TypeError):
        return None


# ── vendor name normalisation ─────────────────────────────────────────────────
def normalize_name(name):
    if pd.isna(name) or not str(name).strip():
        return None                        # return None so UNKNOWN winners are excluded from repeat-winner counts
    n = str(name).upper().strip()
    n = re.sub(r"\s+", " ", n)
    for suffix in ["PRIVATE LIMITED", "PVT LTD", "PVT. LTD.", "LIMITED",
                   "LTD.", "LTD", "CORPORATION", "CORP.", "(OPC) PVT",
                   "UNDER PMA", "UNDER MSE", "UNDER STARTUP",
                   "(MSE)", "(MII)", "(MSE,MII)", "(MII,MSE)"]:
        n = n.replace(suffix, "").strip()
    n = n.strip(" .,()-")
    return n if n else None


# ── date normalisation ────────────────────────────────────────────────────────
def norm_date(val):
    if pd.isna(val) or not str(val).strip():
        return None
    try:
        return pd.to_datetime(val, utc=True).strftime("%Y-%m-%d")
    except Exception:
        return str(val)[:10]


# ── duplicate deduplication ───────────────────────────────────────────────────
def dedup_bids(df):
    before = len(df)
    # primary dedup: exact duplicate rows
    df = df.drop_duplicates()
    # business dedup: same bid_number appearing more than once
    # keep the row with more data (non-null winner_price preferred)
    df = df.sort_values("winner_price", ascending=False)
    df = df.drop_duplicates(subset=["bid_number"], keep="first")
    # secondary: same numeric id
    df = df.drop_duplicates(subset=["id"], keep="first")
    after = len(df)
    print(f"  Bid deduplication: {before} → {after} rows ({before - after} removed)")
    return df.reset_index(drop=True)


def dedup_vendors(df):
    before = len(df)
    # remove exact duplicate rows
    df = df.drop_duplicates()
    # remove same vendor appearing twice at same rank for same bid
    df = df.drop_duplicates(subset=["bid_id", "vendor_name", "vendor_rank"], keep="first")
    after = len(df)
    print(f"  Vendor deduplication: {before} → {after} rows ({before - after} removed)")
    return df.reset_index(drop=True)


# ── anomaly flags ─────────────────────────────────────────────────────────────
def flag_anomalies(df):
    def _flag(row):
        f = []
        wp = row["winner_price"]
        l2 = row["l2_price"]
        nb = row["num_bidders"]
        if pd.isna(wp) or wp == 0:
            f.append("no_winner_price")
        if pd.notna(wp) and pd.notna(l2) and wp > 0 and l2 > 0 and wp > l2:
            f.append("winner_not_lowest")
        if pd.notna(nb) and int(nb) == 1:
            f.append("single_bidder")
        if row.get("is_high_value") in (True, "True"):
            f.append("high_value")
        return "|".join(f) if f else "ok"
    return df.apply(_flag, axis=1)


# ── clean bids ────────────────────────────────────────────────────────────────
def clean_bids():
    path = OUTPUT / "awarded_with_vendors.csv"
    if not path.exists():
        print(f"[!] {path} not found")
        return None

    df = pd.read_csv(path)
    print(f"Raw bids loaded: {len(df):,}")

    # deduplicate first
    df = dedup_bids(df)

    # prices
    df["winner_price"] = df["winner_price"].apply(clean_price).fillna(0)
    df["l2_price"]     = df["l2_price"].apply(clean_price).fillna(0)

    # normalized winner name — None for blank/unknown
    df["winner_name_clean"] = df["winner_name"].apply(normalize_name)

    # dates
    df["award_date"] = df["end_date"].apply(norm_date)
    df["start_date"] = df["start_date"].apply(norm_date)

    # fill missing categoricals
    df["ministry"]    = df["ministry"].fillna("Unknown Ministry")
    df["department"]  = df["department"].fillna("Unknown Dept")
    df["num_bidders"] = df["num_bidders"].fillna(0).astype(int)

    # L1-L2 gap %
    df["price_gap_pct"] = df.apply(
        lambda r: round((r["l2_price"] - r["winner_price"]) / r["l2_price"] * 100, 2)
        if r["l2_price"] > 0 and r["winner_price"] > 0 else None, axis=1
    )

    # anomaly flags
    df["anomaly_flag"] = flag_anomalies(df)

    # repeat winners — exclude None/unknown so blank winners don't dominate counts
    known_winners = df[df["winner_name_clean"].notna()]
    win_counts = known_winners["winner_name_clean"].value_counts()
    df["winner_repeat_count"] = df["winner_name_clean"].map(win_counts).fillna(0).astype(int)
    df["is_repeat_winner"]    = df["winner_repeat_count"] > 1

    # schema validation
    val_report = validate_schema(df, BIDS_SCHEMA, "bids_clean")

    df.to_csv(OUTPUT / "bids_clean.csv", index=False)
    print(f"\n  bids_clean.csv → {len(df):,} rows, {df.shape[1]} columns")
    print(f"  Bids with winner price   : {(df['winner_price'] > 0).sum():,}")
    print(f"  Anomalous bids           : {(df['anomaly_flag'] != 'ok').sum():,}")
    print(f"  Repeat winners (known)   : {df['is_repeat_winner'].sum():,}")
    return df, val_report


# ── clean vendors ─────────────────────────────────────────────────────────────
def clean_vendors():
    path = OUTPUT / "all_vendors.csv"
    if not path.exists():
        print(f"[!] {path} not found")
        return None

    df = pd.read_csv(path)
    print(f"\nRaw vendor rows: {len(df):,}")

    # deduplicate
    df = dedup_vendors(df)

    df["vendor_name_clean"] = df["vendor_name"].apply(normalize_name)
    df["vendor_price"]      = df["vendor_price"].apply(clean_price).fillna(0)
    df["is_disqualified"]   = df["status_flag"].str.contains(
        r"disq|reject|inelig", case=False, na=False
    )

    # schema validation
    val_report = validate_schema(df, VENDORS_SCHEMA, "vendors_clean")

    df.to_csv(OUTPUT / "vendors_clean.csv", index=False)
    print(f"\n  vendors_clean.csv → {len(df):,} rows")
    print(f"  Unique vendors    : {df['vendor_name_clean'].dropna().nunique():,}")
    print(f"  Disqualified      : {df['is_disqualified'].sum()}")
    return df, val_report


if __name__ == "__main__":
    print("=" * 60)
    print("GemEdge — Data Cleaner + Schema Validator")
    print("=" * 60)

    bids_result    = clean_bids()
    vendors_result = clean_vendors()

    # save combined validation report
    report = {}
    if bids_result:
        report["bids"]    = bids_result[1]
    if vendors_result:
        report["vendors"] = vendors_result[1]
    with open(OUTPUT / "validation_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  validation_report.json saved")
    print("\n✅ Done. Run: python3 insights.py")
