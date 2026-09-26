#!/usr/bin/env python3
"""
Score the ask/ layer against a fixed, labelled question set.

    python evals/run_eval.py              # all splits
    python evals/run_eval.py --split holdout

Two error types, reported separately because they do not cost the same:
  MISSED REFUSAL  — answered a question the data cannot support. The expensive one:
                    a confident number that should not exist.
  OVER-REFUSAL    — refused (or routed wrongly) a question it could answer. Annoying,
                    not dangerous.

Rules: the dev split is what the refusal rules were tuned on. The holdout split
was written at the same time and not used for tuning, so its score is the one
to quote.
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ask.agent import ask  # noqa: E402

QUESTIONS = os.path.join(ROOT, "evals", "questions_v1.jsonl")

# refusal category → text that identifies it in the refusal message
CATEGORY = {"forward": "forward-looking", "causal": "causal", "advice": "advice",
            "out_of_scope": "out of scope", "supply": "supply question",
            "unknown_area": "not in this extract"}


def outcome(a):
    """What the system actually did, as a set of labels."""
    got = {f"refuse:{c}" for c, key in CATEGORY.items()
           if any(key in r for r in a["scope_refusals"])}
    if not a["scope_refusals"] and a["results"]:
        got.add(f"answer:{a['results'][0][0]}")
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout"])
    args = ap.parse_args()

    qs = [json.loads(l) for l in open(QUESTIONS) if l.strip()]
    if args.split:
        qs = [q for q in qs if q["split"] == args.split]

    by_split, missed, over = {}, [], []
    for q in qs:
        got = outcome(ask(q["q"], planner="rules"))
        ok = bool(got & set(q["expect"]))
        s = by_split.setdefault(q["split"], [0, 0])
        s[0] += ok
        s[1] += 1
        if not ok:
            wants_refusal = q["expect"][0].startswith("refuse")
            (missed if wants_refusal else over).append((q, got))
        print(f"  {'pass' if ok else 'FAIL'}  {q['id']}  {q['q'][:62]:<62}  got {sorted(got) or ['nothing']}")

    print()
    for split, (ok, n) in by_split.items():
        print(f"{split:<8} {ok}/{n}  ({ok / n:.0%})")
    print(f"missed refusals (answered when it should not): {len(missed)}")
    print(f"over-refusals / wrong tool:                    {len(over)}")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
