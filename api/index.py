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
    return Response(json.dumps(as_json(ask(q, planner="rules")), default=str),
                    mimetype="application/json")


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
