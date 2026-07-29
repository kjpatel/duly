"""Jurisdiction-scoped rules at equal priority are not ambiguous when their
equality guards contradict on the same bound attribute."""

import copy

import pytest
import yaml
from pathlib import Path

from duly_kernel.ir import PackValidationError, validate_pack

REPO = Path(__file__).resolve().parents[2]
NY_PACK = yaml.safe_load((REPO / "kernel/tests/fixtures/ny-pack.yaml").read_text())


def _fl_variant(ny_rule):
    fl = copy.deepcopy(ny_rule)
    fl["id"] = "FL-NR-120"
    fl["when"] = [w.replace('"US-NY"', '"US-FL"') for w in fl["when"]]
    fl["then"]["value"] = {"kind": "decimal", "expr": "120"}
    return fl


def test_state_scoped_equal_priority_rules_are_not_ambiguous():
    pack = copy.deepcopy(NY_PACK)
    ny_45 = next(r for r in pack["rules"] if r["id"] == "NY-NR-45")
    pack["rules"].append(_fl_variant(ny_45))
    validate_pack(pack)  # must not raise


def test_same_guard_literal_is_still_ambiguous():
    pack = copy.deepcopy(NY_PACK)
    ny_45 = next(r for r in pack["rules"] if r["id"] == "NY-NR-45")
    dup = copy.deepcopy(ny_45)
    dup["id"] = "NY-NR-45-DUP"
    pack["rules"].append(dup)
    with pytest.raises(PackValidationError, match="ambiguous"):
        validate_pack(pack)


def test_guard_on_different_attributes_does_not_prove_disjoint():
    pack = copy.deepcopy(NY_PACK)
    ny_45 = next(r for r in pack["rules"] if r["id"] == "NY-NR-45")
    other = copy.deepcopy(ny_45)
    other["id"] = "NY-NR-45-OTHER"
    # Guard on a different attribute entirely: not provably disjoint.
    other["given"] = {
        "notice": {"entityType": "nc:TerminationNotice"},
        "ground": {"attribute": "nc:terminationGround"},
    }
    other["when"] = ['ground == "Nonpayment"']
    with pytest.raises(PackValidationError, match="ambiguous"):
        validate_pack(pack | {"rules": pack["rules"] + [other]})
