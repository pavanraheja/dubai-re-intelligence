"""
Tools the agent is allowed to call. Each one is a plain pandas function that
returns (result_dict, Evidence). Nothing here talks to a model.

Adding a tool = adding a capability. The agent cannot invent one.
"""
import os
import pandas as pd
from . import evidence as ev

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "dashboard", "data")
REAL = os.path.join(DATA, "dld_transactions.csv")
DEMO = os.path.join(DATA, "dld_demo.csv")

_cache = {}


def load():
    """Load DLD transactions, normalising the two export formats."""
    if "df" in _cache:
        return _cache["df"], _cache["source"]

    if os.path.exists(REAL):
        path, source = REAL, "DLD open data, real sales"
        report = os.path.join(os.path.dirname(DATA), "..", "pipeline", "extract_report.json")
        try:
            import json
            source += f" · pulled {json.load(open(report))['pulled_at'][:10]}"
        except Exception:
            pass
    else:
        path, source = DEMO, "SYNTHETIC demo data — generated, not real transactions"
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    rename = {"instance_date": "date", "area_name_en": "area", "area_en": "area",
              "actual_worth": "price_aed", "trans_value": "price_aed",
              "procedure_area": "sqm", "reg_type_en": "reg_type",
              "is_offplan_en": "reg_type", "property_type_en": "property_type",
              "prop_type_en": "property_type", "rooms_en": "rooms"}
    for src, dst in rename.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "price_aed"])
    df["area"] = df["area"].str.upper().str.strip()
    df["sqft"] = df.get("sqft", df["sqm"] * 10.7639)
    df["ppsf"] = df["price_aed"] / df["sqft"].replace(0, pd.NA)
    df["ym"] = df["date"].dt.to_period("M")

    _cache["df"], _cache["source"] = df, source
    return df, source


def _window(df):
    return (df["date"].min().to_pydatetime(), df["date"].max().to_pydatetime())


def _offplan_share(d):
    if "reg_type" not in d or d.empty:
        return 0.0
    return (d["reg_type"].astype(str).str.lower().str.contains("off")).mean() * 100


# ── TOOL 1 ────────────────────────────────────────────────────────────────
def compare_communities(months=12, areas=None):
    """Compare the communities on volume, median price per sqft and momentum."""
    df, source = load()
    areas = areas or sorted(df["area"].unique())
    cutoff = df["date"].max() - pd.DateOffset(months=months)
    recent = df[df["date"] >= cutoff]

    rows, shares, result = [], {}, {}
    for a in areas:
        d = recent[recent["area"] == a]
        prior = df[(df["area"] == a) & (df["date"] < cutoff) &
                   (df["date"] >= cutoff - pd.DateOffset(months=months))]
        rows.append(len(d))
        shares[a.title()] = _offplan_share(d)
        med_now = d["ppsf"].median()
        med_prev = prior["ppsf"].median() if len(prior) else None
        result[a] = {
            "transactions": len(d),
            "median_ppsf": round(med_now, 1) if pd.notna(med_now) else None,
            "median_price_aed": int(d["price_aed"].median()) if len(d) else None,
            "offplan_share_pct": round(shares[a.title()], 1),
            "yoy_ppsf_pct": round((med_now / med_prev - 1) * 100, 1)
            if med_prev and pd.notna(med_now) else None,
            "prior_period_rows": len(prior),
        }

    e = ev.grade(rows, _window(recent), source)
    e = ev.check_like_for_like(e, shares)
    for a, r in result.items():
        if r["prior_period_rows"] == 0:
            e.caveats.append(f"{a.title()}: no prior-period rows in this extract "
                             f"(starts {df['date'].min():%b %Y}) — year-on-year not computed")
        elif r["yoy_ppsf_pct"] is not None and r["prior_period_rows"] < ev.MIN_ROWS_ANSWER:
            e.caveats.append(f"{a.title()} year-on-year based on only "
                             f"{r['prior_period_rows']} prior-period rows — directional only")
    return result, e


# ── TOOL 2 ────────────────────────────────────────────────────────────────
def price_trend(area=None, months=24):
    """Monthly median price per sqft, to show direction rather than a single number."""
    df, source = load()
    d = df if area is None else df[df["area"] == area.upper()]
    cutoff = d["date"].max() - pd.DateOffset(months=months)
    d = d[d["date"] >= cutoff]
    g = d.groupby("ym").agg(txns=("price_aed", "size"), median_ppsf=("ppsf", "median"))
    g = g[g["txns"] >= 5]                      # months with <5 deals are noise, dropped
    series = {str(k): round(v, 1) for k, v in g["median_ppsf"].items()}

    e = ev.grade([len(d)], _window(d), source)
    dropped = len(set(d["ym"])) - len(g)
    if dropped:
        e.caveats.append(f"{dropped} month(s) dropped — fewer than 5 transactions, too thin to plot")
    return {"area": area or "all", "monthly_median_ppsf": series,
            "first": list(series.values())[0] if series else None,
            "last": list(series.values())[-1] if series else None}, e


# ── TOOL 3 ────────────────────────────────────────────────────────────────
def segment_breakdown(area=None, by="property_type", months=12):
    """Where the money actually goes: split volume and price by segment."""
    df, source = load()
    d = df if area is None else df[df["area"] == area.upper()]
    d = d[d["date"] >= d["date"].max() - pd.DateOffset(months=months)]
    if by not in d.columns:
        return {"error": f"cannot split by '{by}'"}, ev.Evidence(
            source=source, refusals=[f"no column '{by}' in this dataset"])

    g = d.groupby(by).agg(txns=("price_aed", "size"),
                          median_ppsf=("ppsf", "median"),
                          value_aed=("price_aed", "sum")).sort_values("txns", ascending=False)
    e = ev.grade([len(d)], _window(d), source)
    thin = g[g["txns"] < ev.MIN_ROWS_ANSWER].index.tolist()
    if thin:
        e.caveats.append(f"segments with thin samples, medians unreliable: {', '.join(map(str, thin))}")
    return {"area": area or "all", "by": by,
            "segments": {str(k): {"txns": int(v.txns),
                                  "median_ppsf": round(v.median_ppsf, 1) if pd.notna(v.median_ppsf) else None,
                                  "value_aed_m": round(v.value_aed / 1e6, 1)}
                         for k, v in g.iterrows()}}, e


# ── TOOL 4 ────────────────────────────────────────────────────────────────
def data_coverage():
    """What this dataset can and cannot speak to. Called before anything else."""
    df, source = load()
    e = ev.grade([len(df)], _window(df), source)
    return {"rows": len(df),
            "areas": sorted(df["area"].unique().tolist()),
            "from": str(df["date"].min().date()),
            "to": str(df["date"].max().date()),
            "columns_available": sorted(df.columns.tolist()),
            "not_in_source": ["rental yields", "service charges", "handover dates",
                              "population", "mortgage rates", "forward supply"]}, e


# ── TOOL 5 ────────────────────────────────────────────────────────────────
def community_snapshot(area="DUBAI CREEK HARBOUR"):
    """One community at a glance — the answer to "what's going on with X?"."""
    df, source = load()
    d = df[df["area"] == area.upper()]
    monthly = d.groupby("ym").agg(txns=("price_aed", "size"), med=("ppsf", "median"))
    monthly = monthly[monthly["txns"] >= 5]
    first, last = (monthly.iloc[0], monthly.iloc[-1]) if len(monthly) else (None, None)
    rooms = d["rooms"].value_counts(normalize=True).head(3) if "rooms" in d else pd.Series(dtype=float)

    e = ev.grade([len(d)], _window(d) if len(d) else None, source)
    if len(monthly) and len(monthly) < len(set(d["ym"])):
        e.caveats.append("months with fewer than 5 sales left out of the trend")
    return {"area": area,
            "transactions": len(d),
            "median_ppsf": round(d["ppsf"].median(), 1) if len(d) else None,
            "median_price_aed": int(d["price_aed"].median()) if len(d) else None,
            "offplan_share_pct": round(_offplan_share(d), 1),
            "trend": {"from_month": str(monthly.index[0]), "to_month": str(monthly.index[-1]),
                      "from_ppsf": round(first["med"], 1), "to_ppsf": round(last["med"], 1),
                      "change_pct": round((last["med"] / first["med"] - 1) * 100, 1)}
            if len(monthly) >= 2 else None,
            "top_bedrooms": {str(k): round(v * 100, 1) for k, v in rooms.items()},
            "busiest_month": str(monthly["txns"].idxmax()) if len(monthly) else None}, e


TOOLS = {
    "community_snapshot": community_snapshot,
    "compare_communities": compare_communities,
    "price_trend": price_trend,
    "segment_breakdown": segment_breakdown,
    "data_coverage": data_coverage,
}
