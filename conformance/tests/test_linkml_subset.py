"""The subset parser: what it interprets, and that it fails loudly at load
time on anything outside the subset (never silently at check time)."""

import pytest
from conformancetest_helpers import ONTOLOGIES_DIR, toy_schema

from duly_conformance import OntologySubsetError, load_repo_registry, parse_ontology


def test_parses_kinds_and_enums():
    ontology = parse_ontology(toy_schema())
    widget = ontology.classes["toy:Widget"]
    assert widget.slots["toy:madeOn"].kind == "date"
    assert widget.slots["toy:price"].kind == "money"
    assert widget.slots["toy:heavy"].kind == "boolean"
    color = widget.slots["toy:color"]
    assert color.kind == "code"
    assert color.enum.code_system == "toy/colors"
    assert color.enum.values == {"Red", "Blue"}
    state = widget.slots["toy:state"]
    assert state.kind == "code"
    assert state.enum.open_code_set
    assert ontology.classes["toy:Crate"].slots["toy:label"].kind == "string"


def test_find_slot_scans_all_classes():
    ontology = parse_ontology(toy_schema())
    cls, slot = ontology.find_slot("toy:label")
    assert cls.curie == "toy:Crate" and slot.kind == "string"
    assert ontology.find_slot("toy:nonesuch") is None


def test_unresolvable_range_is_a_load_error():
    doc = toy_schema()
    doc["classes"]["Widget"]["attributes"]["weird"] = {
        "slot_uri": "toy:weird",
        "range": "integer",  # real LinkML, but outside the enforced subset
    }
    with pytest.raises(OntologySubsetError, match="range 'integer'"):
        parse_ontology(doc)


def test_missing_slot_uri_is_a_load_error():
    doc = toy_schema()
    del doc["classes"]["Widget"]["attributes"]["color"]["slot_uri"]
    with pytest.raises(OntologySubsetError, match="no\nslot_uri|no slot_uri|slot_uri"):
        parse_ontology(doc)


def test_missing_class_uri_is_a_load_error():
    doc = toy_schema()
    del doc["classes"]["Widget"]["class_uri"]
    with pytest.raises(OntologySubsetError, match="class_uri"):
        parse_ontology(doc)


def test_undeclared_prefix_is_a_load_error():
    doc = toy_schema()
    doc["classes"]["Widget"]["class_uri"] = "mystery:Widget"
    with pytest.raises(OntologySubsetError, match="undeclared prefix"):
        parse_ontology(doc)


def test_valueless_closed_enum_is_a_load_error():
    doc = toy_schema()
    doc["enums"]["Color"]["permissible_values"] = {}
    with pytest.raises(OntologySubsetError, match="openCodeSet"):
        parse_ontology(doc)


def test_type_with_unknown_uri_is_a_load_error():
    doc = toy_schema()
    doc["types"]["Money"]["uri"] = "duly:quaternion"
    with pytest.raises(OntologySubsetError, match="duly value kind"):
        parse_ontology(doc)


def test_repo_registry_loads_both_committed_ontologies():
    registry = load_repo_registry(ONTOLOGIES_DIR)
    assert registry.refs() == ["duly-mortgage-closing@0.1.0", "duly-starter-notice@0.1.0"]
    mortgage = registry.get("duly-mortgage-closing", "0.1.0")
    # One artifact spans all five mortgage namespaces.
    assert {c.split(":", 1)[0] for c in mortgage.classes} == {"trid", "ron", "pkg", "resc", "rec"}
    # Version pinning is exact.
    assert registry.get("duly-mortgage-closing", "0.2.0") is None
