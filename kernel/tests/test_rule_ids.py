"""The rule-id convention and its exemptions, on synthetic packs.

    PATH="/opt/homebrew/bin:$PATH" uv run pytest kernel/tests/test_rule_ids.py -q

Every pack below is built in this file, so the convention is asserted without
a corpus to point at. The four tests that swept the *committed* teaching packs
— that each declares an `idPrefix`, that the grandfather list reconciles with
them, that seventeen of those ids would fail the convention today, that they
still load — moved to `examples/tests/test_example_rule_ids.py`, because their
subject is those packs and it is deleted with `examples/`.
"""

import pytest

from duly_kernel.ir import PackValidationError, validate_pack


def conventional_pack(rules: list[dict], prefix: str = "TEST") -> dict:
    return {
        "pack": {"name": "convention-test-pack", "version": "0.0.1", "idPrefix": prefix},
        "decisions": [{"attribute": "t:x"}],
        "rules": rules,
    }


def rule(rid: str, **extra) -> dict:
    out = {
        "id": rid,
        "version": "1.0.0",
        "priority": 0,
        "citation": {"text": "Test"},
        "effectiveFrom": "1900-01-01",
        "given": {"e": {"entityType": "t:Thing"}},
        "then": {"entity": "e", "attribute": "t:x", "value": {"kind": "boolean", "value": True}},
    }
    out.update(extra)
    return out


# --- The convention binds new ids ------------------------------------------


@pytest.mark.parametrize(
    "rid",
    ["TEST-DEF-00", "TEST-NY-NONRENEWAL-01", "TEST-FUND-STAY", "TEST-EXC", "TEST-A-B-C-99"],
)
def test_conforming_ids_pass(rid):
    validate_pack(conventional_pack([rule(rid)]))


@pytest.mark.parametrize(
    "rid",
    [
        "TEST-RON-2018",  # a year
        "TEST-DTT-11933",  # a statute section
        "TEST-SB2-EXEMPT",  # a bill number, mid-id
        "TEST-NR-45-LEGACY",  # digits, but not trailing
        "TEST-NR-120",  # three digits
        "test-nr-01",  # lowercase
        "TEST_NR_01",  # underscores
    ],
)
def test_ids_that_encode_something_are_refused(rid):
    with pytest.raises(PackValidationError, match="not a conforming rule id"):
        validate_pack(conventional_pack([rule(rid)]))


def test_a_new_id_must_join_the_packs_declared_family():
    with pytest.raises(PackValidationError, match="does not start with this pack"):
        validate_pack(conventional_pack([rule("NY-NONRENEWAL-01")]))


def test_a_sequence_number_that_echoes_the_rules_own_number_is_refused():
    """`NY-NR-45` for a 45-day notice: the failure the convention exists for."""
    offender = rule(
        "TEST-NR-45",
        when=["days_between(mailed, expires) < 45"],
        given={"e": {"entityType": "t:Thing"}, "mailed": {"attribute": "t:m"},
               "expires": {"attribute": "t:e"}},
    )
    with pytest.raises(PackValidationError, match="also a literal in the rule's own body"):
        validate_pack(conventional_pack([offender]))


def test_a_sequence_number_that_echoes_a_concluded_amount_is_refused():
    offender = rule(
        "TEST-FEE-75",
        then={
            "entity": "e",
            "attribute": "t:x",
            "value": {"kind": "money", "amount": "75.00", "currency": "USD"},
        },
    )
    with pytest.raises(PackValidationError, match="also a literal in the rule's own body"):
        validate_pack(conventional_pack([offender]))


def test_the_default_slot_zero_is_exempt_from_the_echo_check():
    """`-00` is the default-rule slot repo-wide, and a default very often
    concludes zero; that coincidence carries no claim about the law."""
    validate_pack(
        conventional_pack(
            [
                rule(
                    "TEST-DEF-00",
                    then={
                        "entity": "e",
                        "attribute": "t:x",
                        "value": {"kind": "money", "amount": "0.00", "currency": "USD"},
                    },
                )
            ]
        )
    )


def test_a_pack_without_an_id_prefix_is_not_checked():
    """Declaring `idPrefix` is how a pack opts in. An adopter porting an
    existing rulebase is not forced to rename ids it can no longer rename."""
    pack = conventional_pack([rule("legacy_rule_00017")])
    del pack["pack"]["idPrefix"]
    validate_pack(pack)


def test_a_malformed_id_prefix_is_refused():
    with pytest.raises(PackValidationError, match="pack.idPrefix must be uppercase"):
        validate_pack(conventional_pack([rule("TEST-DEF-00")], prefix="Rec-2"))
