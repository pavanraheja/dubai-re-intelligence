"""
The agent loop.

Two planners, same tools, same evidence rules:
  1. RULE planner (default) — no API key, no network, runs anywhere in 2 seconds.
  2. LLM planner (optional) — set ANTHROPIC_API_KEY to let Claude choose the tools.

The planner only chooses WHICH tool runs. It never produces the numbers, and it
cannot override a refusal. That separation is the point: the model is allowed to
be wrong about intent, never about evidence.
"""
import os
import re
from . import tools, evidence as ev

AREAS = {"emaar south": "EMAAR SOUTH", "emaar": "EMAAR SOUTH", "south": "EMAAR SOUTH",
         "creek harbour": "DUBAI CREEK HARBOUR", "creek": "DUBAI CREEK HARBOUR",
         "dubai creek harbour": "DUBAI CREEK HARBOUR", "dch": "DUBAI CREEK HARBOUR",
         "es": "EMAAR SOUTH"}


def _area_in(q):
    for k, v in AREAS.items():
        if re.search(rf"\b{k}\b", q):
            return v
    return None


def plan_rules(question):
    """Deterministic intent match. Returns a list of (tool_name, kwargs)."""
    q = question.lower()
    area = _area_in(q)
    months = 12
    m = re.search(r"(\d+)\s*(month|months|year|years)", q)
    if m:
        months = int(m.group(1)) * (12 if "year" in m.group(2) else 1)

    if any(w in q for w in ("what can you", "coverage", "what data", "what's in the data",
                            "can you answer", "scope", "this data", "the data actually",
                            "what is in", "limitations", "what can't", "date range",
                            "based on", "how fresh", "how recent", "come from", "source",
                            "only cover", "included in", "dataset")):
        return [("data_coverage", {})]
    rooms = re.search(r"\b(\d\s?-?\s?(bed|br|b/r)\w*|studios?|bedrooms?)\b", q)
    if rooms or any(w in q for w in ("breakdown", "break down", "segment", "split", "villa",
                                     "apartment", "townhouse", "property type",
                                     "where does the money", "trades most")):
        by = "rooms" if rooms else "property_type"
        return [("segment_breakdown", {"area": area, "by": by, "months": months})]
    if any(w in q for w in ("trend", "over time", "direction", "moving", "growth", "rising",
                            "falling", "momentum", "monthly", "month by month",
                            "more expensive over", "got more expensive", "over the past",
                            "trajectory", "track", "dips", "moved")):
        return [("price_trend", {"area": area, "months": max(months, 24)})]
    if any(w in q for w in ("compare", "versus", " vs ", "better", "faster", "outperform",
                            "which community", "absorb", "two communities", "which of the two",
                            "side by side", "cheaper", "more expensive", "transactions",
                            "deals", "stack up")):
        return [("compare_communities", {"months": months})]
    # default: give the comparison plus coverage, rather than guessing
    return [("compare_communities", {"months": months}), ("data_coverage", {})]


def plan_llm(question):
    """Optional: let Claude pick tools. Falls back to rules on any failure."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        spec = ("Choose tools to answer a question about Dubai property transactions. "
                "Tools: compare_communities(months), price_trend(area, months), "
                "segment_breakdown(area, by, months), data_coverage(). "
                "Areas: 'EMAAR SOUTH' or 'DUBAI CREEK HARBOUR'. "
                "Reply ONLY with lines of the form tool|key=value,key=value")
        r = client.messages.create(
            model="claude-sonnet-5", max_tokens=200,
            system=spec, messages=[{"role": "user", "content": question}])
        plan = []
        for line in r.content[0].text.strip().splitlines():
            if "|" not in line:
                continue
            name, _, args = line.partition("|")
            name = name.strip()
            if name not in tools.TOOLS:
                continue
            kw = {}
            for pair in args.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    v = v.strip().strip("'\"")
                    kw[k.strip()] = int(v) if v.isdigit() else (None if v in ("none", "None") else v)
            plan.append((name, kw))
        return plan or None
    except Exception:
        return None          # any failure → rules. The tool still works offline.


def ask(question, planner="auto"):
    """Answer a question, or refuse it. Always returns evidence."""
    refusals = ev.scope_refusals(question)

    plan = None
    if planner in ("auto", "llm"):
        plan = plan_llm(question)
    used_llm = plan is not None
    if plan is None:
        plan = plan_rules(question)

    results = []
    for name, kwargs in plan:
        fn = tools.TOOLS[name]
        try:
            data, e = fn(**kwargs)
        except TypeError:
            data, e = fn()
        results.append((name, data, e))

    return {"question": question,
            "planner": "llm" if used_llm else "rules",
            "scope_refusals": refusals,
            "results": results}


def render(answer):
    """Plain-text answer with provenance attached. No number without its basis."""
    out = [f"Q: {answer['question']}", ""]

    for r in answer["scope_refusals"]:
        out.append(f"  x REFUSED: {r}")
    if answer["scope_refusals"]:
        out.append("")
        out.append("  What I can show instead (this does NOT answer the question asked):")
        out.append("")

    for name, data, e in answer["results"]:
        out.append(f"[{name}]")
        if e.confidence == "INSUFFICIENT":
            out.append("  No answer given — the data does not support one.")
        else:
            out.extend(_fmt(name, data))
        out.append("  " + e.as_text().replace("\n", "\n  "))
        out.append("")

    out.append(f"(planner: {answer['planner']} · "
               f"numbers computed in pandas, not generated by a model)")
    return "\n".join(out)


def _fmt(name, d):
    lines = []
    if name == "compare_communities":
        for area, v in d.items():
            yoy = f"{v['yoy_ppsf_pct']:+.1f}% YoY" if v["yoy_ppsf_pct"] is not None else "YoY n/a"
            lines.append(f"  {area.title():<22} {v['transactions']:>5} txns · "
                         f"median AED {v['median_ppsf']}/sqft · {yoy} · "
                         f"off-plan {v['offplan_share_pct']}%")
    elif name == "price_trend":
        s = d["monthly_median_ppsf"]
        if s:
            months = list(s)
            lines.append(f"  {d['area'].title()}: AED {d['first']}/sqft ({months[0]}) "
                         f"→ AED {d['last']}/sqft ({months[-1]})")
            change = (d["last"] / d["first"] - 1) * 100 if d["first"] else 0
            lines.append(f"  change over window: {change:+.1f}% · {len(s)} months with enough deals")
    elif name == "segment_breakdown":
        for seg, v in list(d.get("segments", {}).items())[:6]:
            lines.append(f"  {seg:<22} {v['txns']:>5} txns · AED {v['median_ppsf']}/sqft · "
                         f"AED {v['value_aed_m']}m total")
    elif name == "data_coverage":
        lines.append(f"  {d['rows']:,} transactions · {', '.join(a.title() for a in d['areas'])} · "
                     f"{d['from']} → {d['to']}")
        lines.append(f"  NOT in this source: {', '.join(d['not_in_source'])}")
    return lines
