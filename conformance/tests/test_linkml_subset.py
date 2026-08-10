"""The subset parser: what it interprets, and that it fails loudly at load
time on anything outside the subset (never silently at check time).

Everything here is toolkit. The constructs are exercised on the synthetic
`toy_schema`, and the one test that needs a *directory* of ontologies reads the
toolkit's own registry under `fixtures/ontology/`. What the two committed
teaching ontologies happen to contain — their names, their five mortgage
namespaces — is asserted in `examples/tests/test_example_conformance.py` and
moves with them.
"""

import pytest
from conformancetest_helpers import FIXTURE_ONTOLOGIES, toy_schema

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


def test_a_registry_directory_loads_as_name_version_refs():
    """`load_repo_registry` walks `<name>/<version>.yaml` and pins exactly.

    On the fixture registry, whose single ontology is enough to state the
    loader's whole contract: the directory name becomes the ontology name, the
    file stem becomes the version, `refs()` renders them as `name@version`, and
    `get` is an exact match rather than a nearest one.
    """
    registry = load_repo_registry(FIXTURE_ONTOLOGIES)
    assert registry.refs() == ["duly-fixture@0.1.0"]
    fixture = registry.get("duly-fixture", "0.1.0")
    assert fixture is not None
    assert set(fixture.classes) == {"fx:Widget"}
    # Version pinning is exact — a near miss is a miss, not a fallback.
    assert registry.get("duly-fixture", "0.2.0") is None
    assert registry.get("duly-fixtures", "0.1.0") is None
