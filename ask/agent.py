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
    project = any(w in q for w in ("project", "building", "tower", "development"))
    rooms = re.search(r"\b(\d\s?-?\s?(bed|br|b/r)\w*|studios?|bedrooms?)\b", q)
    # "how many studios sold recently" is a count by segment, not a list of deals
    # (found by the learning loop, 28 Sep). Individual deals only when nothing is being counted.
    counting = rooms or "how many" in q or "how much" in q
    if not project and not counting and any(w in q for w in (
            "latest", "recent", "biggest", "largest", "highest", "record", "most expensive deal",
            "most expensive sale", "top deal", "top sale")):
        kind = "recent" if any(w in q for w in ("latest", "recent")) else "largest"
        return [("notable_transactions", {"area": area, "kind": kind})]
    ready = re.search(r"\bready\b", q)
    if project or ready or rooms or any(w in q for w in (
            "breakdown", "break down", "segment", "split", "villa", "apartment", "townhouse",
            "property type", "where does the money", "trades most", "sells most")):
        sort = "ppsf" if any(w in q for w in ("expensive", "cheap", "priciest", "premium", "price")) and project else "txns"
        by = ("project_en" if project else "reg_type" if ready
              else "rooms" if rooms else "property_type")
        # No community named → one breakdown per community. Never pool the two: a pooled
        # median is mostly the bigger community and can move on mix alone.
        if area is None:
            return [("segment_breakdown", {"area": a, "by": by, "months": months, "sort": sort})
                    for a in ("DUBAI CREEK HARBOUR", "EMAAR SOUTH")]
        return [("segment_breakdown", {"area": area, "by": by, "months": months, "sort": sort})]
    if any(w in q for w in ("trend", "over time", "direction", "moving", "growth", "rising",
                            "falling", "momentum", "monthly", "month by month",
                            "more expensive over", "got more expensive", "over the past",
                            "trajectory", "track", "dips", "moved", "going up", "going down",
                            "cooling", "heating", "since", "change", "by month", "per month",
                            "demand")):
        if area is None:     # "trend in both", "in comparison", or no community named
            return [("compare_trends", {"months": max(months, 24)})]
        return [("price_trend", {"area": area, "months": max(months, 24)})]
    if any(w in q for w in ("compare", "versus", " vs ", "better", "faster", "outperform",
                            "which community", "absorb", "two communities", "which of the two",
                            "side by side", "cheaper", "more expensive", "transactions",
                            "deals", "stack up")):
        return [("compare_communities", {"months": months})]
    # one named community and no more specific ask ("what's going on with X") -> its snapshot
    if area:
        return [("community_snapshot", {"area": area})]
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
                "segment_breakdown(area, by=property_type|rooms|reg_type|project_en, months, sort=txns|ppsf), "
                "community_snapshot(area), notable_transactions(area, kind=recent|largest), data_coverage(). "
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


# Spellings people actually type. Applied before refusals and planning alike.
SPELLING = ((r"\bharbor\b", "harbour"), (r"\bemmar\b", "emaar"), (r"\bemar\b", "emaar"))


def normalise(question):
    q = question.strip()
    for pat, rep in SPELLING:
        q = re.sub(pat, rep, q, flags=re.I)
    return q


def ask(question, planner="auto"):
    """Answer a question, or refuse it. Always returns evidence."""
    question = normalise(question)
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
        # Asked about a segment with zero sales? Say "none" instead of listing the others.
        if name == "segment_breakdown" and data.get("by") == "rooms":
            asked = {"studio": "Studio"} if re.search(r"\bstudios?\b", question.lower()) else {}
            for word, seg in asked.items():
                if not any(seg.lower() in k.lower() for k in data.get("segments", {})):
                    e.caveats.insert(0, f"no {word} sales recorded in "
                                        f"{data['area'].title()} in this extract — the answer is zero")
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
    elif name == "compare_trends":
        for a, v in d["communities"].items():
            ch = f"{v['change_pct']:+.1f}%" if v["change_pct"] is not None else "n/a"
            ks = list(v["monthly_median_ppsf"])
            lines.append(f"  {a.title():<22} AED {v['first']}/sqft ({ks[0] if ks else '?'}) → "
                         f"AED {v['last']}/sqft ({ks[-1] if ks else '?'}) · {ch}")
    elif name == "notable_transactions":
        for t in d["transactions"]:
            lines.append(f"  {t['date']}  {str(t['project'])[:26]:<26} {t['rooms']:<7} {t['status']:<8} "
                         f"{t['sqft'] or 0:>6,} sqft  AED {t['price_aed']:>12,}  ({t['ppsf']:,.0f}/sqft)")
    elif name == "community_snapshot":
        lines.append(f"  {d['area'].title()}: {d['transactions']:,} sales · median AED {d['median_ppsf']}/sqft · "
                     f"median price AED {d['median_price_aed']:,} · off-plan {d['offplan_share_pct']}%")
        t = d.get("trend")
        if t:
            lines.append(f"  price/sqft {t['from_month']} → {t['to_month']}: AED {t['from_ppsf']} → "
                         f"{t['to_ppsf']} ({t['change_pct']:+.1f}%) · busiest month {d['busiest_month']}")
        if d["top_bedrooms"]:
            lines.append("  mix: " + " · ".join(f"{k} {v}%" for k, v in d["top_bedrooms"].items()))
    elif name == "data_coverage":
        lines.append(f"  {d['rows']:,} transactions · {', '.join(a.title() for a in d['areas'])} · "
                     f"{d['from']} → {d['to']}")
        lines.append(f"  NOT in this source: {', '.join(d['not_in_source'])}")
    return lines
