"""
Dubai Real Estate Intelligence Dashboard
══════════════════════════════════════════
Communities: Emaar South | Dubai Creek Harbour
Data:        real DLD extract (pipeline/fetch_dld.py); synthetic demo data only if it is missing
             Drop real DLD CSV into data/ folder → auto-loaded

To use real data:
  1. Download from: https://dubailand.gov.ae/en/open-data/real-estate-data/
     OR: https://www.kaggle.com/datasets/alexefimik/dubai-real-estate-transactions-dataset
  2. Save as: data/dld_transactions.csv
  3. Restart the app — real data loads automatically

Dashboard: http://localhost:8085
"""

import os, json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

# ─────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────
DATA_DIR   = os.path.join(os.path.dirname(__file__), "data")
REAL_CSV   = os.path.join(DATA_DIR, "dld_transactions.csv")
DEMO_CSV   = os.path.join(DATA_DIR, "dld_demo.csv")
COMMUNITIES = ["EMAAR SOUTH", "DUBAI CREEK HARBOUR"]

AREA_ALIASES = {
    # DLD uses both names for Emaar South
    "MADINAT AL MATAAR":  "EMAAR SOUTH",
    "DUBAI SOUTH":        "EMAAR SOUTH",   # broader master community
}

def normalise_df(df):
    """Normalise any DLD CSV format (old Dubai Pulse OR new DLD export) to internal schema."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    # New DLD export format (uploaded file) column mapping
    new_fmt = {
        "instance_date":    "date",
        "group_en":         "trans_group",
        "is_offplan_en":    "reg_type",
        "area_en":          "area",
        "prop_type_en":     "property_type",
        "prop_sb_type_en":  "sub_type",
        "trans_value":      "price_aed",
        "procedure_area":   "sqm",
        "rooms_en":         "rooms",
        "project_en":       "building",
        "master_project_en":"master_project",
        "usage_en":         "usage",
    }
    # Old Dubai Pulse format column mapping
    old_fmt = {
        "trans_group_en":       "trans_group",
        "area_name_en":         "area",
        "property_type_en":     "property_type",
        "property_sub_type_en": "sub_type",
        "reg_type_en":          "reg_type",
        "building_name_en":     "building",
        "actual_worth":         "price_aed",
        "meter_sale_price":     "ppsm",
        "procedure_area":       "sqm",
    }
    for src, dst in {**new_fmt, **old_fmt}.items():
        if src in df.columns and dst not in df.columns:
            df.rename(columns={src: dst}, inplace=True)

    df["date"]      = pd.to_datetime(df.get("date", df.get("instance_date")), errors="coerce")
    df              = df.dropna(subset=["date"])
    df["year"]      = df["date"].dt.year
    df["month"]     = df["date"].dt.month
    df["ym"]        = df["date"].dt.to_period("M").astype(str)

    df["price_aed"] = pd.to_numeric(df.get("price_aed"), errors="coerce")
    df["sqm"]       = pd.to_numeric(df.get("sqm"), errors="coerce")
    df["sqft"]      = (df["sqm"] * 10.764).round(0)
    df["ppsf"]      = (df["price_aed"] / df["sqft"]).replace([np.inf, -np.inf], np.nan).round(0)

    # Normalise area names + apply aliases
    df["area"] = df["area"].astype(str).str.upper().str.strip()
    df["area"] = df["area"].replace(AREA_ALIASES)

    # Normalise reg_type: "Off-Plan" / "Ready"
    if "reg_type" in df.columns:
        df["reg_type"] = df["reg_type"].astype(str).str.strip()
        df["reg_type"] = df["reg_type"].apply(
            lambda v: "Off-Plan" if "off" in v.lower() else "Ready"
        )

    return df

def load_data():
    has_real = os.path.exists(REAL_CSV)
    frames   = []
    is_demo  = not has_real

    # Synthetic demo data is used ONLY when no real extract exists — never blended
    # into real charts, because mixing generated rows with real ones hides which is which.
    if not has_real and os.path.exists(DEMO_CSV):
        demo = normalise_df(pd.read_csv(DEMO_CSV, low_memory=False))
        demo["source"] = "demo"
        frames.append(demo)
        print(f"  Demo data: {len(demo):,} rows (2020–2025 historical context)")

    # Load real DLD file and overlay — its dates take precedence
    if has_real:
        real = normalise_df(pd.read_csv(REAL_CSV, low_memory=False))
        real["source"] = "real"
        frames.append(real)
        print(f"  Real DLD data: {len(real):,} rows ({real['date'].min().date()} → {real['date'].max().date()})")

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # Drop demo rows that overlap with real data months to avoid double-counting
    if has_real and len(frames) == 2:
        real_months = set(frames[1]["ym"].unique())
        df = df[~((df["source"] == "demo") & (df["ym"].isin(real_months)))]

    # Filter to our target communities + sales only
    df = df[df["area"].isin(COMMUNITIES)]
    if "trans_group" in df.columns:
        # rows without a trans_group (the real extract is sales-only by construction) are kept
        df = df[df["trans_group"].isna() |
                df["trans_group"].astype(str).str.upper().str.contains("SALE|SALES", na=False)]
    df = df[df["price_aed"] > 10_000]
    df = df[df["ppsf"].between(100, 20_000)]

    print(f"  Final dataset: {len(df):,} transactions | {df['area'].nunique()} communities")
    print(f"  Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"  Sources: {df['source'].value_counts().to_dict()}")
    return df, is_demo

DF, IS_DEMO = load_data()

# ─────────────────────────────────────────
# ANALYTICS ENGINE
# ─────────────────────────────────────────
def compute_stats(df, community=None, prop_type=None, reg_type=None, year_from=None, year_to=None):
    d = df.copy()
    if community and community != "ALL":
        d = d[d["area"] == community]
    if prop_type and prop_type != "ALL":
        d = d[d["property_type"] == prop_type]
    if reg_type and reg_type != "ALL":
        d = d[d["reg_type"].str.upper() == reg_type.upper()]
    if year_from:
        d = d[d["year"] >= int(year_from)]
    if year_to:
        d = d[d["year"] <= int(year_to)]
    return d

def safe_mean(s):
    v = s.dropna()
    return round(float(v.mean()), 0) if len(v) else 0

def pct_change(new, old):
    if not old: return 0
    return round((new - old) / old * 100, 1)

def signal(df_community):
    """
    Momentum label (descriptive, not a recommendation) based on:
    - 3-month price momentum vs 12-month avg
    - Transaction volume trend
    - Off-plan ratio (high = developer confidence)
    """
    if len(df_community) < 50:
        return "HOLD", "Insufficient data", "#ffd600"

    recent = df_community[df_community["date"] >= df_community["date"].max() - pd.DateOffset(months=3)]
    hist   = df_community[df_community["date"] < df_community["date"].max() - pd.DateOffset(months=3)]

    if len(recent) < 5 or len(hist) < 10:
        return "HOLD", "Insufficient recent data", "#ffd600"

    recent_ppsf  = safe_mean(recent["ppsf"])
    hist_ppsf    = safe_mean(hist["ppsf"])
    price_mom    = pct_change(recent_ppsf, hist_ppsf)

    recent_vol   = len(recent) / 3   # avg monthly
    hist_monthly = df_community.groupby("ym").size()
    avg_vol      = float(hist_monthly.mean()) if len(hist_monthly) else 1

    offplan_ratio = (df_community["reg_type"].str.upper().str.contains("OFF", na=False).sum() /
                     max(len(df_community), 1) * 100)

    yoy = 0
    if len(df_community["year"].unique()) >= 2:
        latest_yr  = df_community["year"].max()
        prev_yr    = latest_yr - 1
        yoy = pct_change(
            safe_mean(df_community[df_community["year"] == latest_yr]["ppsf"]),
            safe_mean(df_community[df_community["year"] == prev_yr]["ppsf"])
        )

    score = 0
    reasons = []
    if price_mom > 3:    score += 2; reasons.append(f"Price momentum +{price_mom:.1f}% (3M)")
    elif price_mom > 0:  score += 1; reasons.append(f"Mild price growth +{price_mom:.1f}% (3M)")
    elif price_mom < -3: score -= 2; reasons.append(f"Price declining {price_mom:.1f}% (3M)")
    else:                reasons.append(f"Prices flat ({price_mom:.1f}% 3M)")

    if recent_vol > avg_vol * 1.2:  score += 1; reasons.append("Volume above average")
    elif recent_vol < avg_vol * 0.7: score -= 1; reasons.append("Volume below average")

    if yoy > 10:  score += 1; reasons.append(f"Strong YoY +{yoy:.1f}%")
    elif yoy < 0: score -= 1; reasons.append(f"Negative YoY {yoy:.1f}%")

    if offplan_ratio > 60: reasons.append(f"High developer activity ({offplan_ratio:.0f}% off-plan)")

    # Descriptive, not advice: the data can show momentum, not whether to buy.
    if score >= 3:   sig, color = "STRONG MOMENTUM", "#00e676"
    elif score >= 1: sig, color = "RISING",          "#00c853"
    elif score == 0: sig, color = "FLAT",            "#ffd600"
    elif score == -1:sig, color = "SOFTENING",       "#ff9100"
    else:            sig, color = "FALLING",         "#ff1744"

    return sig, " · ".join(reasons), color

# ─────────────────────────────────────────
# ROUTE: API DATA ENDPOINTS
# ─────────────────────────────────────────
@app.route("/api/summary")
def api_summary():
    community = request.args.get("community", "ALL")
    prop_type = request.args.get("prop_type", "ALL")

    d = compute_stats(DF, community=community, prop_type=prop_type)
    if d.empty:
        return jsonify({})

    latest_yr = int(d["year"].max())
    prev_yr   = latest_yr - 1

    d_latest = d[d["year"] == latest_yr]
    d_prev   = d[d["year"] == prev_yr]

    avg_ppsf     = safe_mean(d_latest["ppsf"])
    avg_ppsf_prev= safe_mean(d_prev["ppsf"])
    avg_price    = safe_mean(d_latest["price_aed"])
    avg_price_prev=safe_mean(d_prev["price_aed"])
    total_txn    = len(d_latest)
    total_val    = round(d_latest["price_aed"].sum() / 1e9, 2)
    offplan_pct  = round(
        d_latest["reg_type"].str.upper().str.contains("OFF", na=False).sum() / max(len(d_latest), 1) * 100, 1
    )

    communities_out = []
    for comm in ([community] if community != "ALL" else COMMUNITIES):
        dc = d[d["area"] == comm]
        sig, reason, color = signal(dc)
        communities_out.append({
            "name": comm.title().replace("Dubai Creek Harbour", "Creek Harbour"),
            "signal": sig, "reason": reason, "color": color,
            "avg_ppsf": safe_mean(dc[dc["year"] == latest_yr]["ppsf"]),
            "txn_count": len(dc[dc["year"] == latest_yr]),
            "yoy_ppsf": pct_change(
                safe_mean(dc[dc["year"] == latest_yr]["ppsf"]),
                safe_mean(dc[dc["year"] == prev_yr]["ppsf"])
            ),
        })

    return jsonify({
        "avg_ppsf":      avg_ppsf,
        "avg_ppsf_chg":  pct_change(avg_ppsf, avg_ppsf_prev),
        "avg_price":     avg_price,
        "avg_price_chg": pct_change(avg_price, avg_price_prev),
        "total_txn":     total_txn,
        "total_val_b":   total_val,
        "offplan_pct":   offplan_pct,
        "latest_year":   latest_yr,
        "communities":   communities_out,
        "is_demo":       IS_DEMO,
        "has_real":      not IS_DEMO,
    })

@app.route("/api/price_trend")
def api_price_trend():
    community = request.args.get("community", "ALL")
    prop_type = request.args.get("prop_type", "ALL")
    d = compute_stats(DF, community=community, prop_type=prop_type)
    if d.empty: return jsonify({"labels": [], "datasets": []})

    monthly = d.groupby(["ym","reg_type"])["ppsf"].mean().reset_index()
    monthly["ppsf"] = monthly["ppsf"].round(0)
    monthly = monthly.sort_values("ym")

    labels = sorted(monthly["ym"].unique().tolist())

    datasets = []
    colors = {"off-plan": "#1e88e5", "ready": "#00c853", "offplan": "#1e88e5"}
    for rt in monthly["reg_type"].unique():
        sub = monthly[monthly["reg_type"] == rt].set_index("ym")
        vals = [float(sub.loc[m, "ppsf"]) if m in sub.index else None for m in labels]
        key  = rt.lower().replace(" ", "").replace("-","")
        col  = colors.get(key, "#9c27b0")
        label = "Off-Plan" if "off" in rt.lower() else "Secondary Market"
        datasets.append({"label": label, "data": vals, "color": col})

    return jsonify({"labels": labels, "datasets": datasets})

@app.route("/api/volume_trend")
def api_volume_trend():
    community = request.args.get("community", "ALL")
    d = compute_stats(DF, community=community)
    if d.empty: return jsonify({})

    monthly = d.groupby(["ym","area"]).size().reset_index(name="count")
    monthly = monthly.sort_values("ym")
    labels  = sorted(monthly["ym"].unique().tolist())

    area_colors = {
        "EMAAR SOUTH":          "#ffd600",
        "DUBAI CREEK HARBOUR":  "#40c4ff",
    }
    datasets = []
    for area in monthly["area"].unique():
        sub = monthly[monthly["area"] == area].set_index("ym")
        vals = [int(sub.loc[m, "count"]) if m in sub.index else 0 for m in labels]
        col  = area_colors.get(area, "#9c27b0")
        name = area.title().replace("Dubai Creek Harbour","Creek Harbour")
        datasets.append({"label": name, "data": vals, "color": col})

    return jsonify({"labels": labels, "datasets": datasets})

@app.route("/api/bedroom_breakdown")
def api_bedroom_breakdown():
    community = request.args.get("community", "ALL")
    prop_type = request.args.get("prop_type", "ALL")
    d = compute_stats(DF, community=community, prop_type=prop_type)
    if d.empty: return jsonify({})

    latest_yr = int(d["year"].max())
    d = d[d["year"] == latest_yr]
    if "rooms" not in d.columns: return jsonify({})

    order = ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R"]
    present = [r for r in order if r in d["rooms"].values]
    result = []
    for room in present:
        sub = d[d["rooms"] == room]
        result.append({
            "room": room,
            "avg_ppsf":  safe_mean(sub["ppsf"]),
            "avg_price": safe_mean(sub["price_aed"]),
            "avg_sqft":  safe_mean(sub["sqft"]),
            "count":     len(sub),
        })
    return jsonify(result)

@app.route("/api/offplan_split")
def api_offplan_split():
    community = request.args.get("community", "ALL")
    d = compute_stats(DF, community=community)
    if d.empty: return jsonify({})
    latest = int(d["year"].max())
    d = d[d["year"] == latest]
    counts = d["reg_type"].value_counts().to_dict()
    return jsonify(counts)

@app.route("/api/yoy_ppsf")
def api_yoy_ppsf():
    community = request.args.get("community", "ALL")
    d = compute_stats(DF, community=community)
    if d.empty: return jsonify({})
    yearly = d.groupby("year")["ppsf"].mean().round(0).reset_index()
    yearly["yoy_chg"] = yearly["ppsf"].pct_change().mul(100).round(1)
    return jsonify(yearly.to_dict(orient="records"))

@app.route("/api/recent_transactions")
def api_recent():
    community = request.args.get("community", "ALL")
    prop_type = request.args.get("prop_type", "ALL")
    d = compute_stats(DF, community=community, prop_type=prop_type)
    if d.empty: return jsonify([])
    recent = d.sort_values("date", ascending=False).head(100)
    cols = ["date","area","property_type","rooms","reg_type","building","price_aed","ppsf","sqft"]
    out = []
    for _, row in recent.iterrows():
        r = {}
        for c in cols:
            v = row.get(c, "")
            if pd.isna(v): v = "—"
            elif c == "date": v = str(v)[:10]
            elif c in ("price_aed","ppsf","sqft"): v = int(v) if v != "—" else "—"
            r[c] = v
        out.append(r)
    return jsonify(out)

@app.route("/api/price_heatmap")
def api_heatmap():
    """Avg PPSF by year × community × property type"""
    d = DF.copy()
    grp = d.groupby(["year","area","property_type"])["ppsf"].mean().round(0).reset_index()
    grp.rename(columns={"ppsf":"avg_ppsf"}, inplace=True)
    return jsonify(grp.to_dict(orient="records"))

@app.route("/api/filters")
def api_filters():
    years      = sorted(DF["year"].dropna().unique().astype(int).tolist())
    prop_types = sorted(DF["property_type"].dropna().unique().tolist()) if "property_type" in DF.columns else []
    return jsonify({"years": years, "prop_types": prop_types, "communities": COMMUNITIES})

# ─────────────────────────────────────────
# RENTAL YIELD & ROI ENGINE
# ─────────────────────────────────────────
# Estimated annual rents (AED) at 2025 market rates — based on RERA / Bayut data
# Emaar South & Creek Harbour typical asking / achieved rents
ANNUAL_RENTS = {
    "EMAAR SOUTH": {
        "Apartment": {"Studio": 55_000, "1 B/R": 72_000, "2 B/R": 98_000,  "3 B/R": 135_000},
        "Townhouse": {"3 B/R": 145_000, "4 B/R": 170_000},
        "Villa":     {"4 B/R": 180_000, "5 B/R": 230_000},
    },
    "DUBAI CREEK HARBOUR": {
        "Apartment": {"Studio": 82_000, "1 B/R": 108_000, "2 B/R": 160_000, "3 B/R": 225_000, "4 B/R": 310_000},
        "Townhouse": {"3 B/R": 205_000, "4 B/R": 265_000},
    },
}
# Rent growth index by year (2025 = 1.0 base)
RENT_INDEX = {2020: 0.72, 2021: 0.78, 2022: 0.84, 2023: 0.91, 2024: 0.96, 2025: 1.00}

def get_annual_rent(community, prop_type, room, year):
    base = ANNUAL_RENTS.get(community, {}).get(prop_type, {}).get(room)
    if not base:
        # Fallback: try apartment, then first available
        for pt in ANNUAL_RENTS.get(community, {}).values():
            if room in pt:
                base = pt[room]; break
    if not base: return None
    return round(base * RENT_INDEX.get(int(year), 1.0))

@app.route("/api/rental_yield")
def api_rental_yield():
    """
    Gross rental yield by bedroom type for each community.
    Yield % = Annual Rent / Avg Purchase Price × 100
    Returns current year + historical yield trend.
    """
    community = request.args.get("community", "ALL")
    prop_type = request.args.get("prop_type", "ALL")
    d = compute_stats(DF, community=community, prop_type=prop_type)
    if d.empty: return jsonify([])

    latest_yr = int(d["year"].max())
    room_order = ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R"]
    results = []

    for comm in ([community] if community != "ALL" else COMMUNITIES):
        dc = d[d["area"] == comm]
        if dc.empty: continue
        pt_list = [prop_type] if prop_type != "ALL" else dc["property_type"].dropna().unique().tolist()

        for pt in pt_list:
            dcp = dc[dc["property_type"] == pt] if pt != "ALL" else dc
            if dcp.empty: continue
            for room in room_order:
                sub = dcp[(dcp["year"] == latest_yr) & (dcp.get("rooms", pd.Series()) == room)] \
                    if "rooms" in dcp.columns else pd.DataFrame()
                # fallback to all years if no latest year data
                if sub.empty:
                    sub = dcp[dcp.get("rooms", pd.Series()) == room] if "rooms" in dcp.columns else pd.DataFrame()
                if sub.empty: continue

                avg_price = safe_mean(sub["price_aed"])
                if avg_price < 10_000: continue
                annual_rent = get_annual_rent(comm, pt, room, latest_yr)
                if not annual_rent: continue

                gross_yield = round(annual_rent / avg_price * 100, 2)
                net_yield   = round(gross_yield * 0.78, 2)  # ~22% for service charge, mgmt, vacancy

                results.append({
                    "community":    comm.replace("DUBAI CREEK HARBOUR", "Creek Harbour").replace("EMAAR SOUTH", "Emaar South"),
                    "prop_type":    pt,
                    "room":         room,
                    "avg_price":    int(avg_price),
                    "annual_rent":  annual_rent,
                    "gross_yield":  gross_yield,
                    "net_yield":    net_yield,
                    "monthly_rent": round(annual_rent / 12),
                })

    results.sort(key=lambda x: x["gross_yield"], reverse=True)
    return jsonify(results)

@app.route("/api/roi")
def api_roi():
    """
    Total ROI by community + bedroom = Gross Yield + Capital Appreciation (YoY).
    Also returns historical ROI trend by year.
    """
    community = request.args.get("community", "ALL")
    d = compute_stats(DF, community=community)
    if d.empty: return jsonify({})

    # Per-community ROI summary
    roi_summary = []
    for comm in ([community] if community != "ALL" else COMMUNITIES):
        dc = d[d["area"] == comm]
        if dc.empty: continue
        yearly = dc.groupby("year")["ppsf"].mean().round(0)
        years  = sorted(yearly.index.tolist())

        # Annual yield + cap gain per year
        yearly_roi = []
        for yr in years:
            avg_price = safe_mean(dc[dc["year"] == yr]["price_aed"])
            # Aggregate yield across all bedroom types (weighted by count)
            total_rent = total_count = 0
            if "rooms" in dc.columns and "property_type" in dc.columns:
                for _, row in dc[dc["year"] == yr].iterrows():
                    r = get_annual_rent(comm, row.get("property_type","Apartment"),
                                        row.get("rooms","1 B/R"), yr)
                    if r and row["price_aed"] > 10_000:
                        total_rent  += r
                        total_count += 1
            avg_rent_yield = round(total_rent / total_count / avg_price * 100, 2) if total_count and avg_price else 0

            cap_gain = 0
            if yr > min(years):
                prev_ppsf = float(yearly.get(yr-1, yearly.iloc[0]))
                curr_ppsf = float(yearly.get(yr, yearly.iloc[-1]))
                cap_gain  = round(pct_change(curr_ppsf, prev_ppsf), 1)

            total_roi = round(avg_rent_yield + cap_gain, 1)
            yearly_roi.append({
                "year": yr,
                "yield": avg_rent_yield,
                "cap_gain": cap_gain,
                "total_roi": total_roi,
            })

        latest = yearly_roi[-1] if yearly_roi else {}
        name = comm.replace("DUBAI CREEK HARBOUR","Creek Harbour").replace("EMAAR SOUTH","Emaar South")
        roi_summary.append({
            "community":   name,
            "yield":       latest.get("yield", 0),
            "cap_gain":    latest.get("cap_gain", 0),
            "total_roi":   latest.get("total_roi", 0),
            "yearly":      yearly_roi,
        })

    return jsonify(roi_summary)

# ─────────────────────────────────────────
# MAIN DASHBOARD
# ─────────────────────────────────────────
HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dubai RE Intelligence — Emaar South & Creek Harbour</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#080c12;color:#e0e0e0;min-height:100vh}

  /* HEADER */
  .header{background:linear-gradient(135deg,#0d1117 0%,#0a1628 100%);border-bottom:1px solid #1e2a3a;padding:20px 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
  .logo{display:flex;align-items:center;gap:14px}
  .logo-icon{width:40px;height:40px;background:linear-gradient(135deg,#1e88e5,#00acc1);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px}
  .logo-text h1{font-size:20px;font-weight:700;color:#fff}
  .logo-text p{font-size:12px;color:#546e7a;margin-top:2px}
  .demo-badge{background:#2a1f00;color:#ffd600;border:1px solid #ffd60055;padding:5px 14px;border-radius:20px;font-size:11px;font-weight:600;display:none}
  .demo-badge.show{display:inline-block}
  .last-updated{font-size:11px;color:#37474f}

  /* FILTERS */
  .filters{background:#0d1117;border-bottom:1px solid #1a2332;padding:14px 32px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
  .filter-label{font-size:11px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-right:4px}
  select,button.filter-btn{background:#111927;border:1px solid #1e2a3a;color:#e0e0e0;padding:7px 14px;border-radius:8px;font-size:12px;cursor:pointer;outline:none}
  select:focus{border-color:#1e88e5}
  .pill-group{display:flex;gap:6px}
  .pill{background:#111927;border:1px solid #1e2a3a;color:#546e7a;padding:6px 16px;border-radius:20px;font-size:12px;cursor:pointer;transition:all .2s}
  .pill.active{background:#1e2a4a;border-color:#1e88e5;color:#40c4ff;font-weight:600}

  /* MAIN */
  .main{padding:28px 32px;max-width:1600px;margin:0 auto}

  /* SIGNAL CARDS */
  .signal-row{display:flex;gap:16px;margin-bottom:28px;flex-wrap:wrap}
  .signal-card{flex:1;min-width:260px;background:#0d1117;border:1px solid #1a2332;border-radius:14px;padding:20px 24px;position:relative;overflow:hidden}
  .signal-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--sig-color,#1e88e5)}
  .signal-card .community{font-size:11px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
  .signal-card .signal-val{font-size:22px;font-weight:800;color:var(--sig-color,#fff);margin-bottom:6px}
  .signal-card .signal-reason{font-size:11px;color:#546e7a;line-height:1.6}
  .signal-card .ppsf-row{display:flex;gap:24px;margin-top:14px;padding-top:14px;border-top:1px solid #1a2332}
  .signal-card .metric{text-align:center}
  .signal-card .metric .val{font-size:16px;font-weight:700;color:#fff}
  .signal-card .metric .lbl{font-size:10px;color:#37474f;margin-top:2px}
  .chg-pos{color:#00c853!important}
  .chg-neg{color:#ff1744!important}

  /* STAT BOXES */
  .stat-row{display:flex;gap:14px;margin-bottom:28px;flex-wrap:wrap}
  .stat{background:#0d1117;border:1px solid #1a2332;border-radius:12px;padding:16px 22px;flex:1;min-width:160px}
  .stat .lbl{font-size:10px;color:#37474f;text-transform:uppercase;letter-spacing:1px}
  .stat .val{font-size:22px;font-weight:700;color:#fff;margin-top:5px}
  .stat .chg{font-size:11px;margin-top:3px}

  /* CHARTS GRID */
  .charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:28px}
  .chart-card{background:#0d1117;border:1px solid #1a2332;border-radius:14px;padding:22px}
  .chart-card.full{grid-column:1/-1}
  .chart-card h3{font-size:13px;color:#90a4ae;text-transform:uppercase;letter-spacing:1px;margin-bottom:18px;display:flex;align-items:center;gap:8px}
  .chart-card h3 .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
  .chart-wrap{position:relative;height:260px}
  .chart-wrap.tall{height:300px}

  /* YOY TABLE */
  .yoy-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
  .yoy-table th{color:#37474f;font-size:10px;text-transform:uppercase;letter-spacing:1px;padding:8px 12px;text-align:left;border-bottom:1px solid #1a2332}
  .yoy-table td{padding:10px 12px;border-bottom:1px solid #111927}
  .yoy-table tr:hover td{background:#0a1020}
  .bar-inline{display:inline-block;height:8px;border-radius:4px;margin-left:8px;vertical-align:middle}

  /* BEDROOM TABLE */
  .room-table{width:100%;border-collapse:collapse;font-size:13px}
  .room-table th{color:#37474f;font-size:10px;text-transform:uppercase;letter-spacing:1px;padding:8px 12px;text-align:left}
  .room-table td{padding:10px 12px;border-bottom:1px solid #111927}

  /* TRANSACTIONS TABLE */
  .txn-section{margin-bottom:32px}
  .txn-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
  .txn-header h2{font-size:14px;color:#546e7a;text-transform:uppercase;letter-spacing:1px}
  .txn-table-wrap{background:#0d1117;border:1px solid #1a2332;border-radius:14px;overflow:hidden}
  .txn-table{width:100%;border-collapse:collapse;font-size:12px}
  .txn-table th{background:#0a1020;padding:11px 14px;text-align:left;font-size:10px;color:#37474f;text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
  .txn-table td{padding:10px 14px;border-top:1px solid #111927;white-space:nowrap}
  .txn-table tr:hover td{background:#0a1520}
  .badge-offplan{background:#001a2a;color:#40c4ff;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}
  .badge-ready{background:#0a2000;color:#69f0ae;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}
  .community-es{color:#ffd600;font-weight:600}
  .community-ch{color:#40c4ff;font-weight:600}

  /* DONUT LEGEND */
  .donut-legend{display:flex;gap:16px;justify-content:center;margin-top:12px;flex-wrap:wrap}
  .dl-item{display:flex;align-items:center;gap:6px;font-size:12px}
  .dl-dot{width:10px;height:10px;border-radius:50%}

  /* ROI SECTION */
  .roi-section{margin-bottom:32px}
  .roi-section h2{font-size:14px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:16px}
  .roi-cards{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
  .roi-card{flex:1;min-width:240px;background:#0d1117;border:1px solid #1a2332;border-radius:14px;padding:20px 24px}
  .roi-card .rc-community{font-size:11px;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
  .roi-card .rc-total{font-size:28px;font-weight:800;color:#00e676;margin-bottom:4px}
  .roi-card .rc-total span{font-size:14px;color:#546e7a;font-weight:400}
  .roi-card .rc-breakdown{display:flex;gap:20px;margin-top:14px;padding-top:14px;border-top:1px solid #1a2332}
  .roi-card .rcb{text-align:center}
  .roi-card .rcb .val{font-size:16px;font-weight:700}
  .roi-card .rcb .lbl{font-size:10px;color:#37474f;margin-top:2px}
  .yield-table{width:100%;border-collapse:collapse;font-size:12px}
  .yield-table th{color:#37474f;font-size:10px;text-transform:uppercase;letter-spacing:1px;padding:8px 12px;text-align:left;border-bottom:1px solid #1a2332}
  .yield-table td{padding:9px 12px;border-bottom:1px solid #111927}
  .yield-table tr:hover td{background:#0a1020}
  .yield-bar{display:inline-block;height:6px;border-radius:3px;vertical-align:middle;margin-left:6px}
  .best-badge{background:#00200e;color:#00e676;border:1px solid #00e67655;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600}

  .empty{text-align:center;padding:40px;color:#37474f}
  .footer{text-align:center;padding:20px;color:#1e2a3a;font-size:11px;border-top:1px solid #0d1117}
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-icon">🏙️</div>
    <div class="logo-text">
      <h1>Dubai Real Estate Intelligence</h1>
      <p>Emaar South · Creek Harbour · DLD Transactions</p>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <span class="demo-badge" id="demoBadge">⚠ SYNTHETIC DEMO DATA — not real transactions. Run pipeline/fetch_dld.py</span>
    <span class="last-updated" id="lastUpdated">Loading...</span>
  </div>
</div>

<div class="filters">
  <span class="filter-label">Community</span>
  <div class="pill-group" id="communityPills">
    <button class="pill active" data-val="ALL">All Communities</button>
    <button class="pill" data-val="EMAAR SOUTH">Emaar South</button>
    <button class="pill" data-val="DUBAI CREEK HARBOUR">Creek Harbour</button>
  </div>
  <span class="filter-label" style="margin-left:12px">Type</span>
  <select id="propTypeFilter">
    <option value="ALL">All Types</option>
  </select>
  <span class="filter-label" style="margin-left:12px">Year From</span>
  <select id="yearFromFilter"><option value="">All</option></select>
  <span class="filter-label">To</span>
  <select id="yearToFilter"><option value="">All</option></select>
</div>

<div class="main">

  <!-- SIGNAL CARDS -->
  <div class="signal-row" id="signalRow"></div>

  <!-- TOP STATS -->
  <div class="stat-row" id="statRow">
    <div class="stat"><div class="lbl">Avg Price / sqft</div><div class="val" id="statPpsf">—</div><div class="chg" id="statPpsfChg"></div></div>
    <div class="stat"><div class="lbl">Avg Transaction Price</div><div class="val" id="statPrice">—</div><div class="chg" id="statPriceChg"></div></div>
    <div class="stat"><div class="lbl">Transactions (YTD)</div><div class="val" id="statTxn">—</div></div>
    <div class="stat"><div class="lbl">Total Value (AED)</div><div class="val" id="statVal">—</div></div>
    <div class="stat"><div class="lbl">Off-Plan Share</div><div class="val" id="statOffplan">—</div></div>
  </div>

  <!-- CHARTS ROW 1 -->
  <div class="charts-grid">
    <div class="chart-card full">
      <h3><span class="dot" style="background:#1e88e5"></span>Price per sqft Trend — Monthly</h3>
      <div class="chart-wrap tall"><canvas id="chartPrice"></canvas></div>
    </div>

    <div class="chart-card">
      <h3><span class="dot" style="background:#ffd600"></span>Transaction Volume — Monthly</h3>
      <div class="chart-wrap"><canvas id="chartVolume"></canvas></div>
    </div>

    <div class="chart-card">
      <h3><span class="dot" style="background:#ce93d8"></span>Off-Plan vs Secondary Split</h3>
      <div class="chart-wrap" style="height:180px"><canvas id="chartDonut"></canvas></div>
      <div class="donut-legend" id="donutLegend"></div>
    </div>

    <div class="chart-card">
      <h3><span class="dot" style="background:#00c853"></span>Avg Price/sqft by Bedroom Type</h3>
      <div class="chart-wrap"><canvas id="chartBedroom"></canvas></div>
    </div>

    <div class="chart-card">
      <h3><span class="dot" style="background:#ff6f00"></span>Year-on-Year Price Growth</h3>
      <div style="max-height:300px;overflow-y:auto">
        <table class="yoy-table" id="yoyTable">
          <thead><tr><th>Year</th><th>Avg AED/sqft</th><th>YoY Change</th><th>Trend</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="chart-card">
      <h3><span class="dot" style="background:#40c4ff"></span>Bedroom Breakdown — {{ this_year }}</h3>
      <div style="overflow-x:auto">
        <table class="room-table" id="roomTable">
          <thead><tr><th>Type</th><th>Avg AED/sqft</th><th>Avg Price (AED)</th><th>Avg Size (sqft)</th><th>Deals</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ROI & RENTAL YIELD SECTION -->
  <div class="roi-section">
    <h2>💰 ROI & Rental Yield — MODELLED</h2>
    <p style="background:#352a10;color:#f3d28a;border-radius:8px;padding:10px 14px;font-size:12px;margin:0 0 16px">
      ⚠ Assumption, not data: rents are a hard-coded table of 2025 estimates (<code>ANNUAL_RENTS</code> in app.py) —
      DLD sales records contain no rents. Prices are real; yields and ROI below are only as good as those rent assumptions.
      This is why the <code>ask/</code> layer refuses yield questions.</p>

    <!-- ROI Summary Cards -->
    <div class="roi-cards" id="roiCards"></div>

    <div class="charts-grid">
      <div class="chart-card">
        <h3><span class="dot" style="background:#00e676"></span>Total ROI Trend by Year</h3>
        <div class="chart-wrap"><canvas id="chartRoi"></canvas></div>
      </div>

      <div class="chart-card">
        <h3><span class="dot" style="background:#69f0ae"></span>Gross Yield by Bedroom Type</h3>
        <div class="chart-wrap"><canvas id="chartYield"></canvas></div>
      </div>

      <div class="chart-card full">
        <h3><span class="dot" style="background:#00b0ff"></span>Rental Yield & ROI by Unit Type — Current Year</h3>
        <div style="overflow-x:auto">
          <table class="yield-table" id="yieldTable">
            <thead>
              <tr>
                <th>Community</th><th>Type</th><th>Bedrooms</th>
                <th>Avg Price (AED)</th><th>Annual Rent (AED)</th><th>Monthly Rent</th>
                <th>Gross Yield</th><th>Net Yield</th><th>Yield Bar</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- RECENT TRANSACTIONS -->
  <div class="txn-section">
    <div class="txn-header">
      <h2>Recent Transactions</h2>
      <span style="font-size:12px;color:#37474f">Latest 100</span>
    </div>
    <div class="txn-table-wrap">
      <table class="txn-table">
        <thead>
          <tr>
            <th>Date</th><th>Community</th><th>Building</th>
            <th>Type</th><th>Beds</th><th>Registration</th>
            <th>Price (AED)</th><th>AED/sqft</th><th>Size (sqft)</th>
          </tr>
        </thead>
        <tbody id="txnBody"></tbody>
      </table>
    </div>
  </div>

</div>

<div class="footer">Dubai RE Intelligence Dashboard · Data Source: Dubai Land Department (DLD) · Auto-refreshes every 5 minutes</div>

<script>
// ── STATE ──────────────────────────────────────────────────────────────
let state = { community: "ALL", propType: "ALL", yearFrom: "", yearTo: "" };
let charts = {};

function getParams() {
  const p = new URLSearchParams();
  p.set("community", state.community);
  p.set("prop_type", state.propType);
  if (state.yearFrom) p.set("year_from", state.yearFrom);
  if (state.yearTo)   p.set("year_to",   state.yearTo);
  return p.toString();
}

// ── INIT ───────────────────────────────────────────────────────────────
async function init() {
  const f = await fetch("/api/filters").then(r => r.json());

  // Populate year selects
  ["yearFromFilter","yearToFilter"].forEach(id => {
    const sel = document.getElementById(id);
    f.years.forEach(y => {
      const opt = document.createElement("option");
      opt.value = y; opt.textContent = y;
      sel.appendChild(opt);
    });
  });
  document.getElementById("yearToFilter").value = f.years[f.years.length - 1] || "";

  // Populate property type
  const pts = document.getElementById("propTypeFilter");
  f.prop_types.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    pts.appendChild(opt);
  });

  // Community pills
  document.querySelectorAll("#communityPills .pill").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#communityPills .pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.community = btn.dataset.val;
      refreshAll();
    });
  });

  document.getElementById("propTypeFilter").addEventListener("change", e => { state.propType = e.target.value; refreshAll(); });
  document.getElementById("yearFromFilter").addEventListener("change", e => { state.yearFrom = e.target.value; refreshAll(); });
  document.getElementById("yearToFilter").addEventListener("change", e => { state.yearTo = e.target.value; refreshAll(); });

  refreshAll();
  setInterval(refreshAll, 300_000);
}

async function refreshAll() {
  await Promise.all([
    loadSummary(), loadPriceTrend(), loadVolume(),
    loadOffplanSplit(), loadBedrooms(), loadYoY(),
    loadRoi(), loadRentalYield(),
    loadTransactions()
  ]);
}

// ── SUMMARY ────────────────────────────────────────────────────────────
async function loadSummary() {
  const data = await fetch("/api/summary?" + getParams()).then(r => r.json());
  if (!data || !data.avg_ppsf) return;

  const badge = document.getElementById("demoBadge");
  if (data.has_real) {
    badge.textContent = "✅ LIVE DLD DATA — Mar 2026 + historical";
    badge.style.background = "#002a10"; badge.style.color = "#00e676";
    badge.style.borderColor = "#00e67655"; badge.classList.add("show");
  } else {
    badge.classList.add("show");
  }
  document.getElementById("lastUpdated").textContent = "Data to: " + data.latest_year;

  document.getElementById("statPpsf").textContent = "AED " + fmt(data.avg_ppsf);
  setChg("statPpsfChg", data.avg_ppsf_chg);
  document.getElementById("statPrice").textContent = "AED " + fmt(data.avg_price);
  setChg("statPriceChg", data.avg_price_chg);
  document.getElementById("statTxn").textContent = fmt(data.total_txn);
  document.getElementById("statVal").textContent = "AED " + data.total_val_b + "B";
  document.getElementById("statOffplan").textContent = data.offplan_pct + "%";

  // Signal cards
  const row = document.getElementById("signalRow");
  row.innerHTML = "";
  (data.communities || []).forEach(c => {
    const card = document.createElement("div");
    card.className = "signal-card";
    card.style.setProperty("--sig-color", c.color);
    card.innerHTML = `
      <div class="community">${c.name}</div>
      <div class="signal-val">${c.signal}</div>
      <div class="signal-reason">${c.reason}</div>
      <div class="ppsf-row">
        <div class="metric"><div class="val">AED ${fmt(c.avg_ppsf)}</div><div class="lbl">Avg AED/sqft</div></div>
        <div class="metric"><div class="val ${c.yoy_ppsf >= 0 ? 'chg-pos':'chg-neg'}">${c.yoy_ppsf >= 0 ? '+':''}${c.yoy_ppsf}%</div><div class="lbl">YoY PPSF</div></div>
        <div class="metric"><div class="val">${fmt(c.txn_count)}</div><div class="lbl">Deals (YTD)</div></div>
      </div>`;
    row.appendChild(card);
  });
}

function setChg(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  const cls = val >= 0 ? "chg-pos" : "chg-neg";
  el.className = "chg " + cls;
  el.textContent = (val >= 0 ? "▲ +" : "▼ ") + Math.abs(val) + "% vs prev year";
}

// ── PRICE TREND ────────────────────────────────────────────────────────
async function loadPriceTrend() {
  const data = await fetch("/api/price_trend?" + getParams()).then(r => r.json());
  if (!data.labels) return;

  const ctx = document.getElementById("chartPrice").getContext("2d");
  if (charts.price) charts.price.destroy();

  charts.price = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels.map(formatLabel),
      datasets: data.datasets.map(ds => ({
        label: ds.label,
        data: ds.data,
        borderColor: ds.color,
        backgroundColor: ds.color + "15",
        tension: 0.3,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 2,
        fill: true,
        spanGaps: true,
      }))
    },
    options: chartOpts("AED / sqft", true)
  });
}

// ── VOLUME ────────────────────────────────────────────────────────────
async function loadVolume() {
  const data = await fetch("/api/volume_trend?" + getParams()).then(r => r.json());
  if (!data.labels) return;

  const ctx = document.getElementById("chartVolume").getContext("2d");
  if (charts.volume) charts.volume.destroy();

  charts.volume = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.labels.map(formatLabel),
      datasets: data.datasets.map(ds => ({
        label: ds.label, data: ds.data,
        backgroundColor: ds.color + "cc",
        borderRadius: 3,
      }))
    },
    options: chartOpts("Transactions", false, true)
  });
}

// ── OFFPLAN DONUT ─────────────────────────────────────────────────────
async function loadOffplanSplit() {
  const data = await fetch("/api/offplan_split?" + getParams()).then(r => r.json());
  const keys = Object.keys(data);
  if (!keys.length) return;

  const colors = keys.map(k => k.toLowerCase().includes("off") ? "#1e88e5" : "#00c853");
  const ctx = document.getElementById("chartDonut").getContext("2d");
  if (charts.donut) charts.donut.destroy();

  charts.donut = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: keys.map(k => k.toLowerCase().includes("off") ? "Off-Plan" : "Secondary"),
      datasets: [{ data: Object.values(data), backgroundColor: colors, borderWidth: 0 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "68%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a,b) => a+b, 0);
              return " " + ctx.label + ": " + ctx.raw + " (" + Math.round(ctx.raw/total*100) + "%)";
            }
          }
        }
      }
    }
  });

  const leg = document.getElementById("donutLegend");
  leg.innerHTML = keys.map((k,i) => {
    const total = Object.values(data).reduce((a,b) => a+b,0);
    const pct = Math.round(data[k]/total*100);
    const label = k.toLowerCase().includes("off") ? "Off-Plan" : "Secondary";
    return `<div class="dl-item"><div class="dl-dot" style="background:${colors[i]}"></div><span>${label}: ${pct}%</span></div>`;
  }).join("");
}

// ── BEDROOM CHART ─────────────────────────────────────────────────────
async function loadBedrooms() {
  const data = await fetch("/api/bedroom_breakdown?" + getParams()).then(r => r.json());
  if (!data.length) return;

  const ctx = document.getElementById("chartBedroom").getContext("2d");
  if (charts.bedroom) charts.bedroom.destroy();

  const grad = ["#1e88e5","#00acc1","#00c853","#ffd600","#ff6f00","#ce93d8"];
  charts.bedroom = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map(d => d.room),
      datasets: [{
        label: "Avg AED/sqft",
        data: data.map(d => d.avg_ppsf),
        backgroundColor: data.map((_,i) => grad[i % grad.length] + "cc"),
        borderRadius: 6,
      }]
    },
    options: chartOpts("AED / sqft")
  });

  // Fill room table
  const tbody = document.getElementById("roomTable").querySelector("tbody");
  tbody.innerHTML = data.map(d => `
    <tr>
      <td>${d.room}</td>
      <td><b>AED ${fmt(d.avg_ppsf)}</b></td>
      <td>AED ${fmtM(d.avg_price)}</td>
      <td>${fmt(d.avg_sqft)} sqft</td>
      <td style="color:#546e7a">${d.count}</td>
    </tr>`).join("");
}

// ── YOY ───────────────────────────────────────────────────────────────
async function loadYoY() {
  const data = await fetch("/api/yoy_ppsf?" + getParams()).then(r => r.json());
  if (!data.length) return;

  const maxPpsf = Math.max(...data.map(d => d.avg_ppsf));
  const tbody = document.getElementById("yoyTable").querySelector("tbody");
  tbody.innerHTML = data.map(d => {
    const yoy = d.yoy_chg;
    const cls = !yoy ? "" : yoy > 0 ? "chg-pos" : "chg-neg";
    const barW = Math.round(d.avg_ppsf / maxPpsf * 80);
    const arrow = !yoy ? "—" : (yoy > 0 ? "▲" : "▼") + " " + Math.abs(yoy) + "%";
    return `<tr>
      <td><b>${d.year}</b></td>
      <td>AED ${fmt(d.avg_ppsf)}</td>
      <td class="${cls}">${arrow}</td>
      <td><span class="bar-inline" style="width:${barW}px;background:${yoy > 0 ? '#00c853' : yoy < 0 ? '#ff1744' : '#546e7a'}"></span></td>
    </tr>`;
  }).join("");
}

// ── TRANSACTIONS ──────────────────────────────────────────────────────
async function loadTransactions() {
  const data = await fetch("/api/recent_transactions?" + getParams()).then(r => r.json());
  const tbody = document.getElementById("txnBody");
  if (!data.length) { tbody.innerHTML = '<tr><td colspan="9" class="empty">No transactions</td></tr>'; return; }

  tbody.innerHTML = data.map(t => {
    const isES = t.area && t.area.includes("EMAAR");
    const commCls = isES ? "community-es" : "community-ch";
    const commName = isES ? "Emaar South" : "Creek Harbour";
    const regBadge = t.reg_type && t.reg_type.toLowerCase().includes("off")
      ? `<span class="badge-offplan">Off-Plan</span>`
      : `<span class="badge-ready">Secondary</span>`;
    return `<tr>
      <td style="color:#546e7a">${t.date}</td>
      <td class="${commCls}">${commName}</td>
      <td style="color:#90a4ae">${t.building || "—"}</td>
      <td>${t.property_type || "—"}</td>
      <td>${t.rooms || "—"}</td>
      <td>${regBadge}</td>
      <td><b>AED ${fmt(t.price_aed)}</b></td>
      <td style="color:#40c4ff">AED ${fmt(t.ppsf)}</td>
      <td style="color:#546e7a">${fmt(t.sqft)} sqft</td>
    </tr>`;
  }).join("");
}

// ── ROI ────────────────────────────────────────────────────────────────
async function loadRoi() {
  const data = await fetch("/api/roi?" + getParams()).then(r => r.json());
  if (!data.length) return;

  // ROI summary cards
  const container = document.getElementById("roiCards");
  container.innerHTML = data.map(c => {
    const yieldColor  = c.yield >= 6 ? "#00e676" : c.yield >= 5 ? "#69f0ae" : "#ffd600";
    const capColor    = c.cap_gain >= 0 ? "#40c4ff" : "#ff5252";
    const totalColor  = c.total_roi >= 10 ? "#00e676" : c.total_roi >= 7 ? "#69f0ae" : "#ffd600";
    return `<div class="roi-card">
      <div class="rc-community">${c.community}</div>
      <div class="rc-total" style="color:${totalColor}">${c.total_roi}% <span>Total ROI (est.)</span></div>
      <div style="font-size:11px;color:#37474f;margin-top:2px">Rental Yield + Capital Appreciation</div>
      <div class="rc-breakdown">
        <div class="rcb"><div class="val" style="color:${yieldColor}">${c.yield}%</div><div class="lbl">Gross Yield</div></div>
        <div class="rcb"><div class="val" style="color:${capColor}">${c.cap_gain >= 0 ? '+':''}${c.cap_gain}%</div><div class="lbl">Cap. Gain YoY</div></div>
        <div class="rcb"><div class="val" style="color:#546e7a">${(c.yield * 0.78).toFixed(1)}%</div><div class="lbl">Net Yield</div></div>
      </div>
    </div>`;
  }).join("");

  // ROI trend chart (stacked: yield + cap gain)
  const allYears = [...new Set(data.flatMap(c => c.yearly.map(y => y.year)))].sort();
  const commColors = { "Emaar South": "#ffd600", "Creek Harbour": "#40c4ff" };

  const ctx = document.getElementById("chartRoi").getContext("2d");
  if (charts.roi) charts.roi.destroy();

  const datasets = [];
  data.forEach(c => {
    const col = commColors[c.community] || "#9c27b0";
    const byYear = Object.fromEntries(c.yearly.map(y => [y.year, y]));
    datasets.push({
      label: c.community + " — Total ROI",
      data: allYears.map(y => byYear[y]?.total_roi ?? null),
      borderColor: col, backgroundColor: col + "20",
      tension: 0.3, pointRadius: 3, borderWidth: 2, fill: true, spanGaps: true,
    });
  });

  charts.roi = new Chart(ctx, {
    type: "line",
    data: { labels: allYears, datasets },
    options: {
      ...chartOpts("ROI %"),
      plugins: {
        ...chartOpts("ROI %").plugins,
        tooltip: {
          backgroundColor: "#0d1117", borderColor: "#1e2a3a", borderWidth: 1,
          titleColor: "#90a4ae", bodyColor: "#e0e0e0",
          callbacks: {
            label: ctx => {
              const d2 = data.find(c => ctx.dataset.label.startsWith(c.community));
              const yr  = allYears[ctx.dataIndex];
              const row = d2?.yearly.find(y => y.year === yr);
              if (!row) return "";
              return ` ${ctx.dataset.label.split("—")[0].trim()}: Yield ${row.yield}% + CapGain ${row.cap_gain}% = ${row.total_roi}%`;
            }
          }
        }
      }
    }
  });
}

// ── RENTAL YIELD ───────────────────────────────────────────────────────
async function loadRentalYield() {
  const data = await fetch("/api/rental_yield?" + getParams()).then(r => r.json());
  if (!data.length) return;

  // Yield bar chart by bedroom type (group by room, avg across communities)
  const rooms = [...new Set(data.map(d => d.room))];
  const commKeys = [...new Set(data.map(d => d.community))];
  const commColors = { "Emaar South": "#ffd600cc", "Creek Harbour": "#40c4ffcc" };

  const ctx = document.getElementById("chartYield").getContext("2d");
  if (charts.yield) charts.yield.destroy();

  charts.yield = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rooms,
      datasets: commKeys.map(comm => ({
        label: comm,
        data: rooms.map(r => {
          const rows = data.filter(d => d.community === comm && d.room === r);
          return rows.length ? +(rows.reduce((s,d) => s + d.gross_yield, 0) / rows.length).toFixed(2) : null;
        }),
        backgroundColor: commColors[comm] || "#9c27b0aa",
        borderRadius: 5,
      }))
    },
    options: chartOpts("Gross Yield %")
  });

  // Fill yield table
  const maxYield = Math.max(...data.map(d => d.gross_yield));
  const tbody = document.getElementById("yieldTable").querySelector("tbody");
  tbody.innerHTML = data.map(d => {
    const barW = Math.round(d.gross_yield / maxYield * 80);
    const isBest = d.gross_yield >= 7;
    const yieldColor = d.gross_yield >= 7 ? "#00e676" : d.gross_yield >= 6 ? "#69f0ae" : d.gross_yield >= 5 ? "#ffd600" : "#ff9100";
    const commColor  = d.community === "Emaar South" ? "#ffd600" : "#40c4ff";
    return `<tr>
      <td style="color:${commColor};font-weight:600">${d.community}</td>
      <td style="color:#90a4ae">${d.prop_type}</td>
      <td>${d.room}</td>
      <td>AED ${fmt(d.avg_price)}</td>
      <td>AED ${fmt(d.annual_rent)}</td>
      <td style="color:#546e7a">AED ${fmt(d.monthly_rent)}/mo</td>
      <td style="color:${yieldColor};font-weight:700">${d.gross_yield}%${isBest ? ' <span class="best-badge">BEST</span>' : ''}</td>
      <td style="color:#546e7a">${d.net_yield}%</td>
      <td><span class="yield-bar" style="width:${barW}px;background:${yieldColor}"></span></td>
    </tr>`;
  }).join("");
}

// ── HELPERS ───────────────────────────────────────────────────────────
function fmt(n) {
  if (!n || n === "—") return "—";
  return Number(n).toLocaleString("en-AE");
}
function fmtM(n) {
  if (!n) return "—";
  if (n >= 1_000_000) return (n/1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n/1_000).toFixed(0) + "K";
  return n;
}
function formatLabel(ym) {
  if (!ym || !ym.includes("-")) return ym;
  const [y, m] = ym.split("-");
  const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return months[parseInt(m)] + " " + y.slice(2);
}
function chartOpts(yLabel, smooth=false, stacked=false) {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: "#546e7a", font: { size: 11 }, boxWidth: 12 } },
      tooltip: {
        backgroundColor: "#0d1117", borderColor: "#1e2a3a", borderWidth: 1,
        titleColor: "#90a4ae", bodyColor: "#e0e0e0",
        callbacks: {
          label: ctx => " " + ctx.dataset.label + ": " + (ctx.raw ? Number(ctx.raw).toLocaleString() : "—")
        }
      }
    },
    scales: {
      x: { stacked, grid: { color: "#111927" }, ticks: { color: "#37474f", maxTicksLimit: 14, font: { size: 10 } } },
      y: { stacked, grid: { color: "#111927" }, ticks: { color: "#37474f", font: { size: 10 } },
           title: { display: true, text: yLabel, color: "#37474f", font: { size: 10 } } }
    }
  };
}

document.addEventListener("DOMContentLoaded", init);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    print("\n" + "═"*58)
    print("  Dubai RE Intelligence Dashboard")
    print("  Open: 👉  http://localhost:8085")
    print(f"  Communities: Emaar South | Creek Harbour")
    print(f"  Transactions loaded: {len(DF):,}")
    print(f"  Date range: {DF['date'].min().date()} → {DF['date'].max().date()}")
    print(f"  Data mode: {'⚠ DEMO' if IS_DEMO else '✅ REAL DLD'}")
    if IS_DEMO:
        print("  ─────────────────────────────────────────────────────")
        print("  To load REAL data, download from:")
        print("  https://dubailand.gov.ae/en/open-data/real-estate-data/")
        print("  Save as: data/dld_transactions.csv  → restart app")
    print("═"*58 + "\n")
    app.run(host="0.0.0.0", port=8085, debug=False)
