"""
First look at candidate markets before building anything for them.

    python pipeline/market_scan.py

Same basis as the Dubai South extract: 2026 year to date, market sales, flats and villas,
the same price-per-sqft bounds and the same project grouping. Writes
pipeline/market_scan_2026.json. Registry names: Downtown is "BURJ KHALIFA"; Dubai Islands
is "PALM DEIRA" (the old name for the Deira Islands area). "Island 2" is Jumeira Bay island
(Bulgari), not Dubai Islands; it is scanned only to show that.
"""
import os, sys, datetime as dt, collections, json, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_dld import fetch_month
from communities import SALE_PROCEDURES, PROPERTY_TYPES, PPSF_MIN, PPSF_MAX
from fetch_dubai_south import project_group

AREAS = {"BUSINESS BAY": "Business Bay", "BURJ KHALIFA": "Downtown (registry: Burj Khalifa)",
         "PALM DEIRA": "Dubai Islands (registry: Palm Deira)", "ISLAND 2": "Island 2 (Jumeira Bay, not Dubai Islands)",
         "DUBAI SOUTH": "Dubai South", "EMAAR SOUTH": "Dubai South", "MADINAT AL MATAAR": "Dubai South"}
rows = collections.defaultdict(list)
m = dt.date(2026, 1, 1)
while m <= dt.date.today():
    for r in fetch_month(m):
        a = (r.get("AREA_EN") or "").strip().upper()
        if a not in AREAS or r.get("PROCEDURE_EN") not in SALE_PROCEDURES:
            continue
        pt = PROPERTY_TYPES.get(r.get("PROP_SB_TYPE_EN"))
        sqm, val = r.get("PROCEDURE_AREA") or 0, r.get("TRANS_VALUE") or 0
        ppsf = val / (sqm * 10.7639) if sqm else 0
        if pt and PPSF_MIN <= ppsf <= PPSF_MAX:
            rows[AREAS[a]].append({"a": a, "proj": project_group(r.get("PROJECT_EN")), "raw": (r.get("PROJECT_EN") or "").strip(),
                                   "proc": r["PROCEDURE_EN"], "ready": r.get("IS_OFFPLAN_EN") == "Ready",
                                   "ppsf": ppsf, "price": val, "month": r["INSTANCE_DATE"][:7], "rooms": r.get("ROOMS_EN")})
    m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

out = {}
for name, x in rows.items():
    proj = collections.Counter(r["proj"] for r in x if r["proj"] != "UNNAMED")
    ppsf = sorted(r["ppsf"] for r in x)
    q1, q3 = ppsf[len(ppsf) // 4], ppsf[3 * len(ppsf) // 4]
    resale = sum(1 for r in x if r["proc"] == "Delayed Sell" or (r["proc"] == "Sale" and r["ready"]))
    months = collections.Counter(r["month"] for r in x)
    out[name] = {"sales": len(x), "per_month": round(len(x) / len(months), 0),
                 "ready_share": round(sum(r["ready"] for r in x) / len(x), 2),
                 "resale_share": round(resale / len(x), 2),
                 "offplan_resales": sum(1 for r in x if r["proc"] == "Delayed Sell"),
                 "projects": len(proj), "projects_30plus": sum(1 for v in proj.values() if v >= 30),
                 "top_projects": proj.most_common(6),
                 "median_ppsf": round(statistics.median(ppsf)), "median_price": round(statistics.median(r["price"] for r in x)),
                 "ppsf_spread": round((q3 - q1) / statistics.median(ppsf), 2),
                 "studio_1br_share": round(sum(1 for r in x if r["rooms"] in ("Studio", "1 B/R")) / len(x), 2),
                 "registry_areas": sorted(set(r["a"] for r in x)),
                 "sample_raw_projects": sorted(set(r["raw"] for r in x))[:12]}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_scan_2026.json"), "w"), indent=2, default=str)
for k, v in out.items():
    print(f"== {k}")
    for kk in ("sales", "per_month", "ready_share", "resale_share", "offplan_resales", "projects", "projects_30plus",
               "median_ppsf", "median_price", "ppsf_spread", "studio_1br_share"):
        print(f"   {kk}: {v[kk]}")
    print("   top:", v["top_projects"])
