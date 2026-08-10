#!/usr/bin/env python3
"""The failure the conformance gate kills, demonstrated on committed data.

Before this gate, an adapter emitting a misspelled attribute or the wrong
value kind sailed through ingestion and surfaced only as a rule silently
failing to bind — the quiet cousin of confident wrongness. This script
loads the committed ontology registry (ontologies/), passes a committed
span-grounded starter fact through the gate, then mutates it three ways —
a misspelled attribute, a wrong value kind, an out-of-enum code — and
shows each rejection naming the fact, the pinned ontology + version, and
exactly what failed.

Run from the repo root:

    uv run python spec/conformance_gate_demo.py

Pure stdlib + yaml, like the gate itself (spec/ontology-conformance.md
explains why the enforcing validator is not linkml-runtime). Hashes are
deliberately NOT recomputed for the mutants: run integrity (hashes,
spans) is the envelope's job — the gate catches what a correctly-hashed,
correctly-spanned, honestly-produced fact can still get wrong.
"""
from __future__ import annotations

import copy
import json
import pathlib

from duly_conformance import check_fact, load_repo_registry

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACT_PATH = ROOT / "examples/starters/trid/facts/fact-cd-fee-type.json"


def show(label: str, fact: dict, registry) -> None:
    issues = check_fact(fact, registry)
    print(f"{label}")
    print(f"     attribute={fact['attribute']!r}  value={fact['value']!r}")
    if not issues:
        ref = fact["schemaRef"]
        print(f"     PASS — conforms to {ref['ontology']}@{ref['version']}\n")
        return
    for issue in issues:
        print(f"     REJECTED [{issue.code}]")
        print(f"       fact:     {issue.fact_id}")
        print(f"       ontology: {issue.ontology_ref}")
        print(f"       reason:   {issue.message}")
    print()


def main() -> int:
    registry = load_repo_registry(ROOT / "examples" / "ontologies")
    print(f"registry: {', '.join(registry.refs())}\n")

    fact = json.loads(FACT_PATH.read_text(encoding="utf-8"))
    show("1. the committed fact, as extracted", fact, registry)

    misspelled = copy.deepcopy(fact)
    misspelled["attribute"] = "trid:feeTyp"
    show("2. a misspelled attribute (the silent-bind failure, made loud)", misspelled, registry)

    wrong_kind = copy.deepcopy(fact)
    wrong_kind["attribute"] = "trid:actualAmountAtClosing"
    wrong_kind["value"] = {"kind": "decimal", "value": "1450.00"}
    show("3. the wrong value kind (decimal where the ontology says money)", wrong_kind, registry)

    out_of_enum = copy.deepcopy(fact)
    out_of_enum["value"] = dict(out_of_enum["value"], value="TransferTaks")
    show("4. an out-of-enum code value", out_of_enum, registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
