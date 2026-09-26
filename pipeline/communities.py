"""
What counts as each community. This is a product decision, so it lives in one file.

The Dubai Land Department registry does not know "Emaar South". Its sales sit
under two registry areas — EMAAR SOUTH and Madinat Al Mataar — and Madinat Al
Mataar is mostly other developers (Azizi Venice, Hayat by Dubai South). So
Emaar South is defined by project name, and every project in those areas that
is NOT matched is reported by fetch_dld.py, so the exclusions stay visible.

Checked Sep 2026 against Emaar's own project pages:
  in   Golf Fields, Golf Trails, Golf Vale, Golf Point, Golf Links, Golf Views,
       Urbana, Greenview, Parkside, Fairway Villas, Expo Golf Villas, Grove Ridge, Vista Ridge
       (Grove Ridge + Vista Ridge were missed in the first cut — the exclusion report surfaced
       ~320 rows of them, which is why the report exists)
  out  Hayat (Dubai South's own project), Terra Woods (Expo Living), Azizi Venice
"""

COMMUNITIES = {
    "DUBAI CREEK HARBOUR": {
        # Registry name + marketing name both appear. Everything in them counts.
        "areas_all": {"DUBAI CREEK HARBOUR", "AL KHAIRAN FIRST"},
        "areas_by_project": set(),
        "project_prefixes": (),
    },
    "EMAAR SOUTH": {
        "areas_all": {"EMAAR SOUTH"},
        "areas_by_project": {"MADINAT AL MATAAR"},
        # "GREEN" covers the Expo Golf Villas phases (Greenview, Greenway, Greenridge,
        # Greenville, Greenspoint) — matched on naming pattern, ~30 rows, not checked one by one.
        "project_prefixes": ("GOLF ", "URBANA", "GREEN", "PARKSIDE", "FAIRWAY VILLAS",
                             "EXPO GOLF VILLAS", "GROVE RIDGE", "VISTA RIDGE"),
    },
}

# Market sales only. Developer bulk registrations are not buyer demand.
SALE_PROCEDURES = {"Sell - Pre registration", "Sale", "Delayed Sell", "Sale On Payment Plan"}

# DLD records townhouses as Villa — the split is not recoverable from this source.
PROPERTY_TYPES = {"Flat": "Apartment", "Villa": "Villa"}

# Price-per-sqft sanity bounds (AED). Outside = data-entry error or non-market transfer.
PPSF_MIN, PPSF_MAX = 300, 15000


def community_of(area, project):
    """Return the community name, or None if this row is outside both."""
    a = (area or "").strip().upper()
    p = (project or "").strip().upper()
    for name, rule in COMMUNITIES.items():
        if a in rule["areas_all"]:
            return name
        if a in rule["areas_by_project"] and p.startswith(rule["project_prefixes"]):
            return name
    return None


def watched_area(area):
    """True for registry areas where exclusions should be reported."""
    a = (area or "").strip().upper()
    return any(a in r["areas_all"] or a in r["areas_by_project"] for r in COMMUNITIES.values())
