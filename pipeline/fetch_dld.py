#!/usr/bin/env python3
"""
Pull real sales transactions from the Dubai Land Department open-data API and
write the two-community extract the dashboard and ask/ layer read.

    python pipeline/fetch_dld.py                  # 1 Jan this year → today
    python pipeline/fetch_dld.py --from 2026-06   # shorter window

The public endpoint serves the CURRENT CALENDAR YEAR only (checked Sep 2026: every
2023–2025 range returns an empty result, not an error). So the extract starts 1 Jan,
and year-on-year comparisons are refused downstream rather than guessed.

Outputs (all regenerated on every run — the extract is reproducible, not curated):
  dashboard/data/dld_transactions.csv   rows kept
  pipeline/extract_report.json          what was kept, dropped, and why
  pipeline/dld_area_names.txt           every registry area seen (used to refuse
                                        questions about areas this extract does not cover)

No key needed. Source: gateway.dubailand.gov.ae/open-data/transactions
(the endpoint behind dubailand.gov.ae/en/open-data/real-estate-data).
"""
import argparse, collections, csv, datetime as dt, json, os, sys, time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from communities import (community_of, watched_area, SALE_PROCEDURES,
                         PROPERTY_TYPES, PPSF_MIN, PPSF_MAX)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(ROOT, "dashboard", "data", "dld_transactions.csv")
OUT_REPORT = os.path.join(ROOT, "pipeline", "extract_report.json")
OUT_AREAS = os.path.join(ROOT, "pipeline", "dld_area_names.txt")

URL = "https://gateway.dubailand.gov.ae/open-data/transactions"
HEADERS = {"Content-Type": "application/json", "Origin": "https://dubailand.gov.ae",
           "Referer": "https://dubailand.gov.ae/"}
PAGE = 5000


def fetch_month(first):
    last = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    rows, skip = [], 0
    while True:
        body = {"P_FROM_DATE": first.strftime("%m/%d/%Y"), "P_TO_DATE": last.strftime("%m/%d/%Y"),
                "P_GROUP_ID": "1", "P_USAGE_ID": "1",            # sales · residential
                "P_IS_OFFPLAN": "", "P_IS_FREE_HOLD": "", "P_AREA_ID": "", "P_PROP_TYPE_ID": "",
                "P_TAKE": str(PAGE), "P_SKIP": str(skip), "P_SORT": "TRANSACTION_NUMBER_ASC"}
        for attempt in range(4):
            try:
                r = requests.post(URL, json=body, headers=HEADERS, timeout=180)
                page = r.json()["response"]["result"]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        rows += page
        if not page or len(rows) >= page[0]["TOTAL"]:
            return rows
        skip += PAGE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=f"{dt.date.today().year}-01")
    args = ap.parse_args()

    month = dt.date.fromisoformat(args.start + "-01")
    today = dt.date.today()
    kept, areas = [], set()
    drop = collections.Counter()
    excluded_projects = collections.Counter()   # in a watched area, not matched to a community
    scanned = 0

    while month <= today:
        raw = fetch_month(month)
        scanned += len(raw)
        for r in raw:
            areas.add((r.get("AREA_EN") or "").strip())
            comm = community_of(r.get("AREA_EN"), r.get("PROJECT_EN"))
            if comm is None:
                if watched_area(r.get("AREA_EN")):
                    excluded_projects[f'{r.get("AREA_EN")} / {(r.get("PROJECT_EN") or "?").strip()}'] += 1
                continue
            if r.get("PROCEDURE_EN") not in SALE_PROCEDURES:
                drop[f'procedure: {r.get("PROCEDURE_EN")}'] += 1
                continue
            ptype = PROPERTY_TYPES.get(r.get("PROP_SB_TYPE_EN"))
            if ptype is None:
                drop[f'property sub-type: {r.get("PROP_SB_TYPE_EN")}'] += 1
                continue
            sqm, value = r.get("PROCEDURE_AREA") or 0, r.get("TRANS_VALUE") or 0
            ppsf = value / (sqm * 10.7639) if sqm else 0
            if not (PPSF_MIN <= ppsf <= PPSF_MAX):
                drop["price per sqft outside sanity bounds"] += 1
                continue
            kept.append({"instance_date": r["INSTANCE_DATE"][:10], "area_name_en": comm,
                         "project_en": (r.get("PROJECT_EN") or "").strip(),
                         "property_type_en": ptype, "rooms_en": r.get("ROOMS_EN") or "NA",
                         "reg_type_en": r.get("IS_OFFPLAN_EN"), "procedure_area": sqm,
                         "actual_worth": value, "transaction_number": r.get("TRANSACTION_NUMBER")})
        print(f"{month:%Y-%m}  scanned {len(raw):>6,}  kept so far {len(kept):>6,}", flush=True)
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

    # The API can repeat a row across page boundaries; transaction numbers are unique.
    seen, unique = set(), []
    for k in kept:
        if k["transaction_number"] not in seen:
            seen.add(k["transaction_number"])
            unique.append(k)
    drop["duplicate transaction number"] += len(kept) - len(unique)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(unique[0]))
        w.writeheader()
        w.writerows(unique)
    with open(OUT_AREAS, "w") as f:
        f.write("\n".join(sorted(a for a in areas if a)) + "\n")
    report = {"pulled_at": dt.datetime.now().isoformat(timespec="seconds"),
              "window": [args.start, f"{today:%Y-%m}"], "rows_scanned_all_dubai": scanned,
              "rows_kept": len(unique),
              "kept_by_community": collections.Counter(k["area_name_en"] for k in unique),
              "dropped_within_communities": dict(drop.most_common()),
              "excluded_projects_in_watched_areas": dict(excluded_projects.most_common())}
    with open(OUT_REPORT, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "excluded_projects_in_watched_areas"}, indent=2))


if __name__ == "__main__":
    main()
