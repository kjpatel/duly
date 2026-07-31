import copy

import pytest

from duly_kernel.ir import PackValidationError, validate_pack


def minimal_rule(rid: str, attribute: str = "nc:x", priority: int = 0, **extra) -> dict:
    rule = {
        "id": rid,
        "version": "1.0.0",
        "priority": priority,
        "citation": {"text": "Test"},
        "effectiveFrom": "1900-01-01",
        "given": {"e": {"entityType": "nc:Thing"}},
        "then": {"entity": "e", "attribute": attribute, "value": {"kind": "boolean", "value": True}},
    }
    rule.update(extra)
    return rule


def minimal_pack(rules: list[dict]) -> dict:
    return {
        "pack": {"name": "test-pack", "version": "0.0.1"},
        "decisions": [{"attribute": "nc:x"}],
        "rules": rules,
    }


def test_valid_minimal_pack_passes():
    validate_pack(minimal_pack([minimal_rule("R-1")]))


def test_missing_pack_name():
    pack = minimal_pack([minimal_rule("R-1")])
    del pack["pack"]["name"]
    with pytest.raises(PackValidationError, match="pack.name"):
        validate_pack(pack)


def test_duplicate_rule_ids():
    with pytest.raises(PackValidationError, match="duplicate rule id"):
        validate_pack(minimal_pack([minimal_rule("R-1"), minimal_rule("R-1", priority=1)]))


def test_missing_effective_from():
    rule = minimal_rule("R-1")
    del rule["effectiveFrom"]
    with pytest.raises(PackValidationError, match="effectiveFrom"):
        validate_pack(minimal_pack([rule]))


def test_overrides_unknown_rule():
    rule = minimal_rule("R-1", overrides=["NOPE"])
    with pytest.raises(PackValidationError, match="unknown rule"):
        validate_pack(minimal_pack([rule]))


def test_bad_when_expression():
    rule = minimal_rule("R-1", when=["1 +"])
    with pytest.raises(PackValidationError, match="does not parse"):
        validate_pack(minimal_pack([rule]))


def test_derived_cycle_detected():
    a = minimal_rule("R-A", attribute="nc:a")
    a["given"]["dep"] = {"derived": "nc:b"}
    b = minimal_rule("R-B", attribute="nc:b")
    b["given"]["dep"] = {"derived": "nc:a"}
    with pytest.raises(PackValidationError, match="cycle in derived dependencies"):
        validate_pack(minimal_pack([a, b]))


def test_self_cycle_detected():
    a = minimal_rule("R-A", attribute="nc:a")
    a["given"]["dep"] = {"derived": "nc:a"}
    with pytest.raises(PackValidationError, match="cycle"):
        validate_pack(minimal_pack([a]))


def test_same_attribute_same_priority_ambiguity():
    a = minimal_rule("R-A", attribute="nc:x", priority=5)
    b = minimal_rule("R-B", attribute="nc:x", priority=5)
    with pytest.raises(PackValidationError, match="ambiguous pack"):
        validate_pack(minimal_pack([a, b]))


def test_same_priority_ok_when_one_overrides_the_other():
    a = minimal_rule("R-A", attribute="nc:x", priority=5)
    b = minimal_rule("R-B", attribute="nc:x", priority=5, overrides=["R-A"])
    validate_pack(minimal_pack([a, b]))


def test_same_attribute_different_priority_ok():
    a = minimal_rule("R-A", attribute="nc:x", priority=0)
    b = minimal_rule("R-B", attribute="nc:x", priority=10)
    validate_pack(minimal_pack([a, b]))


def test_then_entity_must_be_bound():
    rule = minimal_rule("R-1")
    rule["then"]["entity"] = "ghost"
    with pytest.raises(PackValidationError, match="then.entity"):
        validate_pack(minimal_pack([rule]))


# --- Decision phrasing (presentation metadata; spec/rule-ir.md) -------------


def phrased_pack(phrasing) -> dict:
    pack = minimal_pack([minimal_rule("R-1")])
    pack["decisions"][0]["phrasing"] = phrasing
    return pack


def test_a_decision_needs_no_phrasing_block():
    validate_pack(minimal_pack([minimal_rule("R-1")]))


def test_valid_phrasing_passes():
    validate_pack(
        phrased_pack(
            [
                {
                    "when": {"value": True, "abstained": "lowConfidence"},
                    "verdict": "Compliant",
                    "detail": "{caveat}",
                    "tone": "warn",
                },
                {
                    "when": {"fact": {"attribute": "noticeType", "equals": "Nonrenewal"}},
                    "verdict": "{value} days",
                    "detail": [
                        "{daysBetween:mailedOn,expiresOn} given, {derived:minDays|int} required",
                        "",
                    ],
                },
                {"verdict": "Midnight of {value|day}"},
            ]
        )
    )


def test_phrasing_case_needs_a_verdict():
    with pytest.raises(PackValidationError, match="missing 'verdict'"):
        validate_pack(phrased_pack([{"detail": "no headline"}]))


def test_phrasing_tone_vocabulary_is_closed():
    with pytest.raises(PackValidationError, match="tone must be one of"):
        validate_pack(phrased_pack([{"verdict": "Yes", "tone": "excited"}]))


def test_phrasing_rejects_unknown_placeholders():
    with pytest.raises(PackValidationError, match=r"\{amount\} is not a known placeholder"):
        validate_pack(phrased_pack([{"verdict": "{amount} due"}]))


def test_phrasing_rejects_an_unknown_format():
    with pytest.raises(PackValidationError, match="unknown format 'month'"):
        validate_pack(phrased_pack([{"verdict": "{value|month}"}]))


def test_phrasing_rejects_a_bare_fact_placeholder():
    with pytest.raises(PackValidationError, match="needs an attribute name"):
        validate_pack(phrased_pack([{"verdict": "{fact:}"}]))


def test_phrasing_rejects_unknown_guards():
    with pytest.raises(PackValidationError, match="unknown guard"):
        validate_pack(phrased_pack([{"when": {"weather": "sunny"}, "verdict": "Yes"}]))


def test_phrasing_fact_guard_must_test_something():
    with pytest.raises(PackValidationError, match="must test 'equals' or 'present'"):
        validate_pack(
            phrased_pack([{"when": {"fact": {"attribute": "x"}}, "verdict": "Yes"}])
        )


def test_phrasing_rejects_unknown_case_keys():
    with pytest.raises(PackValidationError, match="unknown key"):
        validate_pack(phrased_pack([{"verdict": "Yes", "colour": "blue"}]))
