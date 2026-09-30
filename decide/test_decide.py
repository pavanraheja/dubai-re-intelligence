"""
Tests for the decision workbench: the rules that keep it decision SUPPORT.

Run:  python decide/test_decide.py
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from decide.engine import run, MIN_SALES, PRESETS  # noqa: E402


def test_thin_projects_are_listed_never_ranked():
    r = run()
    assert all(o["sales"] >= MIN_SALES for o in r["options"])
    assert any("fewer than" in " ".join(x["excluded_because"]) for x in r["excluded"])


def test_unnamed_project_is_never_an_option():
    assert all(o["project"] != "UNNAMED" for o in run()["options"])


def test_budget_excludes_out_of_band_projects():
    # Azizi Venice's median ticket is well under AED 1M: outside the default band
    r = run()
    assert "AZIZI VENICE" not in [o["project"] for o in r["options"]]
    assert "AZIZI VENICE" in [o["project"] for o in run(budget=(300_000, 1_000_000))["options"]]


def test_weights_are_normalised_and_order_is_deterministic():
    a = run(weights={"demand": 2, "persistence": 2})
    b = run(weights={"demand": 1, "persistence": 1})
    assert abs(sum(a["frame"]["weights"].values()) - 1) < 1e-6
    assert [o["project"] for o in a["options"]] == [o["project"] for o in b["options"]]


def test_stress_shares_are_probabilities():
    r = run()
    assert abs(sum(o["p_first"] for o in r["options"]) - 1) < 0.01
    assert all(0 <= o["p_top3"] <= 1 for o in r["options"])


def test_noisy_momentum_is_scored_on_its_lower_bound():
    for o in run("growth")["options"]:
        if o["momentum_ci"]:
            assert o["momentum"] == o["momentum_ci"][0] <= o["momentum_point"]


def test_growth_preset_warns_how_little_momentum_is_reliable():
    assert any("price momentum whose 90% interval" in w for w in run("growth")["warnings"])


def test_unsettled_leader_is_called_out():
    r = run()
    if r["stress"]["leader_holds"] < .6:
        assert any("not settled by the data" in w for w in r["warnings"])


def test_expo_can_be_excluded_from_the_mandate():
    r = run(include_expo=False)
    assert not any(o["master"].startswith("Expo") for o in r["options"])


def test_every_option_carries_the_evidence_gaps():
    for o in run()["options"]:
        assert any("Exit liquidity" in g for g in o["gaps"])


def test_a_budget_nothing_fits_returns_empty_not_a_crash():
    r = run(budget=(30_000_000, 40_000_000))
    assert r["options"] == [] and r["stress"]["leader_holds"] is None


def test_output_is_json_serialisable_for_every_preset():
    for p in PRESETS:
        json.dumps(run(p))


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
