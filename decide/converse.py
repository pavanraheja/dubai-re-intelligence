"""
Conversation layer for the decision workbench.

Turns what a decision-maker says ("I have 4-5M, want to exit in 3 years, leave Expo out")
into a frame and priorities, runs the engine, and writes a brief. The rule from the rest of
the product holds: words can be generated, numbers cannot. Every number in a reply is taken
from the engine's output; test_converse.py checks that, and the optional Claude narrator is
held to the same check, falling back to the template when it fails.
"""
import json, os, re
from decide.engine import run, PRESETS, CRITERIA
from ask import evidence

DEFAULT_BUDGET = [1_000_000, 2_500_000]
PRIORITY_WORDS = {
    "exit": ("exit", "sell later", "resell", "resale", "liquid", "flip", "get out", "able to sell",
             "sell in", "sell within", "sell it in", "selling in", "cash out"),
    "growth": ("growth", "apprecia", "capital gain", "upside", "grow", "price rise"),
    "value": ("value", "cheap", "bargain", "discount", "entry price", "affordable", "undervalued"),
    "safety": ("safe", "stable", "low risk", "lower risk", "defensive", "conservative"),
    "demand": ("demand", "popular", "selling well", "sells"),
}
PRIORITY_WEIGHTS = {
    "exit": {"demand": .30, "persistence": .20, "resale": .30, "stability": .20},
    "growth": PRESETS["growth"]["weights"],
    "value": PRESETS["value"]["weights"],
    "safety": {"persistence": .35, "stability": .35, "depth": .30},
    "demand": PRESETS["demand_first"]["weights"],
}
PRIORITY_LABEL = {"exit": "being able to sell later", "growth": "capital growth", "value": "entry value",
                  "safety": "stability", "demand": "buyer demand"}
LABEL = {"demand": "recent demand", "persistence": "steady demand", "depth": "market depth",
         "stability": "consistent prices", "momentum": "reliable price growth", "value": "entry value",
         "resale": "resale evidence"}


# ── numbers: one formatter, so the check and the text agree ──────────────
def m(v):          # AED millions, two decimals at most
    return f"{round(v / 1e6, 2):g}M"


def pct(v):        # shares 0–1 → "48.5%"
    return f"{round(v * 100, 1):g}%"


def _signed(v):    # "+5.4%", "-0.5%", "0%"
    return "0%" if v == 0 else f"{v:+g}%"


def num(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:g}"


# ── understanding ────────────────────────────────────────────────────────
def _amount(x, unit):
    x = float(x.replace(",", ""))
    unit = (unit or "").lower()
    if unit.startswith("k"):
        return x * 1e3
    if x >= 10_000:        # written out in AED
        return x
    return x * 1e6         # "4", "4m", "4 mil", "4 million"


def parse_budget(q):
    q = q.lower().replace("–", "-").replace("aed", " ")
    U = r"\s*(k|m|mn|mil|million|millions)?\b"
    n = r"(\d[\d,]*(?:\.\d+)?)"
    r = re.search(n + U + r"\s*(?:-|to|and)\s*" + n + U, q)
    if r and not re.search(r"^\s*(year|yr|month|bed|br)", q[r.end():]):
        unit = r.group(4) or r.group(2)
        return [_amount(r.group(1), unit), _amount(r.group(3), unit)]
    r = re.search(r"(?:under|below|up to|upto|max(?:imum)?|less than|within)\s*" + n + U, q)
    if r:
        return [0, _amount(r.group(1), r.group(2))]
    r = re.search(r"(?:over|above|at least|min(?:imum)?|more than|from)\s*" + n + U, q)
    if r and (r.group(2) or "m" in q[r.end():r.end() + 2]):
        return [_amount(r.group(1), r.group(2)), 50e6]
    r = re.search(r"(?:around|about|roughly|budget(?: of| is)?)\s*" + n + U, q)
    if r:
        a = _amount(r.group(1), r.group(2))
        return [a * .8, a * 1.2]
    return None


def parse(message, state):
    """Update the frame from one message. Returns (state, intent, notes)."""
    q = message.lower().strip()
    st = json.loads(json.dumps(state or {}))
    st.setdefault("frame", {"budget": DEFAULT_BUDGET, "stage": "all", "include_expo": True})
    st.setdefault("priorities", [])
    notes, intent = [], "brief"

    if re.search(r"\b(reset|start over|clear)\b", q):
        return {"frame": {"budget": DEFAULT_BUDGET, "stage": "all", "include_expo": True}, "priorities": []}, "reset", []
    b = parse_budget(q)
    if b:
        st["frame"]["budget"] = sorted(b)
    if re.search(r"\b(no|exclude|without|leave out|drop|not)\b[^.]{0,20}\bexpo\b|\bexpo\b[^.]{0,12}\b(out|excluded)\b", q):
        st["frame"]["include_expo"] = False
    elif re.search(r"\b(include|with|add|allow)\b[^.]{0,12}\bexpo\b", q):
        st["frame"]["include_expo"] = True
    if re.search(r"\b(off[- ]?plan only|only off[- ]?plan)\b", q):
        st["frame"]["stage"] = "offplan"
    elif re.search(r"\b(ready only|only ready|ready to move|move in|completed|handed over)\b", q):
        st["frame"]["stage"] = "ready"
    elif re.search(r"\b(any stage|both stages|off[- ]?plan (and|or) ready)\b", q):
        st["frame"]["stage"] = "all"

    found = [p for p, words in PRIORITY_WORDS.items() if any(w in q for w in words)]
    if found:
        adding = re.search(r"\b(also|and also|too|as well|plus)\b", q)
        st["priorities"] = sorted(set(st["priorities"]) | set(found)) if adding else found

    if re.search(r"\bcompare\b|\bvs\.?\b|\bversus\b|head[- ]to[- ]head|side by side", q):
        intent = "compare"
    elif re.search(r"\b(memo|write it up|write up|document the decision)\b", q):
        intent = "memo"
    elif re.search(r"^(why|tell me about|what about|more on|details? (on|for))\b", q):
        intent = "project"

    # the evidence contract still applies to anything asked here
    for r in evidence.scope_refusals(message):
        if r.startswith(("forward-looking", "causal")) or "out of scope" in r or r.startswith("supply"):
            notes.append(r)
    if re.search(r"\b(yield|rent)", q):
        notes.append("rental yield is not in sales records; it stays on the verify list")
    return st, intent, notes


def weights_for(priorities):
    ps = priorities or ["demand"]
    w = {}
    for p in ps:
        for k, v in PRIORITY_WEIGHTS[p].items():
            w[k] = w.get(k, 0) + v / len(ps)
    return w


# ── the brief: structured facts first, text built only from them ─────────
def _status(holds):
    return "settled" if holds >= .8 else ("leaning" if holds >= .6 else "contested")


def _strong(o, c, opts):
    """True if the project is in the top 40% of the options on criterion c."""
    vals = [x[c] for x in opts if x.get(c) is not None]
    if o.get(c) is None or len(vals) < 2:
        return False
    better = sum(1 for v in vals if (v < o[c] if c == "value" else v > o[c]))
    worse = sum(1 for v in vals if (v > o[c] if c == "value" else v < o[c]))
    return worse >= 1 and better / len(vals) <= .4      # a tie at the bottom is not a strength


def _why(o, w, opts=None):
    """Up to three weighted criteria the project is genuinely strong on, with raw numbers.
    A criterion it is weak on is never offered as a reason."""
    raw = {"demand": f"{num(o['demand'])} sales a month recently",
           "persistence": f"{pct(o['persistence'])} of its sales outside its busiest month",
           "depth": f"{num(o['sales'])} sales this year",
           "stability": f"prices within a tight range ({pct(o['stability'])} consistency)",
           "momentum": (f"price per sqft {_signed(o['momentum_point'])} from Q1 to Q3"
                        if o.get("momentum_point") is not None else None),
           "value": f"AED {num(o['median_ppsf'])} per sqft",
           "resale": f"{pct(o['resale'])} of its sales are resales or ready sales"}
    ranked = sorted((c for c in w if raw.get(c) and (opts is None or _strong(o, c, opts))), key=lambda c: -w[c])
    return [raw[c] for c in ranked[:3]]


def _tradeoffs(o):
    t = []
    if o["in_budget_share"] < .5:
        t.append(f"only {pct(o['in_budget_share'])} of its sales fall inside your budget")
    if o["resale"] < .05:
        t.append("almost no resales yet, so how easily it resells is unknown")
    if o["offplan_share"] >= .95:
        t.append("off-plan only: prices are the developer's launch prices")
    ci = o.get("momentum_ci")
    if ci and ci[1] < 0:
        t.append(f"price per sqft fell clearly ({ci[0]:g}% to {ci[1]:g}%): price cuts or a shift to larger units")
    elif ci and ci[0] > 0:
        t.append("its price rise may partly be the developer raising prices between phases")
    if o["launch_burst"]:
        t.append("most sales came in one launch month")
    return t


def _find(options, q):
    q = q.lower()
    hits = [o for o in options if o["project"].lower() in q or
            any(len(t) > 3 and t in q for t in o["project"].lower().split())]
    return hits


def brief(message, state, previous=None):
    st, intent, notes = parse(message, state)
    f = st["frame"]
    w = weights_for(st["priorities"])
    r = run(weights=w, budget=tuple(f["budget"]), stage=f["stage"], include_expo=f["include_expo"])
    opts = r["options"]
    b = {"frame": {"budget": [m(f["budget"][0]), m(f["budget"][1])], "stage": f["stage"],
                   "include_expo": f["include_expo"],
                   "priorities": [PRIORITY_LABEL[p] for p in (st["priorities"] or ["demand"])],
                   "assumed_priority": not st["priorities"]},
         "count": len(opts), "notes": notes, "warnings": r["warnings"], "intent": intent,
         "basis": r["basis"], "weights": r["frame"]["weights"]}
    if not opts:
        b["status"] = "none"
        return st, b, r
    lead = opts[0]
    holds = r["stress"]["leader_holds"]
    b.update({
        "status": _status(holds), "holds": pct(holds),
        "leader": {"project": lead["project"].title(), "why": _why(lead, w, opts), "tradeoffs": _tradeoffs(lead)},
        "runner_up": ({"project": opts[1]["project"].title(), "first_in": pct(opts[1]["p_first"])}
                      if len(opts) > 1 else None),
        "finalists": [{"project": o["project"].title(), "master": o["master"], "first_in": pct(o["p_first"]),
                       "demand": num(o["demand"]), "sales": num(o["sales"]), "median_price": m(o["median_price"]),
                       "ppsf": num(o["median_ppsf"]),
                       "momentum": None if o.get("momentum_point") is None else _signed(o["momentum_point"]),
                       "resale": pct(o["resale"]), "in_budget": pct(o["in_budget_share"]),
                       "confidence": o["confidence"]} for o in opts[:3]],
        "flips": [{"criterion": LABEL[x["criterion"]], "change": "halved" if x["factor"] < 1 else "raised by half",
                   "new_leader": x["new_leader"].title()} for x in r["stress"]["flips"][:3]],
        "verify": (lead["gaps"][:1] if lead["launch_burst"] else []) + r["global_gaps"][:4],
    })
    # the exit case: the one project with resale evidence may not lead, but it must be named
    if "exit" in st["priorities"]:
        best_resale = max(opts, key=lambda o: o["resale"])
        if best_resale["project"] != lead["project"] and best_resale["resale"] >= .3:
            b["exit_note"] = {"project": best_resale["project"].title(), "resale": pct(best_resale["resale"])}
    if previous and previous.get("frame"):
        pf, nf = previous["frame"], b["frame"]
        diff = []
        if pf.get("budget") != nf["budget"]:
            diff.append(f"budget AED {nf['budget'][0]} to {nf['budget'][1]}")
        if pf.get("stage") != nf["stage"]:
            diff.append({"offplan": "off-plan only", "ready": "ready only"}.get(nf["stage"], "any stage"))
        if pf.get("include_expo") != nf["include_expo"]:
            diff.append(f"Expo City {'in' if nf['include_expo'] else 'out'}")
        if pf.get("priorities") != nf["priorities"]:
            diff.append("priority " + " and ".join(nf["priorities"]))
        b["frame_changes"] = diff
    if previous and previous.get("leader"):
        b["changed"] = {"before": previous["leader"], "before_holds": previous.get("holds"),
                        "leader_changed": previous["leader"] != b["leader"]["project"]}
    if intent == "compare":
        picked = _find(opts, message)
        pair = picked[:2] if len(picked) >= 2 else opts[:2]
        b["compare"] = [{"project": o["project"].title(), "first_in": pct(o["p_first"]),
                         "rows": {LABEL[c]: v for c, v in zip(
                             ["demand", "persistence", "depth", "stability", "momentum", "value", "resale"],
                             [f"{num(o['demand'])}/mo", pct(o["persistence"]), num(o["sales"]), pct(o["stability"]),
                              "n/a" if o.get("momentum_point") is None else _signed(o["momentum_point"]),
                              f"AED {num(o['median_ppsf'])}/sqft", pct(o["resale"])])}} for o in pair]
    if intent == "project":
        hit = _find(opts, message)
        if hit:
            o = hit[0]
            b["project"] = {"project": o["project"].title(), "why": _why(o, {c: 1 for c in LABEL}, opts),
                            "tradeoffs": _tradeoffs(o), "first_in": pct(o["p_first"]), "rank": opts.index(o) + 1}
    b["suggestions"] = _suggest(b, st)
    return st, b, r


def _suggest(b, st):
    s = []
    if "growth" not in st["priorities"]:
        s.append("What if growth matters more?")
    if "exit" not in st["priorities"]:
        s.append("I need to be able to sell in 3 years")
    if b.get("runner_up"):
        s.append(f"Compare {b['leader']['project']} and {b['runner_up']['project']}")
    s.append("Leave Expo out" if st["frame"]["include_expo"] else "Include Expo City")
    s.append("Write the memo")
    return s[:4]


# ── the reply, built only from the brief ─────────────────────────────────
def template_reply(b):
    f = b["frame"]
    lines = []
    for n in b["notes"]:
        lines.append(f"Before anything else: {n}.")
    frame = (f"AED {f['budget'][0]} to {f['budget'][1]}, "
             f"{'off-plan only' if f['stage'] == 'offplan' else 'ready only' if f['stage'] == 'ready' else 'any stage'}, "
             f"Expo City {'in' if f['include_expo'] else 'out'}")
    pri = " and ".join(f["priorities"])
    if b.get("frame_changes") is not None:
        lines.append(("Changed: " + ", ".join(b["frame_changes"]) + ".") if b["frame_changes"]
                     else "Same frame as before.")
    else:
      lines.append(f"Frame: {frame}. Priority: {pri}" +
                   (" (my default; tell me if growth, value or being able to sell later matters more)." if f["assumed_priority"] else "."))
    if b["status"] == "none":
        lines.append("No project passes this frame. Widen the budget or the stage.")
        return " ".join(lines)
    L = b["leader"]
    if b["count"] <= 3:
        lines.append(f"Only {b['count']} projects fit.")
    word = {"settled": "The data settles it", "leaning": "The data leans one way",
            "contested": "The data does not settle it"}[b["status"]]
    lines.append(f"{word}: {L['project']} comes first in {b['holds']} of 2,000 scenarios.")
    if b["status"] != "settled" and b.get("runner_up"):
        lines.append(f"{b['runner_up']['project']} comes first in {b['runner_up']['first_in']}, a real alternative.")
    if L["tradeoffs"]:
        lines.append(f"Main trade-off: {L['tradeoffs'][0]}.")
    if b.get("exit_note"):
        e = b["exit_note"]
        lines.append(f"If selling later matters most, {e['project']} is the one option with resale evidence "
                     f"({e['resale']} of its sales).")
    ch = b.get("changed")
    if ch:
        lines.append(f"Compared with before: the leader changed from {ch['before']}." if ch["leader_changed"]
                     else f"Compared with before: {ch['before']} still leads.")
    if b.get("project"):
        p = b["project"]
        lines.append(f"{p['project']} ranks #{p['rank']} and comes first in {p['first_in']} of scenarios; details in the brief.")
    if b.get("compare"):
        lines.append("The head-to-head is in the brief.")
    lines.append("I don't pick: the brief has the why, the trade-offs and what to verify.")
    return " ".join(lines)


def numbers_in(text):
    return set(re.findall(r"\d[\d,]*(?:\.\d+)?", text))


def allowed_numbers(b):
    """Every number the reply may contain: the brief itself, serialised."""
    return numbers_in(json.dumps(b)) | {"2,000", "2000", "3"}


def llm_reply(b):
    """Optional: Claude writes the brief in plain language. Held to the same rule as the
    template: any number not in the brief → discard and use the template."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(
            model="claude-opus-5", max_tokens=700,
            system=("You write a short decision brief for an investment committee from JSON facts. "
                    "Use ONLY numbers that appear in the facts, written exactly as they appear. Never recommend or "
                    "pick a project; say how settled the ranking is, why the leader leads, the trade-offs, and what "
                    "to verify. Plain, calm, under 150 words."),
            messages=[{"role": "user", "content": json.dumps(b)}])
        if r.stop_reason == "refusal":
            return None
        text = "".join(x.text for x in r.content if x.type == "text").strip()
        return text if numbers_in(text) <= allowed_numbers(b) else None
    except Exception:
        return None


def converse(message, state=None, previous=None):
    st, b, _ = brief(message, state or {}, previous)
    text = llm_reply(b)
    b["writer"] = "claude" if text else "template"
    b["reply"] = text or template_reply(b)
    return st, b
