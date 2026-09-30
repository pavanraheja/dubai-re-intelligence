"""
Decision workbench for Dubai South: rank projects under criteria and weights that
the PERSON deciding sets. The engine never picks. It computes evidence per project,
grades its confidence, tests how fragile the ranking is, and lists what the data
cannot tell you.

Everything here is computed from registry sales (dashboard/data/dubai_south.csv).
"""
import json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "dashboard", "data", "dubai_south.csv")
REPORT = os.path.join(ROOT, "pipeline", "dubai_south_report.json")

MIN_SALES = 30          # below this a project is listed, never ranked
LAUNCH_BURST = 0.60     # more than this share of sales in one month = launch-only evidence
MIN_QUARTER = 10        # sales needed in both Q1 and Q3 before a price trend is computed

CRITERIA = {
    "demand": "Recent buyer demand: average sales per month, Jul–Sep",
    "persistence": "Demand persistence: 1 minus the share of sales in the busiest month",
    "depth": "Market depth: total sales this year",
    "stability": "Price consistency: 1 minus the spread of price per sqft (IQR ÷ median)",
    "momentum": "Price momentum you can rely on: the LOWER end of the 90% interval for Q1 → Q3 median price per sqft",
    "value": "Entry value: price per sqft against the Dubai South median (lower scores higher)",
}

PRESETS = {
    "demand_first": {"label": "Demand first (proxy for liquidity)",
                     "weights": {"demand": .35, "persistence": .30, "depth": .20, "stability": .15}},
    "growth": {"label": "Capital growth",
               "weights": {"momentum": .50, "demand": .20, "persistence": .15, "stability": .15}},
    "value": {"label": "Entry value",
              "weights": {"value": .45, "stability": .20, "demand": .20, "persistence": .15}},
}

GAPS = [
    "Exit liquidity: resales are 0.7% of 2026 Dubai South sales, too few to measure how easily units resell",
    "Rental yield: not in sales records",
    "Handover date and construction progress: not in sales records",
    "Developer delivery record: not in sales records",
    "Payment plan terms and service charges: not in sales records",
    "Unsold inventory: sales show demand, not how much stock is left",
]


def load():
    d = pd.read_csv(DATA, parse_dates=["date"])
    d["ym"] = d["date"].dt.to_period("M")
    return d


def _pct_rank(s, higher_better=True):
    r = s.rank(pct=True, method="average")
    return r if higher_better else 1 - r + (1 / len(s))


def _momentum(g, rng, draws=500):
    q1 = g[g["date"].dt.quarter == 1]["ppsf"].to_numpy()
    q3 = g[g["date"].dt.quarter == 3]["ppsf"].to_numpy()
    if len(q1) < MIN_QUARTER or len(q3) < MIN_QUARTER:
        return None, None, None
    point = (np.median(q3) / np.median(q1) - 1) * 100
    boots = [(np.median(rng.choice(q3, len(q3))) / np.median(rng.choice(q1, len(q1))) - 1) * 100
             for _ in range(draws)]
    lo, hi = np.percentile(boots, [5, 95])
    return round(float(point), 1), round(float(lo), 1), round(float(hi), 1)


def metrics(d, budget=(1_000_000, 2_500_000), stage="all", include_expo=True, seed=7):
    """One row per project group, with every criterion value and eligibility."""
    rng = np.random.default_rng(seed)
    last = d["ym"].max()
    recent = [last - i for i in range(3)]
    area_median = d["ppsf"].median()
    rows = []
    for name, g in d.groupby("project_group"):
        monthly = g.groupby("ym").size()
        mom, lo, hi = _momentum(g, rng)
        iqr = g["ppsf"].quantile(.75) - g["ppsf"].quantile(.25)
        offplan = (g["reg_type"] == "Off-Plan").mean()
        in_budget = g["price_aed"].between(*budget).mean()
        row = {
            "project": name, "master": g["master"].mode()[0], "sales": len(g),
            "phases": g["project"].nunique(),
            "first_sale": str(g["date"].min().date()), "months_active": int(monthly.size),
            "demand": round(monthly.reindex(recent, fill_value=0).mean(), 1),
            "persistence": round(1 - monthly.max() / len(g), 2),
            "depth": len(g),
            "stability": round(1 - iqr / g["ppsf"].median(), 2),
            # scored on the lower bound: a +7.7% point estimate with a -25%..+27% interval is noise
            "momentum": lo, "momentum_point": mom, "momentum_ci": [lo, hi] if mom is not None else None,
            "value": round(g["ppsf"].median() / area_median, 2),
            "median_ppsf": round(g["ppsf"].median(), 0),
            "median_price": int(g["price_aed"].median()),
            "offplan_share": round(offplan, 2), "resale_share": round((g["procedure"] == "Delayed Sell").mean(), 3),
            "in_budget_share": round(in_budget, 2),
        }
        why = []
        if name == "UNNAMED":
            why.append("no project name in the registry")
        if len(g) < MIN_SALES:
            why.append(f"fewer than {MIN_SALES} sales")
        if in_budget < .25:
            why.append("under 25% of sales inside the budget")
        if not include_expo and row["master"].startswith("Expo"):
            why.append("Expo City / Expo Living excluded from the mandate")
        if stage == "offplan" and offplan < .5:
            why.append("mostly ready, outside the off-plan filter")
        if stage == "ready" and offplan >= .5:
            why.append("mostly off-plan, outside the ready filter")
        row["excluded_because"] = why
        row["launch_burst"] = monthly.max() / len(g) > LAUNCH_BURST
        rows.append(row)
    return pd.DataFrame(rows)


def score(m, weights):
    """Percentile-rank each criterion among eligible projects, then weight.
    A criterion a project has no value for (momentum without two quarters of sales)
    is left out of its score and its weights are renormalised; the project is marked."""
    e = m[m["excluded_because"].str.len() == 0].copy()
    w = {k: v for k, v in weights.items() if v > 0}
    total = sum(w.values())
    w = {k: v / total for k, v in w.items()}
    pct = {}
    for c in w:
        vals = e[c].astype(float)
        ok = vals.notna()
        p = pd.Series(np.nan, index=e.index)
        if ok.sum():
            p[ok] = _pct_rank(vals[ok], higher_better=(c != "value"))
        pct[c] = p
    scores, missing = [], []
    for i in e.index:
        have = {c: pct[c][i] for c in w if pd.notna(pct[c][i])}
        tw = sum(w[c] for c in have)
        scores.append(sum(w[c] * v for c, v in have.items()) / tw if tw else np.nan)
        missing.append([c for c in w if c not in have])
    e["score"] = np.round(scores, 3)
    e["missing_criteria"] = missing
    e["confidence"] = [
        "LOW" if r.launch_burst or r.missing_criteria else ("HIGH" if r.sales >= 200 else "MEDIUM")
        for r in e.itertuples()]
    return e.sort_values("score", ascending=False), pct, w


def stress(e_sorted, pct, w, draws=2000, seed=11):
    """How fragile is the ranking? Resample weights around the chosen ones (Dirichlet)
    and count how often each project comes first and top-3. Then find single weight
    changes (×0.5 and ×1.5 on one criterion) that change the first place."""
    rng = np.random.default_rng(seed)
    crits = list(w)
    M = np.column_stack([pct[c].reindex(e_sorted.index).fillna(0.5).to_numpy() for c in crits])
    alpha = np.array([w[c] for c in crits]) * 30 + 0.5
    first = np.zeros(len(e_sorted))
    top3 = np.zeros(len(e_sorted))
    for ws in rng.dirichlet(alpha, draws):
        order = np.argsort(-(M @ ws))
        first[order[0]] += 1
        top3[order[:3]] += 1
    flips = []
    leader = e_sorted.index[0]
    for c in crits:
        for f in (0.5, 1.5):
            ww = {k: (v * f if k == c else v) for k, v in w.items()}
            t = sum(ww.values())
            vec = np.array([ww[k] / t for k in crits])
            new = e_sorted.index[int(np.argmax(M @ vec))]
            if new != leader:
                flips.append({"criterion": c, "factor": f, "new_leader": e_sorted.loc[new, "project"]})
    return (np.round(first / draws, 3), np.round(top3 / draws, 3), flips)


def run(preset="demand_first", weights=None, budget=(1_000_000, 2_500_000), stage="all", include_expo=True):
    d = load()
    m = metrics(d, budget, stage, include_expo)
    w_in = weights or PRESETS[preset]["weights"]
    ranked, pct, w = score(m, w_in)
    p_first, p_top3, flips = stress(ranked, pct, w)
    ranked = ranked.assign(p_first=p_first, p_top3=p_top3)
    report = json.load(open(REPORT)) if os.path.exists(REPORT) else {}
    options = ranked.to_dict("records")
    for o in options:
        o["gaps"] = (["Only launch demand observed: over 60% of sales came in one month"]
                     if o["launch_burst"] else []) + GAPS
    excluded = m[m["excluded_because"].str.len() > 0][["project", "sales", "excluded_because"]]
    warnings = []
    stages = {o["offplan_share"] >= .5 for o in options}
    if len(stages) == 2:
        warnings.append("Off-plan and ready projects are ranked together: prices are not like-for-like "
                        "(off-plan prices are launch prices). Use the stage filter to compare within one.")
    top3_expo = [o["project"] for o in options[:3] if o["master"].startswith("Expo")]
    if top3_expo:
        warnings.append(f"{len(top3_expo)} of the top 3 ({', '.join(top3_expo)}) are Expo City / Expo Living, "
                        "a separate master developer inside the same registry area. Check they fit the mandate.")
    if w.get("momentum"):
        solid = [o["project"] for o in options if o["momentum_ci"] and o["momentum_ci"][0] > 0]
        warnings.append(f"Only {len(solid)} project(s) show price momentum whose 90% interval sits above zero"
                        f"{': ' + ', '.join(solid) if solid else ''}. Nine months of prices barely support "
                        "a growth thesis; weight momentum with that in mind.")
    if len(p_first) and p_first[0] < .6:
        warnings.append(f"The leader comes first in only {round(float(p_first[0]) * 100, 1):g}% of plausible weightings: the ranking "
                        "at the top is not settled by the data. Decide on the gaps, not the score.")
    return {
        "frame": {"area": "Dubai South (registry: DUBAI SOUTH, EMAAR SOUTH, Madinat Al Mataar)",
                  "budget_aed": list(budget), "stage": stage, "include_expo": include_expo,
                  "preset": preset if not weights else "custom",
                  "weights": {k: round(v, 3) for k, v in w.items()}},
        "criteria": {k: CRITERIA[k] for k in w},
        "basis": {"rows": int(len(d)), "from": str(d["date"].min().date()), "to": str(d["date"].max().date()),
                  "pulled": report.get("pulled_at", "")[:10], "source": "DLD open data, real sales"},
        "options": options,
        "excluded": excluded.sort_values("sales", ascending=False).to_dict("records"),
        "warnings": warnings,
        "stress": {"leader_holds": float(p_first[0]) if len(p_first) else None, "flips": flips,
                   "draws": 2000},
        "global_gaps": GAPS,
    }
