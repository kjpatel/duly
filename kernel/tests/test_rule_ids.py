"""The rule-id convention, its exemptions, and the packs that opt into it.

    PATH="/opt/homebrew/bin:$PATH" uv run pytest kernel/tests/test_rule_ids.py -q
"""

from pathlib import Path

import pytest
import yaml

from duly_kernel.ir import PackValidationError, validate_pack
from duly_kernel.rule_ids import (
    GRANDFATHERED_RULE_ID_COUNT,
    GRANDFATHERED_RULE_IDS,
    rule_id_problem,
)

RULEPACKS = Path(__file__).resolve().parents[2] / "rulepacks"


def committed_packs():
    """EXAMPLE CONTENT: the four tests below sweep the committed teaching
    packs and their grandfathered-id audit trail — their subject moves under
    `examples/` and they move with it. The convention unit tests above them
    are toolkit (synthetic packs) and stay. The list-then-assert shape is the
    vacuous-glob guard: an empty directory must fail these tests loudly, not
    let two of them pass over nothing while the other two fail confusingly.
    """
    packs = [
        (pack_file, yaml.safe_load(pack_file.read_text(encoding="utf-8")))
        for pack_file in sorted(RULEPACKS.glob("*/pack.yaml"))
    ]
    assert packs, "no committed packs found; these tests sweep example content"
    return packs


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


# --- The grandfathered ids -------------------------------------------------


def test_every_committed_pack_declares_its_id_family():
    for pack_file, pack in committed_packs():
        assert pack["pack"].get("idPrefix"), pack_file.name


def test_the_grandfather_list_is_exactly_the_ids_that_predate_the_convention():
    """Every committed id is listed, nothing else is, and the count is pinned.

    The list is the exemption's whole audit trail: it may only grow in a diff
    that also changes this count.
    """
    committed = {
        pack["pack"]["name"]: {r["id"] for r in pack["rules"]}
        for _, pack in committed_packs()
    }
    assert set(GRANDFATHERED_RULE_IDS) == set(committed)
    for name, ids in committed.items():
        assert GRANDFATHERED_RULE_IDS[name] == frozenset(ids), name
    total = sum(len(ids) for ids in GRANDFATHERED_RULE_IDS.values())
    assert total == GRANDFATHERED_RULE_ID_COUNT == 46


def test_seventeen_of_the_grandfathered_ids_would_fail_the_convention_today():
    """The honest measure of what the exemption is carrying.

    Every one of these is a receipt-visible id that cannot be renamed: a
    jurisdiction-first prefix, a year, a statute section, or a day count.
    """
    non_conforming = {}
    for _, pack in committed_packs():
        prefix = pack["pack"]["idPrefix"]
        for r in pack["rules"]:
            problem = rule_id_problem(r, prefix)
            if problem:
                non_conforming[r["id"]] = problem
    assert set(non_conforming) == {
        # county-recording-us — jurisdiction-first, and two encoded lengths
        "CA-TOPSPACE-25",
        "AZ-TOPMARGIN-20",
        "CA-DTT-11933",
        "CA-SB2-75",
        "CA-SB2-EXEMPT-DTT",
        # notarization-ron-us-states — jurisdiction-first, year-suffixed
        "VA-RON-2012",
        "TX-RON-2018",
        "FL-RON-2020",
        "NY-RON-2023",
        "CA-RON-2030",
        # termination-notice-us-states — jurisdiction-first, day counts
        "NY-NR-45-LEGACY",
        "NY-NR-45",
        "NY-NR-NONPAY-15",
        "FL-NR-120",
        "FL-NONPAY-10",
        "CA-NR-75",
        "CA-NONPAY-10",
    }
    assert len(non_conforming) == 17


def test_the_committed_packs_still_load():
    """Grandfathering is not a promise unless the packs actually validate."""
    for pack_file, _ in committed_packs():
        from duly_kernel.ir import load_pack

        load_pack(pack_file)
