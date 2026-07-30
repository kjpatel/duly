#!/usr/bin/env python3
"""A decision table becomes a rule pack, and adjudicates identically.

This script compiles dmn/examples/trid-fee-tolerance.dmn — the three TRID fee
tolerance rules re-authored as two DMN decision tables — and adjudicates the
committed starter facts in starters/trid/facts twice: once under the compiled
pack, once under the hand-written pack in rulepacks/. It prints the two
receipts side by side, then shows the compiler refusing a table it cannot
justify.

The claim being demonstrated is not "DMN works". It is that an authoring
surface a business analyst can read compiles into the same IR, executed by the
same kernel, producing the same defensible receipt — and that where a table
would compile into a rule duly cannot justify, the compiler stops.

Run from the repo root:

    uv run python spec/dmn_demo.py

Design decisions and their rationale: spec/dmn.md. Determinism note: the
evaluation point below is hard-coded, like every other example in this repo —
there is no wall clock anywhere in duly, including its demos.
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

from duly_dmn import DmnCompileError, compile_file
from duly_kernel.api import adjudicate

ROOT = pathlib.Path(__file__).resolve().parent.parent
DMN = ROOT / "dmn/examples/trid-fee-tolerance.dmn"
HAND_WRITTEN = ROOT / "rulepacks/trid-fee-tolerance-us-federal/pack.yaml"
FACTS_DIR = ROOT / "starters/trid/facts"
REFUSALS = ROOT / "dmn/examples/refusals"

AS_OF = "2026-03-15"
QUESTION = "trid:toleranceCureAmount"


def load_facts() -> list[dict]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(FACTS_DIR.glob("*.json"))
    ]


def money(value: dict) -> str:
    if value.get("kind") == "money":
        return f"{value['amount']} {value['currency']}"
    return f"{value.get('value')}"


COL = 50


def summarize(receipt: dict) -> list[str]:
    lines = [f"decision:   {money(receipt['decision']['value'])}"]
    for entry in receipt["rulesFired"]:
        lines.append(f"fired:      {entry['ruleId']}  priority {entry['priority']}")
        lines.append(f"            {entry['citation']['text']}")
        for defeated in entry.get("defeated") or []:
            lines.append(f"            defeats {defeated}")
    lines.append(f"facts used: {len(receipt['inputFacts'])}")
    lines.append(f"pack:       {receipt['rulePack']['name']}")
    lines.append(f"            @{receipt['rulePack']['version']}")
    return lines


def side_by_side(left: list[str], right: list[str]) -> None:
    for a, b in zip(left + [""] * len(right), right + [""] * len(left)):
        if not a and not b:
            continue
        print(f"  {a:<{COL}}  {b}".rstrip())


def main() -> int:
    facts = load_facts()
    print(f"facts:  {len(facts)} committed grounded facts from starters/trid/facts")
    print(f"asOf:   effective {AS_OF}")
    print(f"asking: {QUESTION}\n")

    print("1. compiling the decision tables")
    compiled = compile_file(DMN)
    print(f"     {DMN.relative_to(ROOT)}")
    print(f"     -> {len(compiled['decisions'])} decisions, {len(compiled['rules'])} rules: "
          f"{', '.join(r['id'] for r in compiled['rules'])}")
    hit_policies = {"toleranceCategory": "UNIQUE", "toleranceCureAmount": "FIRST"}
    for name, policy in hit_policies.items():
        print(f"     {name:<22} hitPolicy={policy}")
    print()

    hand = yaml.safe_load(HAND_WRITTEN.read_text(encoding="utf-8"))
    receipts = {}
    for label, pack in (("DMN-compiled", compiled), ("hand-written", hand)):
        receipts[label] = adjudicate(
            facts=facts,
            pack=pack,
            as_of_effective=AS_OF,
            as_of_knowledge=f"{AS_OF}T23:59:59Z",
            decision_attribute=QUESTION,
        )

    print("2. adjudicating the same facts under both packs\n")
    print(f"  {'DMN-COMPILED PACK':<{COL}}  HAND-WRITTEN PACK")
    print(f"  {'-' * COL}  {'-' * COL}")
    side_by_side(summarize(receipts["DMN-compiled"]), summarize(receipts["hand-written"]))
    print()

    dmn_r, hand_r = receipts["DMN-compiled"], receipts["hand-written"]
    same_value = dmn_r["decision"]["value"] == hand_r["decision"]["value"]
    same_fired = [e["ruleId"] for e in dmn_r["rulesFired"]] == [
        e["ruleId"] for e in hand_r["rulesFired"]
    ]
    same_defeats = [sorted(e.get("defeated") or []) for e in dmn_r["rulesFired"]] == [
        sorted(e.get("defeated") or []) for e in hand_r["rulesFired"]
    ]
    same_facts = sorted(f["id"] for f in dmn_r["inputFacts"]) == sorted(
        f["id"] for f in hand_r["inputFacts"]
    )
    print("3. equivalence")
    print(f"     decision value        {'MATCH' if same_value else 'DIFFER'}")
    print(f"     rules fired, in order {'MATCH' if same_fired else 'DIFFER'}")
    print(f"     defeat chains         {'MATCH' if same_defeats else 'DIFFER'}")
    print(f"     input facts consumed  {'MATCH' if same_facts else 'DIFFER'}")
    print("     rule priorities       DIFFER — derived from hit policy + row order,")
    print("                           not authored (spec/dmn.md M2)")
    print("     receipt hash          DIFFER — two packs, two identities:")
    print(f"                           {dmn_r['receiptSha256'][:16]}…  vs")
    print(f"                           {hand_r['receiptSha256'][:16]}…")
    print()

    print("4. what the compiler refuses")
    for path in sorted(REFUSALS.glob("*.dmn")):
        try:
            compile_file(path)
        except DmnCompileError as e:
            headline = e.message.split(". ")[0]
            print(f"     {path.name}")
            print(f"       [{e.klass}] {headline}.")
            print(f"       at {e.location.describe()}")
        else:  # pragma: no cover - the refusal examples must refuse
            print(f"     {path.name}: COMPILED — this example was supposed to fail")
            return 1
    print()

    ok = same_value and same_fired and same_defeats and same_facts
    print("EQUIVALENT" if ok else "NOT EQUIVALENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
