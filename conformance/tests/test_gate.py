"""The conformance checks: every rejection is loud and names the fact, the
ontology reference, and what failed; a conforming fact passes clean."""

import pytest
from conformancetest_helpers import toy_fact, toy_schema

from duly_conformance import (
    FactNonconformantError,
    OntologyRegistry,
    assert_conformant,
    check_fact,
    parse_ontology,
)


@pytest.fixture()
def registry():
    return OntologyRegistry([parse_ontology(toy_schema())])


def codes(issues):
    return [i.code for i in issues]


def test_conforming_fact_passes(registry):
    assert check_fact(toy_fact(), registry) == []
    assert_conformant(toy_fact(), registry)  # does not raise


def test_unknown_ontology_names_known_registry(registry):
    fact = toy_fact(schemaRef={"ontology": "mystery", "version": "0.1.0"})
    issues = check_fact(fact, registry)
    assert codes(issues) == ["unknown_ontology"]
    assert "mystery@0.1.0" in issues[0].message
    assert "toy@0.1.0" in issues[0].message  # says what IS known


def test_version_pin_is_exact(registry):
    fact = toy_fact(schemaRef={"ontology": "toy", "version": "0.1.1"})
    issues = check_fact(fact, registry)
    assert codes(issues) == ["unknown_ontology"]
    assert "exact" in issues[0].message


def test_unknown_entity_type(registry):
    fact = toy_fact(entity={"id": "x", "type": "toy:Gizmo"})
    issues = check_fact(fact, registry)
    assert "unknown_entity_type" in codes(issues)
    assert "toy:Gizmo" in issues[0].message


def test_misspelled_attribute_suggests_the_real_one(registry):
    fact = toy_fact(attribute="toy:madeOm")
    issues = check_fact(fact, registry)
    assert codes(issues) == ["unknown_attribute"]
    assert "did you mean 'toy:madeOn'" in issues[0].message
    assert issues[0].fact_id == "urn:duly:fact:sha256:0000"
    assert issues[0].ontology_ref == "toy@0.1.0"


def test_attribute_on_wrong_class_is_misattachment(registry):
    fact = toy_fact(attribute="toy:label")  # declared on Crate, not Widget
    issues = check_fact(fact, registry)
    assert codes(issues) == ["misattached_attribute"]
    assert "toy:Crate" in issues[0].message


def test_wrong_value_kind(registry):
    fact = toy_fact(value={"kind": "string", "value": "2026-01-01"})
    issues = check_fact(fact, registry)
    assert codes(issues) == ["kind_mismatch"]
    assert "declared date" in issues[0].message


def test_code_outside_enum(registry):
    fact = toy_fact(
        attribute="toy:color",
        value={"kind": "code", "value": "Chartreuse", "codeSystem": "toy/colors"},
    )
    issues = check_fact(fact, registry)
    assert codes(issues) == ["code_not_permitted"]
    assert "Blue, Red" in issues[0].message


def test_wrong_code_system(registry):
    fact = toy_fact(
        attribute="toy:color",
        value={"kind": "code", "value": "Red", "codeSystem": "toy/hues"},
    )
    issues = check_fact(fact, registry)
    assert codes(issues) == ["code_system_mismatch"]


def test_open_code_set_checks_identity_not_membership(registry):
    ok = toy_fact(
        attribute="toy:state",
        value={"kind": "code", "value": "US-ZZ", "codeSystem": "iso-3166-2"},
    )
    assert check_fact(ok, registry) == []  # membership not vendored
    bad = toy_fact(
        attribute="toy:state",
        value={"kind": "code", "value": "US-NY", "codeSystem": "fips"},
    )
    assert codes(check_fact(bad, registry)) == ["code_system_mismatch"]


def test_money_kind(registry):
    ok = toy_fact(attribute="toy:price", value={"kind": "money", "amount": "9.99", "currency": "USD"})
    assert check_fact(ok, registry) == []
    bad = toy_fact(attribute="toy:price", value={"kind": "decimal", "value": "9.99"})
    assert codes(check_fact(bad, registry)) == ["kind_mismatch"]


def test_assert_conformant_raises_with_every_issue(registry):
    fact = toy_fact(attribute="toy:madeOm")
    with pytest.raises(FactNonconformantError) as exc:
        assert_conformant(fact, registry)
    assert exc.value.issues and "unknown_attribute" in str(exc.value)
