#!/usr/bin/env python3
"""
The learning loop: read what people actually asked, find where the product failed
them, and turn it into roadmap evidence and proposed eval questions.

    python insights/review.py                 # pull recent production logs from Vercel
    python insights/review.py --file logs.jsonl

What it does, in order:
  1. Archive every question it sees (insights/data/questions.jsonl). Vercel keeps
     logs for a short time only; the archive is what makes this cumulative.
  2. Replay each question against the CURRENT code, so the report shows what a
     visitor saw then and what they would see now.
  3. Flag rephrase chains: a typed question followed within 2 minutes by another
     that shares a word. People rephrase when the answer missed. This is the
     signal that caught the pooled-trend bug on 28 Sep.
  4. Count refusals by category and map them to roadmap items. A refusal is
     correct behaviour, and also demand for data the product does not have.
  5. Propose every new typed question as an eval candidate, labelled with what
     the tool does now, for a human to confirm or correct.

What it deliberately does NOT do: change any rule, threshold or eval label by
itself. A public text box that rewrote its own rules could be steered by anyone
typing into it. The loop proposes; a person approves.
"""
import argparse, datetime as dt, json, os, re, subprocess, sys, urllib.parse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ask.agent import ask  # noqa: E402

DATA = os.path.join(ROOT, "insights", "data")
ARCHIVE = os.path.join(DATA, "questions.jsonl")
REPORTS = os.path.join(ROOT, "insights", "reports")
EVAL_FILES = [os.path.join(ROOT, "evals", f) for f in
              ("questions_v1.jsonl", "questions_independent_v1.jsonl", "questions_everyday_v1.jsonl")]

REPHRASE_SECONDS = 120
SESSION_GAP_MINUTES = 30
STOP = set("the a an in of on for to is are was what whats how and or vs with by me show give "
           "it this that there about do does did i my please pls".split())

# Refusal category → the roadmap item that would turn it into an answer (PRODUCT.md).
ROADMAP = {
    "supply question": "Supply data (project completions) — roadmap #3",
    "forward-looking question": "Historic data for longer trends — roadmap #2 (forecasts stay refused)",
    "causal question": "None — transactions cannot show cause; keep refusing",
    "advice question": "None — by design; keep refusing",
    "not in this extract": "Coverage: add the areas people ask for most",
    "is not in DLD sales transactions": "Second source (rents / Ejari) with its own evidence rules",
}


# ── collect ───────────────────────────────────────────────────────────────
def pull_vercel(since):
    out = subprocess.run(["vercel", "logs", "--environment", "production", "--since", since,
                          "--no-branch", "--json", "-n", "1000"],
                         cwd=ROOT, capture_output=True, text=True, timeout=180)
    return out.stdout.splitlines()


def parse(lines):
    """Log lines → {ts, q, then}. Reads both the structured 'ask' line and the plain
    access-log line, and merges them per request."""
    by_req = {}
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        msgs = [d.get("message", "")] + [l.get("message", "") for l in d.get("logs", []) or []]
        key = d.get("requestId") or d.get("id")
        rec = by_req.setdefault(key, {"ts": d.get("timestamp"), "q": None, "then": None})
        for m in msgs:
            m = (m or "").strip()
            if m.startswith("{") and '"event": "ask"' in m:
                try:
                    s = json.loads(m)
                    rec["q"], rec["then"] = s["q"], {"tools": s["tools"], "refused": s["refused"],
                                                     "confidence": s["confidence"]}
                except ValueError:
                    pass
            hit = re.search(r"GET /api/ask\?q=(\S+)", m)
            if hit and not rec["q"]:
                rec["q"] = urllib.parse.unquote(hit.group(1)).replace("+", " ")
    return [r for r in by_req.values() if r["q"] and r["ts"]]


def archive(new):
    os.makedirs(DATA, exist_ok=True)
    old = [json.loads(l) for l in open(ARCHIVE)] if os.path.exists(ARCHIVE) else []
    seen = {(r["ts"], r["q"]) for r in old}
    added = [r for r in new if (r["ts"], r["q"]) not in seen]
    with open(ARCHIVE, "a") as f:
        for r in added:
            f.write(json.dumps(r) + "\n")
    return sorted(old + added, key=lambda r: r["ts"]), len(added)


# ── analyse ───────────────────────────────────────────────────────────────
# Example buttons from earlier versions of the page — clicks on these are not typed questions.
PAST_CHIPS = {"monthly price trend in emaar south", "split creek harbour sales by bedrooms",
              "what can this data answer?", "compare the two communities",
              "is emaar south absorbing supply faster than creek harbour?",
              "will creek harbour prices keep rising?", "should i buy in emaar south?",
              "why did creek harbour prices rise?", "what's happening in downtown dubai?"}


def example_chips():
    html = open(os.path.join(ROOT, "api", "page.html")).read()
    now = {c.strip().lower() for c in re.findall(r'<span class="chip[^"]*">([^<]+)</span>', html)}
    return now | PAST_CHIPS


def words(q):
    return {w for w in re.findall(r"[a-z0-9]+", q.lower()) if w not in STOP and len(w) > 2}


def now_outcome(q):
    a = ask(q, planner="rules")
    tools = [n for n, _, _ in a["results"]]
    return {"tools": tools, "refused": [r.split(" — ")[0] for r in a["scope_refusals"]],
            "confidence": [e.confidence for _, _, e in a["results"]],
            "fell_through": tools == ["compare_communities", "data_coverage"] and not a["scope_refusals"]}


def label(o):
    if o is None:
        return "not logged"
    if o["refused"]:
        return "refused: " + ", ".join(o["refused"])
    return " + ".join(o["tools"]) + (" (fallback)" if o.get("fell_through") else "")


def analyse(rows):
    chips = example_chips()
    known = {json.loads(l)["q"].strip().lower() for f in EVAL_FILES if os.path.exists(f)
             for l in open(f) if l.strip()}
    for r in rows:
        r["typed"] = r["q"].strip().lower() not in chips
        r["now"] = now_outcome(r["q"])

    sessions, cur = [], []
    for r in rows:
        if cur and (r["ts"] - cur[-1]["ts"]) / 60000 > SESSION_GAP_MINUTES:
            sessions.append(cur)
            cur = []
        cur.append(r)
    if cur:
        sessions.append(cur)

    chains = []
    for s in sessions:
        typed = [r for r in s if r["typed"]]
        chain = []
        for prev, nxt in zip(typed, typed[1:]):
            same = prev["q"].strip().lower() == nxt["q"].strip().lower()
            if (not same and (nxt["ts"] - prev["ts"]) / 1000 <= REPHRASE_SECONDS
                    and words(prev["q"]) & words(nxt["q"])):
                chain = chain or [prev]
                chain.append(nxt)
            elif chain:
                chains.append(chain)
                chain = []
        if chain:
            chains.append(chain)

    refusal_demand = Counter()
    for r in rows:
        for ref in r["now"]["refused"]:
            key = next((k for k in ROADMAP if k in ref), ref)
            refusal_demand[key] += 1
    candidates, seen = [], set()
    for r in rows:
        k = r["q"].strip().lower()
        if r["typed"] and k not in known and k not in seen:
            seen.add(k)
            candidates.append(r)
    fallbacks = [r for r in rows if r["now"]["fell_through"]]
    return sessions, chains, refusal_demand, candidates, fallbacks


# ── report ────────────────────────────────────────────────────────────────
def when(ts):
    return dt.datetime.fromtimestamp(ts / 1000).strftime("%d %b %H:%M:%S")


def report(rows, added, sessions, chains, demand, candidates, fallbacks):
    typed = [r for r in rows if r["typed"]]
    out = [f"# Question log review — {dt.date.today():%d %b %Y}", "",
           f"**{len(rows)} questions** in {len(sessions)} session(s) · {len(typed)} typed, "
           f"{len(rows) - len(typed)} example clicks · {added} new since last run", ""]

    out += ["## 1. Where people rephrased (the answer probably missed)", ""]
    if not chains:
        out.append("No rephrase chains.")
    for c in chains:
        out.append(f"**Chain at {when(c[0]['ts'])}** — {len(c)} questions in "
                   f"{(c[-1]['ts'] - c[0]['ts']) / 1000:.0f}s")
        out += ["", "| Asked | Then | Now |", "|---|---|---|"]
        out += [f"| {r['q']} | {label(r['then'])} | {label(r['now'])} |" for r in c]
        out.append("")

    out += ["## 2. Refusals, read as demand", "",
            "A refusal is correct behaviour. It is also a count of people asking for data the "
            "product does not have. This is the roadmap signal.", "",
            "| Refusal | Count | Roadmap item it points to |", "|---|---|---|"]
    out += [f"| {k} | {v} | {ROADMAP.get(k, '—')} |" for k, v in demand.most_common()] or ["| none | 0 | |"]

    out += ["", "## 3. Questions the planner did not recognise", ""]
    out += [f"- {r['q']} ({when(r['ts'])}) — fell back to the generic comparison" for r in fallbacks] \
        or ["None: every question reached a specific tool or a refusal."]

    out += ["", "## 4. Proposed eval questions (need a human label)", "",
            f"{len(candidates)} typed question(s) not yet in any eval set, written to "
            "`insights/data/candidates.jsonl` with the current behaviour as a *suggested* label. "
            "Confirm or correct each, then add it to `evals/`. Nothing is added automatically.", ""]
    out += [f"- {r['q']} → suggested `{('refuse' if r['now']['refused'] else 'answer')}:"
            f"{(r['now']['refused'] or r['now']['tools'])[0]}`" for r in candidates]

    changed = [r for r in rows if r["then"] and label(r["then"]) != label(r["now"])]
    out += ["", "## 5. Answers that changed since they were asked", ""]
    out += [f"- {r['q']}: {label(r['then'])} → {label(r['now'])}" for r in changed] \
        or ["None (or the questions were logged before outcomes were recorded)."]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Vercel logs as JSON lines, instead of pulling live")
    ap.add_argument("--since", default="24h")
    ap.add_argument("--out", help="report path (default insights/reports/<date>.md)")
    args = ap.parse_args()

    lines = open(args.file).read().splitlines() if args.file else pull_vercel(args.since)
    rows, added = archive(parse(lines))
    sessions, chains, demand, candidates, fallbacks = analyse(rows)

    os.makedirs(REPORTS, exist_ok=True)
    path = args.out or os.path.join(REPORTS, f"{dt.date.today()}.md")
    open(path, "w").write(report(rows, added, sessions, chains, demand, candidates, fallbacks))
    with open(os.path.join(DATA, "candidates.jsonl"), "w") as f:
        for r in candidates:
            f.write(json.dumps({"q": r["q"], "suggested": ("refuse:" + r["now"]["refused"][0])
                                if r["now"]["refused"] else "answer:" + r["now"]["tools"][0],
                                "status": "needs human label"}) + "\n")
    print(f"{len(rows)} questions · {len(chains)} rephrase chain(s) · {len(candidates)} candidate(s) → {path}")


if __name__ == "__main__":
    main()
