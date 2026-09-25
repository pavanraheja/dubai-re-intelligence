#!/usr/bin/env python3
"""
Ask the Dubai transaction data a question.

    python ask.py "is Emaar South absorbing supply faster than Creek Harbour?"
    python ask.py --demo          # run the built-in question set
    python ask.py --json "..."    # machine-readable

Works with no API key (rule-based planner). Set ANTHROPIC_API_KEY to let Claude
choose the tools instead — the numbers and the refusals are identical either way.
"""
import sys, json
from ask.agent import ask, render

DEMO = [
    "What can this data actually answer?",
    "Is Emaar South absorbing supply faster than Dubai Creek Harbour?",
    "What's the price trend in Dubai Creek Harbour over 24 months?",
    "Break down Emaar South by property type",
    "Which community will perform better next year?",      # refused: forward-looking
    "Why did Creek Harbour prices rise?",                   # refused: causal
    "What are rental yields in Emaar South?",               # refused: out of scope
]

def main():
    args = [a for a in sys.argv[1:]]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]

    if not args or args[0] == "--demo":
        for q in DEMO:
            print("=" * 78)
            print(render(ask(q)))
        return

    a = ask(" ".join(args))
    if as_json:
        print(json.dumps({
            "question": a["question"], "planner": a["planner"],
            "scope_refusals": a["scope_refusals"],
            "results": [{"tool": n, "data": d,
                         "evidence": {"rows": e.rows, "confidence": e.confidence,
                                      "caveats": e.caveats, "refusals": e.refusals}}
                        for n, d, e in a["results"]]}, indent=2, default=str))
    else:
        print(render(a))

if __name__ == "__main__":
    main()
