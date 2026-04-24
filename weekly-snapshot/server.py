"""
Dubai RE Weekly Snapshot — Dynamic Server
Port : 9081  (Content Projects series: 9081–9089)
Auto : Scrapes new DLD data every Monday at 09:00 UAE time (05:00 UTC)
"""

import json, os, re, logging, threading
from datetime import datetime, timezone, timedelta
from flask import Flask, send_file, jsonify, request
import requests as req

# ── paths ──────────────────────────────────────────────────────────────────
BASE   = os.path.dirname(os.path.abspath(__file__))
DATA   = os.path.join(BASE, "data.json")
HTML   = os.path.join(BASE, "index.html")
PORT   = 9081

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── data helpers ───────────────────────────────────────────────────────────
def load_data():
    with open(DATA) as f:
        return json.load(f)

def save_data(d):
    d["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(DATA, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

# ── scraper ────────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def scrape_edwards():
    """Scrape Edwards & Towers weekly rundown for latest figures."""
    try:
        r = req.get("https://edwardsandtowers.com/dubai-real-estate-weekly-rundown/",
                    headers=HEADERS, timeout=15)
        text = r.text
        # Look for AED X.XX billion pattern
        val_match  = re.search(r'AED\s+([\d,\.]+)\s*[Bb]illion', text)
        deal_match = re.search(r'([\d,]+)\s+(?:transactions?|deals?)', text)
        date_match = re.search(r'(\w+ \d+\s*[-–]\s*\d+,?\s*202\d)', text)
        if val_match and deal_match:
            value = float(val_match.group(1).replace(",", ""))
            deals = int(deal_match.group(1).replace(",", ""))
            dates = date_match.group(1).strip() if date_match else "Latest week"
            log.info(f"Edwards scrape: AED {value}B, {deals} deals, {dates}")
            return {"value_aed_b": value, "deals": deals, "dates": dates,
                    "source": "Edwards & Towers — DLD"}
    except Exception as e:
        log.warning(f"Edwards scrape failed: {e}")
    return None

def scrape_voice_of_emirates():
    """Scrape Voice of Emirates for latest weekly DLD article."""
    try:
        r = req.get("https://www.voiceofemirates.com/en/category/business/",
                    headers=HEADERS, timeout=15)
        text = r.text
        # Find article links about real estate transactions
        links = re.findall(r'href="(https://www\.voiceofemirates\.com/en/business/202\d/\d+/\d+/[^"]*real-estate[^"]*)"', text)
        for link in links[:5]:
            try:
                art = req.get(link, headers=HEADERS, timeout=15)
                atext = art.text
                val_m  = re.search(r'AED\s+([\d,\.]+)\s*[Bb]illion', atext)
                deal_m = re.search(r'([\d,]+)\s+(?:transactions?|deals?)', atext)
                date_m = re.search(r'(\w+ \d+\s*[-–]\s*\d+,?\s*202\d)', atext)
                if val_m and deal_m:
                    value = float(val_m.group(1).replace(",", ""))
                    deals = int(deal_m.group(1).replace(",", ""))
                    dates = date_m.group(1).strip() if date_m else "Latest week"
                    log.info(f"VoE scrape: AED {value}B, {deals} deals — {link}")
                    return {"value_aed_b": value, "deals": deals, "dates": dates,
                            "source": f"Voice of Emirates — DLD"}
            except Exception:
                continue
    except Exception as e:
        log.warning(f"VoE scrape failed: {e}")
    return None

def auto_refresh():
    """Try all sources, add new week if data differs from current latest."""
    log.info("Monday auto-refresh — scraping DLD data...")
    result = scrape_edwards() or scrape_voice_of_emirates()
    if not result:
        log.warning("Auto-refresh: no new data found from any source.")
        return

    data   = load_data()
    latest = data["weeks"][-1]

    # Only update if value or deals differ (new week published)
    if (abs(result["value_aed_b"] - latest["value_aed_b"]) > 0.05
            or abs(result["deals"] - latest["deals"]) > 50):
        new_week = {
            "dates":       result["dates"],
            "value_aed_b": result["value_aed_b"],
            "deals":       result["deals"],
            "offplan":     "~68%",
            "label":       "",
            "source":      result["source"]
        }
        data["weeks"].append(new_week)
        data["weeks"] = data["weeks"][-3:]   # keep only last 3 weeks
        data["pending_note"] = ""
        save_data(data)
        log.info(f"Auto-refresh: new week added — AED {new_week['value_aed_b']}B, {new_week['deals']} deals")
    else:
        log.info("Auto-refresh: no new week detected (same data as current latest).")

# ── Monday scheduler ───────────────────────────────────────────────────────
def scheduler_loop():
    """Runs in background — fires auto_refresh every Monday at 09:00 UAE (UTC+4)."""
    UAE = timezone(timedelta(hours=4))
    while True:
        now = datetime.now(UAE)
        # Monday = 0, target 09:00
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_monday = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.weekday() != 0 or now.hour >= 9:
            next_monday += timedelta(days=days_until_monday)
        wait = (next_monday - now).total_seconds()
        log.info(f"Next auto-refresh: {next_monday.strftime('%a %b %d %Y %H:%M')} UAE — {wait/3600:.1f}h away")
        threading.Event().wait(wait)
        auto_refresh()

# ── routes ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_file(HTML)

@app.route("/api/data")
def api_data():
    return jsonify(load_data())

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Manual trigger — POST /api/refresh"""
    threading.Thread(target=auto_refresh, daemon=True).start()
    return jsonify({"status": "refresh started"})

@app.route("/api/save", methods=["POST"])
def api_save():
    """Save edited week data from the dashboard."""
    body = request.get_json()
    data = load_data()
    data["weeks"] = body.get("weeks", data["weeks"])
    if "pending_note" in body:
        data["pending_note"] = body["pending_note"]
    save_data(data)
    return jsonify({"status": "saved"})

# ── main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=scheduler_loop, daemon=True).start()
    log.info(f"Dubai RE Weekly Snapshot — http://localhost:{PORT}")
    log.info(f"Manual refresh: POST http://localhost:{PORT}/api/refresh")
    app.run(host="0.0.0.0", port=PORT, debug=False)
