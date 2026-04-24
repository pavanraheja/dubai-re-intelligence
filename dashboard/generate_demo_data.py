"""
Generates realistic demo data for Emaar South & Creek Harbour
based on actual Dubai market conditions (2020–2025).
Run once: python3 generate_demo_data.py
"""
import pandas as pd
import numpy as np
import os

np.random.seed(42)

COMMUNITIES = {
    "EMAAR SOUTH": {
        "property_types": {
            "Apartment": {
                "rooms": ["Studio", "1 B/R", "2 B/R", "3 B/R"],
                "weights": [0.15, 0.40, 0.35, 0.10],
                "sqft_range": {"Studio": (350,500), "1 B/R": (550,850), "2 B/R": (900,1350), "3 B/R": (1400,2000)},
                "ppsf_base": 900,    # AED/sqft in 2020
                "ppsf_2025": 1350,   # AED/sqft in 2025
                "offplan_ratio": 0.70,
            },
            "Townhouse": {
                "rooms": ["3 B/R", "4 B/R"],
                "weights": [0.60, 0.40],
                "sqft_range": {"3 B/R": (1800,2400), "4 B/R": (2400,3200)},
                "ppsf_base": 750,
                "ppsf_2025": 1100,
                "offplan_ratio": 0.65,
            },
            "Villa": {
                "rooms": ["4 B/R", "5 B/R"],
                "weights": [0.55, 0.45],
                "sqft_range": {"4 B/R": (3000,4500), "5 B/R": (4500,6500)},
                "ppsf_base": 700,
                "ppsf_2025": 1000,
                "offplan_ratio": 0.50,
            },
        },
        "monthly_volume": 35,
    },
    "DUBAI CREEK HARBOUR": {
        "property_types": {
            "Apartment": {
                "rooms": ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R"],
                "weights": [0.12, 0.38, 0.32, 0.12, 0.06],
                "sqft_range": {"Studio": (400,550), "1 B/R": (650,950), "2 B/R": (1000,1500), "3 B/R": (1600,2200), "4 B/R": (2500,3500)},
                "ppsf_base": 1250,
                "ppsf_2025": 2100,
                "offplan_ratio": 0.75,
            },
            "Townhouse": {
                "rooms": ["3 B/R", "4 B/R"],
                "weights": [0.55, 0.45],
                "sqft_range": {"3 B/R": (2000,2800), "4 B/R": (2800,3800)},
                "ppsf_base": 1100,
                "ppsf_2025": 1700,
                "offplan_ratio": 0.60,
            },
        },
        "monthly_volume": 55,
    },
}

# Month-by-month market multiplier (reflects real Dubai market cycles)
MARKET_CYCLE = {
    2020: [1.00,0.98,0.96,0.88,0.83,0.82,0.84,0.86,0.88,0.90,0.92,0.94],  # COVID dip
    2021: [0.95,0.97,1.00,1.04,1.07,1.10,1.13,1.16,1.20,1.24,1.28,1.32],  # Recovery
    2022: [1.35,1.38,1.42,1.46,1.50,1.54,1.57,1.60,1.63,1.65,1.67,1.69],  # Boom
    2023: [1.70,1.72,1.74,1.76,1.78,1.80,1.82,1.84,1.86,1.88,1.90,1.92],  # Sustained
    2024: [1.93,1.95,1.97,1.99,2.01,2.03,2.05,2.07,2.09,2.11,2.13,2.15],  # Continued growth
    2025: [2.16,2.18,2.20,2.22,2.24,2.26,2.28,2.30,2.32,2.34,2.36,2.38],  # 2025
}

# Volume multiplier — market got busier over time
VOL_CYCLE = {
    2020: [0.8,0.8,0.7,0.5,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1],
    2021: [1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,1.9,2.0,2.1],
    2022: [2.0,2.1,2.2,2.3,2.4,2.5,2.4,2.3,2.4,2.5,2.6,2.7],
    2023: [2.5,2.6,2.7,2.8,2.9,3.0,3.1,3.0,3.1,3.2,3.3,3.4],
    2024: [3.2,3.3,3.4,3.5,3.6,3.7,3.6,3.7,3.8,3.9,4.0,4.1],
    2025: [3.9,4.0,4.1,4.2,4.3,4.4,4.3,4.4,4.5,4.6,4.7,4.8],
}

def random_building(community, ptype):
    buildings = {
        "EMAAR SOUTH": {
            "Apartment": ["Golf Links", "Urbana", "Expo Golf Villas", "Fairway Residences",
                          "The Pulse Residence", "Greenway", "Almeria", "Mimosa",
                          "Parkside", "Mulberry Park"],
            "Townhouse": ["Urbana I", "Urbana II", "Urbana III", "The Pulse Townhouses",
                          "Greenway Townhouses", "Golf Dale"],
            "Villa":     ["Fairways Villas", "Golf Point", "Greenway Villas", "Expo Golf"],
        },
        "DUBAI CREEK HARBOUR": {
            "Apartment": ["Creek Gate", "Harbour Views", "The Cove", "Island Park",
                          "Creek Rise", "Creek Beach", "Creek Horizon", "Lotus",
                          "Orchid", "Cedar", "Grove", "Canal Front Residences",
                          "Creek Vista", "Vida Creek Harbour"],
            "Townhouse": ["Creek Waters", "Creek Waters 2", "Harbour Cove",
                          "The Cove Townhouses", "Creek Beach Townhouses"],
        }
    }
    choices = buildings.get(community, {}).get(ptype, ["Unknown"])
    return np.random.choice(choices)

records = []
for community, cfg in COMMUNITIES.items():
    for year in range(2020, 2026):
        for month in range(1, 13):
            if year == 2025 and month > 9:  # Data up to Sep 2025
                continue
            mkt_mult = MARKET_CYCLE[year][month-1]
            vol_mult  = VOL_CYCLE[year][month-1]

            for ptype, pcfg in cfg["property_types"].items():
                base_vol = max(1, int(cfg["monthly_volume"] * vol_mult * (
                    0.60 if ptype == "Apartment" else
                    0.28 if ptype == "Townhouse" else 0.12
                )))
                n = max(1, int(np.random.normal(base_vol, base_vol * 0.2)))

                for _ in range(n):
                    room = np.random.choice(pcfg["rooms"], p=pcfg["weights"])
                    sqft_min, sqft_max = pcfg["sqft_range"][room]
                    sqft = round(np.random.uniform(sqft_min, sqft_max), 0)
                    sqm  = round(sqft / 10.764, 1)

                    # Price per sqft interpolated by year + noise
                    ppsf_base = pcfg["ppsf_base"]
                    ppsf_2025 = pcfg["ppsf_2025"]
                    t = ((year - 2020) * 12 + (month - 1)) / 71  # 0→1 from Jan2020 to Dec2025
                    ppsf = ppsf_base + (ppsf_2025 - ppsf_base) * t
                    ppsf *= mkt_mult / mkt_mult  # already baked in above
                    ppsf *= np.random.normal(1.0, 0.06)
                    ppsf = max(400, round(ppsf, 0))

                    price = round(ppsf * sqft, 0)
                    ppsm  = round(ppsf * 10.764, 0)

                    is_offplan = np.random.random() < pcfg["offplan_ratio"]
                    reg_type   = "Off-Plan" if is_offplan else "Ready"

                    day = np.random.randint(1, 28)
                    date = f"{year}-{month:02d}-{day:02d}"

                    records.append({
                        "instance_date":       date,
                        "area_name_en":        community,
                        "property_type_en":    ptype,
                        "property_sub_type_en": ptype,
                        "rooms_en":            room,
                        "reg_type_en":         reg_type,
                        "procedure_area":      sqm,
                        "actual_worth":        price,
                        "meter_sale_price":    ppsm,
                        "building_name_en":    random_building(community, ptype),
                        "trans_group_en":      "Sales",
                        "nearest_metro_en":    "UAE Exchange" if community == "EMAAR SOUTH" else "Creek",
                        "nearest_mall_en":     "The Beach" if "CREEK" in community else "Dubai Hills Mall",
                    })

df = pd.DataFrame(records)
df["sqft"] = (df["procedure_area"] * 10.764).round(0)
df["ppsf"] = (df["actual_worth"] / df["sqft"]).round(0)
df["instance_date"] = pd.to_datetime(df["instance_date"])

out = "/Users/macbook/Downloads/Content Projects/04 - Dubai RE Dashboard/data/dld_demo.csv"
df.to_csv(out, index=False)
print(f"Generated {len(df):,} transactions → {out}")
print(df.groupby(["area_name_en","property_type_en"]).size().to_string())
