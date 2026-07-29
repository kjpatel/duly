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
