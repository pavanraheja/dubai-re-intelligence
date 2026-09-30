#!/usr/bin/env python3
"""
Project-level extract for the Dubai South decision workbench (decide/).

    python pipeline/fetch_dubai_south.py

"Dubai South" here = the three registry areas that cover it: DUBAI SOUTH, EMAAR SOUTH
and Madinat Al Mataar. Madinat Al Mataar also holds Expo City / Expo Living projects,
which are a separate master developer; they stay in, tagged, rather than silently
dropped or silently merged.

Same source, filters and current-year limit as fetch_dld.py. Written to its own file
so the two-community extract behind ask/ is not changed by this one.

Outputs:
  dashboard/data/dubai_south.csv          one row per kept sale, with project group
  pipeline/dubai_south_report.json        kept / dropped / grouping, per area
"""
import collections, csv, datetime as dt, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_dld import fetch_month, ROOT                      # noqa: E402
from communities import SALE_PROCEDURES, PROPERTY_TYPES, PPSF_MIN, PPSF_MAX, community_of  # noqa: E402

AREAS = {"DUBAI SOUTH", "EMAAR SOUTH", "MADINAT AL MATAAR"}
OUT_CSV = os.path.join(ROOT, "dashboard", "data", "dubai_south.csv")
OUT_REPORT = os.path.join(ROOT, "pipeline", "dubai_south_report.json")

# Phase numbers and suffixes are dropped so "AZIZI VENICE 14" and "Azizi Venice 6" are one
# option: an investor chooses a project, and single phases are too thin to rank on their own.
PHASE = re.compile(r"\b(PHASE\s*)?(\d+|I{1,3}|IV|VI{0,3}|IX|X|PREMIUM)\b")
EXPO = ("EXPO CITY", "EXPO VALLEY", "TERRA WOODS", "TERRA GARDENS", "SIDR", "AL WAHA", "MANGROVE")


def project_group(name):
    n = (name or "").upper().replace("-", " ")
    n = PHASE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n or "UNNAMED"


def main():
    month, today = dt.date(dt.date.today().year, 1, 1), dt.date.today()
    kept, drop, scanned = [], collections.Counter(), 0
    while month <= today:
        raw = fetch_month(month)
        for r in raw:
            area = (r.get("AREA_EN") or "").strip().upper()
            if area not in AREAS:
                continue
            scanned += 1
            if r.get("PROCEDURE_EN") not in SALE_PROCEDURES:
                drop[f'{area} · procedure: {r.get("PROCEDURE_EN")}'] += 1
                continue
            ptype = PROPERTY_TYPES.get(r.get("PROP_SB_TYPE_EN"))
            if ptype is None:
                drop[f'{area} · sub-type: {r.get("PROP_SB_TYPE_EN")}'] += 1
                continue
            sqm, value = r.get("PROCEDURE_AREA") or 0, r.get("TRANS_VALUE") or 0
            ppsf = value / (sqm * 10.7639) if sqm else 0
            if not (PPSF_MIN <= ppsf <= PPSF_MAX):
                drop[f"{area} · price per sqft outside bounds"] += 1
                continue
            project = (r.get("PROJECT_EN") or "").strip()
            group = project_group(project)
            kept.append({
                "date": r["INSTANCE_DATE"][:10], "area": area, "project": project,
                "project_group": group,
                "master": ("Emaar South" if community_of(area, project) == "EMAAR SOUTH"
                           else "Expo City / Expo Living" if group.startswith(EXPO) else "Dubai South"),
                "procedure": r.get("PROCEDURE_EN"), "reg_type": r.get("IS_OFFPLAN_EN"),
                "property_type": ptype, "rooms": r.get("ROOMS_EN") or "NA",
                "sqm": sqm, "price_aed": value, "ppsf": round(ppsf, 1),
                "transaction_number": r.get("TRANSACTION_NUMBER")})
        print(f"{month:%Y-%m}  kept so far {len(kept):>6,}", flush=True)
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

    seen, unique = set(), []
    for k in kept:
        if k["transaction_number"] not in seen:
            seen.add(k["transaction_number"])
            unique.append(k)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(unique[0]))
        w.writeheader()
        w.writerows(unique)
    groups = collections.Counter(k["project_group"] for k in unique)
    report = {"pulled_at": dt.datetime.now().isoformat(timespec="seconds"),
              "areas": sorted(AREAS), "rows_in_areas": scanned, "rows_kept": len(unique),
              "kept_by_area": collections.Counter(k["area"] for k in unique),
              "kept_by_master": collections.Counter(k["master"] for k in unique),
              "dropped": dict(drop.most_common()),
              "project_groups": len(groups),
              "groups_with_30_plus_sales": sum(1 for v in groups.values() if v >= 30),
              "group_sizes": dict(groups.most_common())}
    json.dump(report, open(OUT_REPORT, "w"), indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "group_sizes"}, indent=2))


if __name__ == "__main__":
    main()
