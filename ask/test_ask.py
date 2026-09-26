"""
Tests for the part that matters: what the tool refuses to say.

Run:  python ask/test_ask.py      (or: python -m pytest ask/test_ask.py -q)
"""
import os, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ask.agent import ask, plan_rules
from ask import evidence as ev
from ask import tools


def test_forward_looking_is_refused():
    a = ask("Which community will perform better next year?")
    assert any("forward-looking" in r for r in a["scope_refusals"])


def test_causal_question_is_refused():
    a = ask("Why did Creek Harbour prices rise?")
    assert any("causal" in r for r in a["scope_refusals"])


def test_out_of_scope_is_refused():
    a = ask("What are rental yields in Emaar South?")
    assert any("out of scope" in r for r in a["scope_refusals"])


def test_supply_question_is_refused():
    a = ask("Is Emaar South absorbing supply faster than Dubai Creek Harbour?")
    assert any("supply question" in r for r in a["scope_refusals"])


def test_normal_question_is_not_refused():
    a = ask("Compare the two communities over 12 months")
    assert a["scope_refusals"] == []


def test_every_answer_carries_provenance():
    a = ask("Compare the two communities over 12 months")
    for _, _, e in a["results"]:
        assert e.rows > 0
        assert e.source
        assert e.confidence in ("HIGH", "MEDIUM", "LOW", "INSUFFICIENT")


def test_thin_sample_refuses_rather_than_guesses():
    e = ev.grade([5, 900], None, "test")
    assert e.confidence == "INSUFFICIENT"
    assert e.refusals


def test_unlike_comparison_is_flagged_and_downgraded():
    e = ev.grade([500, 500], None, "test")
    assert e.confidence == "HIGH"
    e = ev.check_like_for_like(e, {"A": 70.0, "B": 20.0})
    assert any("not like-for-like" in c for c in e.caveats)
    assert e.confidence == "MEDIUM"


def test_stale_data_is_flagged():
    e = ev.grade([500, 500], (datetime(2020, 1, 1), datetime(2024, 1, 1)),
                 "test", today=datetime(2026, 1, 1))
    assert any("old" in c for c in e.caveats)


def test_planner_never_invents_a_tool():
    for q in ["compare them", "trend please", "breakdown by rooms", "anything at all"]:
        for name, _ in plan_rules(q):
            assert name in tools.TOOLS


if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  pass  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
