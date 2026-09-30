#!/usr/bin/env python3
"""
Web front for ask/ — one page, one endpoint.

    python api/index.py            # http://localhost:8090
    GET /api/ask?q=...             # the same JSON as `python ask.py --json`

Also the Vercel entry point (see vercel.json). No API key: rules planner only,
so a public link can never spend money or leak a key.
"""
import os, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from flask import Flask, jsonify, request, Response  # noqa: E402
from ask.agent import ask  # noqa: E402
from ask import tools  # noqa: E402

app = Flask(__name__)
EVAL_SUMMARY = os.path.join(ROOT, "evals", "summary.json")


def as_json(a):
    return {"question": a["question"], "planner": a["planner"],
            "scope_refusals": a["scope_refusals"],
            "results": [{"tool": n, "data": d,
                         "evidence": {"rows": e.rows, "confidence": e.confidence,
                                      "window": [str(w.date()) for w in e.window] if e.window else None,
                                      "source": e.source, "caveats": e.caveats,
                                      "refusals": e.refusals}}
                        for n, d, e in a["results"]]}


@app.get("/api/ask")
def api_ask():
    q = (request.args.get("q") or "").strip()[:300]
    if not q:
        return jsonify({"error": "empty question"}), 400
    a = ask(q, planner="rules")
    # One structured line per question for insights/review.py. The question and what the
    # tool did with it — no IP, no headers, nothing that identifies the visitor.
    print(json.dumps({"event": "ask", "q": q, "tools": [n for n, _, _ in a["results"]],
                      "refused": [r.split(" — ")[0] for r in a["scope_refusals"]],
                      "confidence": [e.confidence for _, _, e in a["results"]]}), flush=True)
    return Response(json.dumps(as_json(a), default=str), mimetype="application/json")


def _clean(o):
    """numpy / NaN → plain JSON (the browser's JSON.parse rejects NaN)."""
    import math
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item"):
        o = o.item()
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


@app.get("/api/decide")
def api_decide():
    from decide.engine import run, CRITERIA, PRESETS
    a = request.args
    weights = {c: float(a[f"w_{c}"]) for c in CRITERIA if a.get(f"w_{c}")}
    weights = {c: v for c, v in weights.items() if v > 0} or None
    budget = (float(a.get("budget_min", 1_000_000)), float(a.get("budget_max", 2_500_000)))
    preset = a.get("preset", "demand_first") if a.get("preset") in PRESETS else "demand_first"
    r = run(preset, weights, budget, a.get("stage", "all"), a.get("expo", "1") == "1")
    print(json.dumps({"event": "decide", "preset": r["frame"]["preset"], "weights": r["frame"]["weights"],
                      "budget": list(budget), "stage": r["frame"]["stage"]}), flush=True)
    return Response(json.dumps(_clean(r)), mimetype="application/json")


@app.get("/api/decide/meta")
def api_decide_meta():
    from decide.engine import CRITERIA, PRESETS
    return jsonify({"criteria": CRITERIA, "presets": PRESETS})


@app.post("/api/converse")
def api_converse():
    from decide.converse import converse
    body = request.get_json(silent=True) or {}
    msg = str(body.get("message", ""))[:500]
    if not msg.strip():
        return jsonify({"error": "empty message"}), 400
    state, brief = converse(msg, body.get("state") or {}, body.get("previous"))
    # same logging rule as /api/ask: the words and what the tool did, nothing identifying
    print(json.dumps({"event": "converse", "q": msg, "frame": state.get("frame"),
                      "priorities": state.get("priorities"), "status": brief.get("status"),
                      "leader": (brief.get("leader") or {}).get("project"), "writer": brief.get("writer")}), flush=True)
    return Response(json.dumps(_clean({"state": state, "brief": brief})), mimetype="application/json")


@app.get("/decide")
def decide_page():
    return Response(open(os.path.join(ROOT, "api", "decide.html")).read(), mimetype="text/html")


@app.get("/decide/evidence")
def evidence_page():
    return Response(open(os.path.join(ROOT, "api", "evidence.html")).read(), mimetype="text/html")


@app.get("/api/meta")
def api_meta():
    cov, _ = tools.data_coverage()
    _, source = tools.load()
    meta = {"rows": cov["rows"], "from": cov["from"], "to": cov["to"], "source": source}
    if os.path.exists(EVAL_SUMMARY):
        meta["eval"] = json.load(open(EVAL_SUMMARY))
    return jsonify(meta)


@app.get("/")
def page():
    return Response(open(os.path.join(ROOT, "api", "page.html")).read(), mimetype="text/html")


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 8090)))
