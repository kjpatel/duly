"""Decision phrasing (kernel/duly_kernel/phrasing.py).

Phrasing moved into the kernel because two surfaces were wording the same
decision two different ways: the demo read the pack's `phrasing:` block, and
the audit report guessed from the attribute name. One implementation now
answers both, so it needs toolkit-owned coverage — asserted against
`fixtures/pack.yaml`, whose `fx:assessedFee` decision is the repo's one
committed non-boolean phrasing block and whose `fx:permitted` decision
deliberately has none.

Guards and placeholders that the fixture pack does not itself exercise are
asserted against packs built inline here. That is on purpose: a phrasing
vocabulary is a published contract (spec/rule-ir.md), and pinning it to
whichever guards the example packs happen to use today would make deleting an
example pack silently delete a contract test.
"""

import pytest

import duly_kernel.ir as ir
from duly_kernel.ir import validate_pack
from duly_kernel.phrasing import (
    PHRASING_FORMATS,
    PHRASING_TOKEN,
    determination,
    low_confidence_caveat,
)

from conftest import fixture_case, fixture_pack

FX_AS_OF_EFFECTIVE = "2026-06-01"
FX_AS_OF_KNOWLEDGE = "2026-03-02T12:00:00Z"


def _pack(phrasing, attribute="d:answer"):
    """A minimal valid pack carrying one phrased decision."""
    return {
        "pack": {"name": "phrasing-fixture", "version": "1.0.0"},
        "decisions": [
            {"attribute": attribute, "entityType": "d:Thing", "phrasing": phrasing}
        ],
        "rules": [
            {
                "id": "D-00",
                "version": "1.0.0",
                "priority": 0,
                "citation": {"text": "Inline fixture (fictional)"},
                "effectiveFrom": "1900-01-01",
                # `score` is bound, not merely declared: `{caveat}` and the
                # `abstained` guard are scoped to attributes the decision's
                # rules can actually consult, so a fixture whose rule reads
                # nothing would abstain over something irrelevant and
                # correctly get no caveat.
                "given": {
                    "thing": {"entityType": "d:Thing"},
                    "score": {"attribute": "d:score"},
                    "a": {"attribute": "d:a"},
                },
                "then": {
                    "entity": "thing",
                    "attribute": attribute,
                    "value": {"kind": "boolean", "value": True},
                },
            }
        ],
    }


def _receipt(value, attribute="d:answer", **extra):
    return {"decision": {"attribute": attribute, "value": value}, **extra}


# ---------------------------------------------------------------------------
# The None contract
# ---------------------------------------------------------------------------


class TestNoWordingToOffer:
    """`None` is the whole reason this returns a value rather than a string.

    Each caller words the gap differently — the report names the attribute,
    the demo says Yes/No and flags `generic` — so inventing a fallback here
    would publish wording no pack author wrote, which is the defect the module
    exists to remove.
    """

    def test_no_pack_at_all(self):
        assert determination(_receipt({"kind": "boolean", "value": True}), [], None) is None

    def test_pack_phrases_a_different_decision(self):
        pack = _pack([{"verdict": "Yes"}], attribute="d:other")
        assert determination(_receipt({"kind": "boolean", "value": True}), [], pack) is None

    def test_the_fixture_packs_unphrased_decision(self):
        facts, _case, receipt = fixture_case("fx-0001")
        assert receipt["decision"]["attribute"] == "fx:permitted"
        assert determination(receipt, facts, fixture_pack()) is None

    def test_no_case_matches(self):
        pack = _pack([{"when": {"value": True}, "verdict": "Yes"}])
        found = determination(_receipt({"kind": "boolean", "value": False}), [], pack)
        assert found is None

    def test_a_case_whose_verdict_cannot_render_is_passed_over(self):
        # Every alternative unresolvable == the case cannot speak, so the next
        # case gets its turn. A half-rendered verdict is never emitted.
        pack = _pack(
            [
                {"verdict": "{fact:missingAttribute}"},
                {"verdict": "Fallback case"},
            ]
        )
        found = determination(_receipt({"kind": "code", "value": "X"}), [], pack)
        assert found == {"verdict": "Fallback case", "detail": "", "tone": ""}


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


class TestGuards:
    def test_first_matching_case_wins(self):
        pack = _pack(
            [
                {"when": {"value": True}, "verdict": "First", "tone": "pos"},
                {"when": {"value": True}, "verdict": "Second"},
            ]
        )
        found = determination(_receipt({"kind": "boolean", "value": True}), [], pack)
        assert found == {"verdict": "First", "detail": "", "tone": "pos"}

    def test_an_unguarded_case_always_holds(self):
        pack = _pack([{"verdict": "Anything", "detail": "d", "tone": "warn"}])
        found = determination(_receipt({"kind": "code", "value": "Z"}), [], pack)
        assert found == {"verdict": "Anything", "detail": "d", "tone": "warn"}

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [("250.00", "Fee assessed"), ("0.00", "No fee"), ("-1.00", "No fee")],
    )
    def test_money_is_guarded_by_amount_not_by_value(self, amount, expected):
        # A money value is an amount and a currency, not a scalar, so `value:`
        # matches nothing on it — which is why the fixture pack carries this
        # guard and a comment about getting it wrong the first time.
        pack = fixture_pack()
        receipt = _receipt(
            {"kind": "money", "amount": amount, "currency": "USD"},
            attribute="fx:assessedFee",
        )
        assert determination(receipt, [], pack)["verdict"] == expected

    def test_a_code_value_is_guarded_by_its_literal(self):
        pack = _pack(
            [
                {"when": {"value": "ZeroTolerance"}, "verdict": "Zero tolerance"},
                {"verdict": "Something else"},
            ]
        )
        found = determination(_receipt({"kind": "code", "value": "ZeroTolerance"}), [], pack)
        assert found["verdict"] == "Zero tolerance"

    def test_abstained_guards_on_a_low_confidence_exclusion(self):
        pack = _pack(
            [
                {
                    "when": {"value": True, "abstained": "lowConfidence"},
                    "verdict": "Yes",
                    "detail": "{caveat}",
                    "tone": "warn",
                },
                {"when": {"value": True}, "verdict": "Yes", "tone": "pos"},
            ]
        )
        value = {"kind": "boolean", "value": True}
        clean = determination(_receipt(value), [], pack)
        assert clean == {"verdict": "Yes", "detail": "", "tone": "pos"}

        abstained = determination(
            _receipt(
                value,
                abstentions=[
                    {
                        "reason": "low_confidence",
                        "attribute": "d:score",
                        "confidence": {"score": 0.42},
                        "threshold": {"minConfidence": 0.8},
                    }
                ],
            ),
            [],
            pack,
        )
        assert abstained["tone"] == "warn"
        assert abstained["detail"] == (
            "Presumption only — score excluded at confidence 0.42, "
            "below the 0.8 floor"
        )

    def test_a_fact_guard_reads_the_facts_the_caller_supplied(self):
        pack = _pack(
            [
                {
                    "when": {"fact": {"attribute": "method", "equals": "RemoteOnline"}},
                    "verdict": "Remote",
                },
                {"when": {"fact": {"attribute": "method", "present": True}}, "verdict": "Some method"},
                {"verdict": "No method on file"},
            ]
        )
        value = {"kind": "boolean", "value": True}
        remote = [{"attribute": "d:method", "value": {"kind": "code", "value": "RemoteOnline"}}]
        wet = [{"attribute": "d:method", "value": {"kind": "code", "value": "WetInk"}}]
        assert determination(_receipt(value), remote, pack)["verdict"] == "Remote"
        assert determination(_receipt(value), wet, pack)["verdict"] == "Some method"
        assert determination(_receipt(value), [], pack)["verdict"] == "No method on file"

    def test_a_fact_guard_can_compare_against_the_decision_value(self):
        pack = _pack(
            [
                {
                    "when": {"fact": {"attribute": "statedDeadline", "equals": "{value}"}},
                    "verdict": "Matches what the document stated",
                },
                {"verdict": "Differs from what the document stated"},
            ]
        )
        value = {"kind": "date", "value": "2026-08-01"}
        agrees = [{"attribute": "d:statedDeadline", "value": {"kind": "date", "value": "2026-08-01"}}]
        differs = [{"attribute": "d:statedDeadline", "value": {"kind": "date", "value": "2026-09-01"}}]
        assert determination(_receipt(value), agrees, pack)["verdict"].startswith("Matches")
        assert determination(_receipt(value), differs, pack)["verdict"].startswith("Differs")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestPlaceholders:
    def test_value_and_money(self):
        pack = _pack([{"verdict": "{money}", "detail": "{value}"}], attribute="d:fee")
        found = determination(
            _receipt({"kind": "money", "amount": "12.50", "currency": "EUR"}, attribute="d:fee"),
            [],
            pack,
        )
        assert found == {"verdict": "12.50 EUR", "detail": "12.50 EUR", "tone": ""}

    def test_formats_trim_a_date_and_round_a_decimal(self):
        pack = _pack([{"verdict": "{value|day}"}])
        found = determination(
            _receipt({"kind": "datetime", "value": "2026-08-01T00:00:00Z"}), [], pack
        )
        assert found["verdict"] == "2026-08-01"

        pack_int = _pack([{"verdict": "{fact:days|int}"}])
        facts = [{"attribute": "d:days", "value": {"kind": "decimal", "value": "45.0"}}]
        assert determination(_receipt({"kind": "code", "value": "x"}), facts, pack_int)[
            "verdict"
        ] == "45"

    def test_derived_reads_the_derivation_tree(self):
        pack = _pack([{"verdict": "{derived:requiredMinimumScore|int} required"}])
        receipt = _receipt(
            {"kind": "boolean", "value": False},
            derivation={
                "rule": "D-01",
                "conclusion": {"attribute": "d:answer", "value": {"kind": "boolean", "value": False}},
                "premises": [
                    {
                        "rule": "D-02",
                        "conclusion": {
                            "attribute": "d:requiredMinimumScore",
                            "value": {"kind": "decimal", "value": "50"},
                        },
                        "premises": [],
                    }
                ],
            },
        )
        assert determination(receipt, [], pack)["verdict"] == "50 required"

    def test_days_between_subtracts_two_facts_and_never_reads_a_clock(self):
        pack = _pack([{"verdict": "{daysBetween:mailed,expires} days"}])
        facts = [
            {"attribute": "d:mailed", "value": {"kind": "date", "value": "2026-07-25"}},
            {"attribute": "d:expires", "value": {"kind": "date", "value": "2026-09-01"}},
        ]
        assert determination(_receipt({"kind": "boolean", "value": False}), facts, pack)[
            "verdict"
        ] == "38 days"

    def test_the_first_fully_resolving_alternative_wins(self):
        # The contract that makes a pack able to say "phrase it this way when
        # the inputs are there, that way when they are not".
        pack = _pack(
            [
                {
                    "verdict": "V",
                    "detail": [
                        "{daysBetween:mailed,expires} days notice given",
                        "No applicable rule found it deficient",
                    ],
                }
            ]
        )
        value = {"kind": "boolean", "value": False}
        facts = [
            {"attribute": "d:mailed", "value": {"kind": "date", "value": "2026-07-25"}},
            {"attribute": "d:expires", "value": {"kind": "date", "value": "2026-09-01"}},
        ]
        assert determination(_receipt(value), facts, pack)["detail"] == "38 days notice given"
        assert determination(_receipt(value), [], pack)["detail"] == (
            "No applicable rule found it deficient"
        )

    def test_fewer_facts_makes_a_template_unresolvable_never_wrong(self):
        pack = _pack([{"verdict": "{fact:score}"}])
        assert determination(_receipt({"kind": "code", "value": "x"}), [], pack) is None


# ---------------------------------------------------------------------------
# The validator and the renderer are one vocabulary
# ---------------------------------------------------------------------------


def test_the_validator_resolves_placeholders_with_the_renderers_own_regex():
    """A validator and a renderer holding separate copies of "what a
    placeholder is" fail the worst way available: the pack loads, and the
    sentence silently comes out wrong. `ir.py` imports both the token pattern
    and the format set from `phrasing.py`, so this asserts the wiring rather
    than re-stating the pattern."""
    assert ir._PHRASING_TOKEN is PHRASING_TOKEN
    assert ir._PHRASING_FORMATS is PHRASING_FORMATS


def test_a_caveat_names_only_exclusions_this_decision_could_consult():
    """Abstentions are case-wide; a caveat is about *this* answer.

    The kernel excludes below-floor facts from the whole live-fact universe
    before any rule runs, so a receipt carries exclusions that had nothing to
    do with the question it answers. Unscoped, a decision that never read the
    attribute got captioned "Presumption only — … excluded" — a false claim
    about why that answer is what it is, and one that reaches the audit report
    a regulator reads. The corpus could not catch it: it asks one question per
    case, so its abstentions are always relevant. Asking two questions of one
    case is what exposes it.
    """
    pack = _pack([{"when": {"value": True}, "verdict": "Yes", "detail": "{caveat}"}])
    consulted = {
        "reason": "low_confidence",
        "attribute": "d:score",
        "confidence": {"score": 0.42},
        "threshold": {"minConfidence": 0.8},
    }
    unrelated = {**consulted, "attribute": "d:somethingElse"}
    value = {"kind": "boolean", "value": True}

    # The fixture's rule binds d:score, so this exclusion shaped the answer.
    assert "score excluded" in determination(
        _receipt(value, abstentions=[consulted]), [], pack
    )["detail"]

    # No rule concluding d:answer reads d:somethingElse, so the decision is
    # not "presumption only" on its account — the case falls through to a
    # phrasing alternative that claims nothing.
    assert determination(_receipt(value, abstentions=[unrelated]), [], pack)["detail"] == ""

    # And an unrelated exclusion does not resurrect a caveat beside a real one.
    both = determination(_receipt(value, abstentions=[unrelated, consulted]), [], pack)
    assert "score excluded" in both["detail"]
    assert "somethingElse" not in both["detail"]


def test_without_a_pack_a_caveat_stays_unscoped_rather_than_vanishing():
    """`None` from `consulted_attributes` means *unknown*, not *nothing*.

    A caller with no pack cannot tell relevance, and silently dropping a
    caveat it cannot verify would hide a real exclusion. Over-reporting is the
    safe direction here; under-reporting is not.
    """
    receipt = _receipt(
        {"kind": "boolean", "value": True},
        abstentions=[{"reason": "low_confidence", "attribute": "d:whatever"}],
    )
    assert low_confidence_caveat(receipt) is not None
    assert low_confidence_caveat(receipt, None) is not None


def test_every_placeholder_the_validator_accepts_the_renderer_resolves():
    pack = _pack(
        [
            {
                "verdict": "{value} {money} {fact:a} {derived:b} {daysBetween:a,c}",
                "detail": "{caveat}",
            }
        ]
    )
    validate_pack(pack)  # the vocabulary, as the pack author sees it
    facts = [
        {"attribute": "d:a", "value": {"kind": "date", "value": "2026-01-01"}},
        {"attribute": "d:c", "value": {"kind": "date", "value": "2026-01-11"}},
    ]
    receipt = _receipt(
        {"kind": "money", "amount": "5.00", "currency": "USD"},
        derivation={
            "rule": "D-00",
            "conclusion": {"attribute": "d:b", "value": {"kind": "decimal", "value": "7"}},
            "premises": [],
        },
        abstentions=[{"reason": "low_confidence", "attribute": "d:a"}],
    )
    found = determination(receipt, facts, pack)
    assert found["verdict"] == "5.00 USD 5.00 USD 2026-01-01 7 10"
    assert found["detail"] == "Presumption only — a excluded below the confidence floor"
