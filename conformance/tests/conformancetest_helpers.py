"""Shared fixtures for the conformance suite (module, not conftest.py —
repo convention: test dirs have no __init__.py, so identically named
conftest files across suites would collide)."""

from __future__ import annotations

import copy
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ONTOLOGIES_DIR = REPO / "examples" / "ontologies"

# A minimal, self-contained schema exercising every construct the subset
# interprets: builtin ranges, a duly:money type, a closed enum with a code
# system, and an open external code set.
TOY_SCHEMA = {
    "id": "https://example.org/toy/0.1.0",
    "name": "toy",
    "version": "0.1.0",
    "prefixes": {
        "linkml": "https://w3id.org/linkml/",
        "duly": "https://duly.dev/spec/v0/vocab#",
        "toy": "https://example.org/toy#",
    },
    "types": {
        "Money": {"typeof": "string", "uri": "duly:money"},
    },
    "enums": {
        "Color": {
            "annotations": {"codeSystem": "toy/colors"},
            "permissible_values": {"Red": {}, "Blue": {}},
        },
        "Subdivision": {
            "annotations": {"codeSystem": "iso-3166-2", "openCodeSet": True},
        },
    },
    "classes": {
        "Widget": {
            "class_uri": "toy:Widget",
            "attributes": {
                "color": {"slot_uri": "toy:color", "range": "Color"},
                "madeOn": {"slot_uri": "toy:madeOn", "range": "date"},
                "price": {"slot_uri": "toy:price", "range": "Money"},
                "state": {"slot_uri": "toy:state", "range": "Subdivision"},
                "heavy": {"slot_uri": "toy:heavy", "range": "boolean"},
            },
        },
        "Crate": {
            "class_uri": "toy:Crate",
            "attributes": {
                "label": {"slot_uri": "toy:label", "range": "string"},
            },
        },
    },
}


def toy_schema() -> dict:
    return copy.deepcopy(TOY_SCHEMA)


def toy_fact(**overrides) -> dict:
    fact = {
        "id": "urn:duly:fact:sha256:0000",
        "contentHash": "0000",
        "caseId": "case:toy:1",
        "entity": {"id": "widget:1", "type": "toy:Widget"},
        "attribute": "toy:madeOn",
        "value": {"kind": "date", "value": "2026-01-01"},
        "grounding": {"kind": "attestation", "actor": "t", "channel": "test", "at": "2026-01-01T00:00:00Z"},
        "assertion": {"kind": "machine", "at": "2026-01-01T00:00:00Z", "extractor": {"name": "t", "version": "0"}},
        "confidence": {"score": 1.0, "method": "raw"},
        "recordedAt": "2026-01-01T00:00:00Z",
        "status": "asserted",
        "schemaRef": {"ontology": "toy", "version": "0.1.0"},
    }
    fact.update(overrides)
    return fact
