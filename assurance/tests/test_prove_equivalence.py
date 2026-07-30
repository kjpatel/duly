"""Equivalence over the input space (assurance/duly_assurance/prove.py).

The gap these tests close is stated in spec/dmn.md, "What this equivalence
does *not* prove": the DMN suite compares two packs over a fixture list, and
perturbing `> disclosed` to `>= disclosed` leaves all twelve of its tests
green because no committed fixture puts the two amounts exactly equal.

The acceptance evidence is `test_the_perturbation_the_fixtures_cannot_see_is_caught`
below. It also records something spec/dmn.md gets slightly wrong: that
perturbation changes no *decision* at all — both packs conclude a `0.00`
cure when the amounts are equal — it changes which rule fired and what it
defeated. Decision equivalence therefore cannot catch it, and should not
pretend to; trace equivalence can, and does.
"""

from __future__ import annotations

import pytest

from provetest_helpers import (  # noqa: E402
    HAVE_Z3,
    committed_pack,
    dmn_pack,
    perturbed,
    repo_registry,
)

needs_z3 = pytest.mark.skipif(not HAVE_Z3, reason="z3-solver is not installed")

HAND = "trid-fee-tolerance-us-federal"


def compare(pack_a, pack_b, attributes=None):
    from duly_assurance.prove import equivalence_report

    return equivalence_report(pack_a, pack_b, repo_registry(), attributes)


def decision(report, attribute):
    return next(d for d in report.decisions if d.attribute == attribute)


# ---------------------------------------------------------------------------
# The committed pair
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_dmn_example_and_the_hand_written_trid_pack_are_equivalent():
    """The claim spec/dmn.md makes over fixtures, made over the input space."""
    report = compare(committed_pack(HAND), dmn_pack())
    assert report.error is None
    assert [d.verdict for d in report.decisions] == ["PROVED-DISJOINT"] * 2
    assert {d.attribute for d in report.decisions} == {
        "trid:toleranceCategory",
        "trid:toleranceCureAmount",
    }
    assert report.trace.verdict == "PROVED-DISJOINT"
    assert report.trace.shared_rules == 3
    assert report.exit_code == 0


@needs_z3
@pytest.mark.z3
def test_differing_compiled_priorities_do_not_break_equivalence():
    """spec/dmn.md M2: compiled priorities come from hit policy and row order,
    so the numbers differ from the hand-written pack's by construction. What
    must match is the *outcome* of the tiebreak, and it does."""
    hand, compiled = committed_pack(HAND), dmn_pack()
    hand_priorities = {r["id"]: r["priority"] for r in hand["rules"]}
    compiled_priorities = {r["id"]: r["priority"] for r in compiled["rules"]}
    assert hand_priorities != compiled_priorities
    assert compare(hand, compiled).trace.verdict == "PROVED-DISJOINT"


# ---------------------------------------------------------------------------
# The acceptance evidence
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_perturbation_the_fixtures_cannot_see_is_caught():
    """`> disclosed` becoming `>= disclosed`, caught at the boundary."""
    report = compare(
        committed_pack(HAND), perturbed(dmn_pack(), "actual > disclosed", "actual >= disclosed")
    )
    assert report.trace.verdict == "NOT-PROVED"
    assert report.exit_code == 1

    differences = set(report.trace.differences)
    assert "TRID-ZT-01 applies" in differences
    assert "TRID-ZT-01 defeats TRID-DEF-00" in differences

    witness = dict(report.trace.witness)
    assert witness["trid:feeType"] == '"TransferTax"'
    # The whole point: the perturbation is visible only where the two amounts
    # are exactly equal, which is exactly what no committed fixture supplies.
    assert (
        witness["trid:actualAmountAtClosing"] == witness["trid:disclosedAmountAtBaseline"]
    )


@needs_z3
@pytest.mark.z3
def test_that_same_perturbation_changes_no_decision_which_is_why_trace_matters():
    """Reported rather than engineered around: at `actual == disclosed` the
    cure rule concludes `actual - disclosed`, which is the `0.00` the default
    rule concludes anyway. Decision equivalence is right to prove them equal;
    it is the receipt that changed, not the answer."""
    report = compare(
        committed_pack(HAND), perturbed(dmn_pack(), "actual > disclosed", "actual >= disclosed")
    )
    assert decision(report, "trid:toleranceCureAmount").verdict == "PROVED-DISJOINT"
    assert decision(report, "trid:toleranceCategory").verdict == "PROVED-DISJOINT"


@needs_z3
@pytest.mark.z3
def test_a_perturbation_that_does_change_a_decision_is_caught_at_the_decision_level():
    """The fixture-visible perturbation spec/dmn.md measures (retyping one
    input cell) fails 10 of its 12 tests. Here it fails at both levels, and
    the witness names the fee type that separates them."""
    report = compare(
        committed_pack(HAND), perturbed(dmn_pack(), '"TransferTax"', '"RecordingFee"')
    )
    assert decision(report, "trid:toleranceCategory").verdict == "NOT-PROVED"
    assert report.trace.verdict == "NOT-PROVED"
    assert report.exit_code == 1


@needs_z3
@pytest.mark.z3
def test_the_disagreement_witness_names_both_packs_values():
    report = compare(
        committed_pack(HAND), perturbed(dmn_pack(), '"TransferTax"', '"RecordingFee"')
    )
    result = decision(report, "trid:toleranceCategory")
    assert result.left_value != result.right_value
    assert "(no decision)" in (result.left_value, result.right_value)


# ---------------------------------------------------------------------------
# Honest refusals
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_two_unrelated_packs_share_no_rule_id_and_the_tool_says_so():
    report = compare(
        committed_pack(HAND), committed_pack("notarization-ron-us-states")
    )
    assert report.decisions == []
    assert report.trace.verdict == "OUT-OF-FRAGMENT"
    assert "share no rule id" in report.trace.reason
    assert report.exit_code == 2


@needs_z3
@pytest.mark.z3
def test_rules_present_in_only_one_pack_are_named_rather_than_ignored():
    compiled = dmn_pack()
    compiled["rules"] = [r for r in compiled["rules"] if r["id"] != "TRID-DEF-00"]
    report = compare(committed_pack(HAND), compiled)
    assert report.only_a == ["TRID-DEF-00"]
    assert report.only_b == []


@needs_z3
@pytest.mark.z3
def test_a_pack_is_equivalent_to_itself():
    hand = committed_pack(HAND)
    report = compare(hand, hand)
    assert report.exit_code == 0
    assert report.trace.verdict == "PROVED-DISJOINT"


@needs_z3
@pytest.mark.z3
def test_equivalence_output_is_stable_across_runs():
    from duly_assurance.prove import render_equivalence

    args = (
        committed_pack(HAND),
        perturbed(dmn_pack(), "actual > disclosed", "actual >= disclosed"),
    )
    first = render_equivalence(compare(*args), "a", "b", verbose=True)
    second = render_equivalence(compare(*args), "a", "b", verbose=True)
    assert first == second
