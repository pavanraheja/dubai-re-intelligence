"""
Tests for the conversation layer: it understands the decision-maker, and it never
writes a number the engine did not produce.

Run:  python decide/test_converse.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decide.converse import (converse, parse, parse_budget, numbers_in, allowed_numbers,  # noqa: E402
                             template_reply)

MESSAGES = [
    "I have 4-5 mil, want to be able to exit in 3 years, leave Expo out",
    "I have 1-2m budget, which is best?",
    "between 1 and 2 million, growth matters most",
    "under 2m, cheapest entry, off-plan only",
    "AED 1,500,000 to 2,000,000, stable and low risk",
    "will prices rise in Hayat next year? budget 4 to 5 million",
    "compare windsor house and south square",
    "why windsor house",
    "I have 30-40 million",
]


def test_budget_is_understood_in_the_ways_people_say_it():
    assert parse_budget("I have 4-5 mil") == [4e6, 5e6]
    assert parse_budget("1–2m budget") == [1e6, 2e6]
    assert parse_budget("between 1 and 2 million") == [1e6, 2e6]
    assert parse_budget("under 2m") == [0, 2e6]
    assert parse_budget("AED 1,500,000 to 2,000,000") == [1.5e6, 2e6]


def test_years_and_bedrooms_are_not_budgets():
    assert parse_budget("I want to exit in 3 years") is None
    assert parse_budget("a 2-3 bed apartment") is None


def test_mandate_stage_and_priorities():
    st, _, _ = parse("leave Expo out, off-plan only, growth matters", {})
    assert st["frame"]["include_expo"] is False and st["frame"]["stage"] == "offplan"
    assert st["priorities"] == ["growth"]
    st2, _, _ = parse("also value", st)
    assert set(st2["priorities"]) == {"growth", "value"}


def test_every_number_in_a_reply_comes_from_the_engine():
    for msg in MESSAGES:
        _, b = converse(msg)
        stray = numbers_in(b["reply"]) - allowed_numbers(b)
        assert not stray, f"{msg!r} wrote numbers the engine did not produce: {stray}"


def test_a_generated_number_is_rejected_by_the_check():
    _, b = converse("I have 1-2m budget")
    assert numbers_in("Windsor House will return 17.3% a year") - allowed_numbers(b)


def test_weak_criteria_are_never_offered_as_reasons():
    _, b = converse("I have 4-5 mil, want to be able to exit in 3 years, leave Expo out")
    assert not any("resales" in w for w in b["leader"]["why"])   # Hayat has none


def test_it_never_picks():
    for msg in MESSAGES:
        _, b = converse(msg)
        assert "I don't pick" in b["reply"] or b["status"] == "none"
        assert "recommend" not in b["reply"].lower()


def test_forecasts_are_refused_before_answering():
    _, b = converse("will prices rise in Hayat next year? budget 4 to 5 million")
    assert b["reply"].startswith("Before anything else: forward-looking")


def test_a_what_if_reports_what_changed():
    st, b = converse("I have 1-2m, leave Expo out")
    _, b2 = converse("what if growth matters more?", st,
                     {"leader": b["leader"]["project"], "holds": b["holds"], "frame": b["frame"]})
    assert "Compared with before" in b2["reply"]
    assert b2["reply"].startswith("Changed: priority capital growth")


def test_exit_names_the_one_option_with_resale_evidence():
    _, b = converse("I have 4-5 mil, want to be able to exit in 3 years")
    assert b.get("exit_note", {}).get("project") == "The Pulse Beachfront"


def test_a_frame_nothing_fits_says_so():
    _, b = converse("I have 30-40 million")
    assert b["status"] == "none" and "No project passes" in b["reply"]


if __name__ == "__main__":
    import traceback
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
