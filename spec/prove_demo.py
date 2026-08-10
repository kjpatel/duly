#!/usr/bin/env python3
"""A solver reads the rulebase, and says what the pack validator cannot.

`python -m duly_assurance prove` encodes a rule pack as SMT and answers three
questions the kernel's syntactic pack validator answers narrowly or not at
all: can two same-priority rules both fire, is any input region left with no
conclusion, and do two packs decide alike everywhere. This script runs all
three, on committed artifacts.

The claim being demonstrated is not "Z3 works". It is that the reasoning a
rule author does in a code comment — "these two can never both fire, but the
validator cannot see it, so I separated the priorities" — is a proof
obligation, and a proof obligation can be discharged mechanically instead of
asserted in prose.

Nothing here touches adjudication. `prove` is validation-time only: no
solver output reaches a receipt, and running this script changes no decision.

Run from the repo root:

    uv run --with z3-solver python spec/prove_demo.py

Design decisions and their rationale: spec/pack-verification.md. Determinism
note: witnesses are normalized against a static candidate ladder drawn from
the pack's own vocabulary, so this script prints the same bytes on every run
— like every other example in this repo, and for the same reason.
"""
from __future__ import annotations

import copy
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from duly_assurance.prove import (  # noqa: E402
    NOT_PROVED,
    OUT_OF_FRAGMENT,
    PROVED_DISJOINT,
    analyze_pack,
    equivalence_report,
)
from duly_conformance.registry import load_repo_registry  # noqa: E402
from duly_kernel.ir import PackValidationError, load_pack, validate_pack  # noqa: E402

ESIGN = ROOT / "examples/rulepacks/esign-closing-package/pack.yaml"
RECORDING = ROOT / "examples/rulepacks/county-recording-us/pack.yaml"
TILA = ROOT / "examples/rulepacks/tila-rescission-us-federal/pack.yaml"
TRID = ROOT / "examples/rulepacks/trid-fee-tolerance-us-federal/pack.yaml"
DMN_PACK = ROOT / "examples/dmn/trid-fee-tolerance.pack.yaml"


def rule(text: str) -> None:
    print()
    print(text)
    print("-" * len(text))


def witness(rows, indent="       ") -> None:
    width = max((len(label) for label, _ in rows), default=0)
    for label, value in rows:
        print(f"{indent}{label.ljust(width)}  {value}")


# ---------------------------------------------------------------------------
# A toy pack whose rules genuinely overlap.
#
# Committed packs cannot demonstrate this: `validate_pack` refuses any
# same-priority pair it cannot prove disjoint and that carries no `overrides`,
# so an unresolved overlap never reaches a pack.yaml. The toy below is what
# such a pack would look like — two rules split by a numeric range that shares
# its endpoint.
# ---------------------------------------------------------------------------

OVERLAPPING = {
    "pack": {"name": "demo-overlapping-thresholds", "version": "1.0.0"},
    "decisions": [
        {"attribute": "toy:tier", "entityType": "toy:Account",
         "question": "Which fee tier applies?"}
    ],
    "rules": [
        {
            "id": "TIER-STANDARD",
            "version": "1.0.0",
            "priority": 100,
            "citation": {"text": "Demo fee schedule, standard tier"},
            "effectiveFrom": "2020-01-01",
            "given": {
                "account": {"entityType": "toy:Account"},
                "balance": {"attribute": "toy:balance"},
            },
            "when": ["balance <= 10000"],
            "then": {"entity": "account", "attribute": "toy:tier",
                     "value": {"kind": "string", "value": "Standard"}},
        },
        {
            "id": "TIER-PREMIUM",
            "version": "1.0.0",
            "priority": 100,
            "citation": {"text": "Demo fee schedule, premium tier"},
            "effectiveFrom": "2020-01-01",
            "given": {
                "account": {"entityType": "toy:Account"},
                "balance": {"attribute": "toy:balance"},
            },
            "when": ["balance >= 10000"],
            "then": {"entity": "account", "attribute": "toy:tier",
                     "value": {"kind": "string", "value": "Premium"}},
        },
    ],
}


def main() -> int:
    registry = load_repo_registry(ROOT / "examples" / "ontologies")
    failures: list[str] = []

    # -----------------------------------------------------------------------
    rule("1. disjointness — the eSign pack, rule pair by rule pair")

    esign = load_pack(ESIGN)
    report = analyze_pack(ESIGN.relative_to(ROOT), esign, registry)
    print(f"  {report.name} {report.version}, {len(report.reachability)} rules")
    print(f"  {len(report.pairs)} pairs of same-priority rules concluding one attribute\n")
    for pair in report.pairs:
        print(f"    {pair.verdict:<16} {pair.left} / {pair.right}")
        print(f"      {pair.attribute} at priority {pair.priority}")
        if pair.verdict == PROVED_DISJOINT:
            continue
        print(f"      {pair.reason}")
        witness(pair.witness)
        if pair.overrides:
            print(f"      resolved: {pair.overrides}")

    proved = [p for p in report.pairs if p.verdict == PROVED_DISJOINT]
    print(f"\n  {len(proved)} of {len(report.pairs)} PROVED-DISJOINT.")
    print("  The rest is not a defect. PKG-NOTE-30 routes every promissory note to")
    print("  wet ink; PKG-NOTE-31 routes a registered eNote to the eVault channel.")
    print("  A registered eNote is a promissory note, so both fire — which is")
    print("  exactly why the author wrote `overrides: [PKG-NOTE-30]`. The prover")
    print("  reports the overlap and the exception that resolves it, rather than")
    print("  reporting a proof it does not have.")
    if len(proved) != 4 or report.fatal:
        failures.append("the eSign pack's expected verdicts changed")

    # -----------------------------------------------------------------------
    rule("2. disjointness — a pack whose rules really do overlap")

    try:
        validate_pack(OVERLAPPING)
    except PackValidationError as exc:
        print("  The kernel refuses to load it:\n")
        print(f"    {exc}\n")
        print("  True, and unhelpfully general: `validate_pack` says it *cannot prove*")
        print("  disjointness, not that the rules overlap. Those are different claims,")
        print("  and an author who believes the first is the second will add an")
        print("  `overrides` and move on. Here is the second claim:\n")
    else:  # pragma: no cover - the demo pack must be refused
        failures.append("the overlapping demo pack was accepted by validate_pack")

    toy = analyze_pack(pathlib.Path("<demo>"), OVERLAPPING, registry)
    for pair in toy.pairs:
        print(f"    {pair.verdict:<16} {pair.left} / {pair.right}")
        print(f"      {pair.reason}")
        witness(pair.witness)
    print("\n  One number, and the rulebase is ambiguous there. That is the")
    print("  difference between 'unproven' and 'wrong'.")
    if [p.verdict for p in toy.pairs] != [NOT_PROVED]:
        failures.append("the overlapping demo pack was not reported as NOT-PROVED")

    # -----------------------------------------------------------------------
    rule("3. disjointness the kernel cannot express at all")

    tila = analyze_pack(TILA.relative_to(ROOT), load_pack(TILA), registry, all_pairs=True)
    wanted = {("RESC-APP-01", "RESC-APP-02"), ("RESC-FUND-STAY", "RESC-FUND-EXP")}
    print("  Two comments in the TILA pack say, in effect, 'these can never both")
    print("  fire, but the validator only proves string-equality guards, so we")
    print("  separated the priorities'. Both claims are now checkable:\n")
    for pair in tila.pairs:
        if (pair.left, pair.right) in wanted:
            print(f"    {pair.verdict:<16} {pair.left} / {pair.right}  ({pair.attribute})")
    print("\n  The first is a boolean split (`dwelling == true` / `== false`).")
    print("  The second compares the evaluation date against a deadline the pack")
    print("  COMPUTES with add_business_days() over its own embedded calendar —")
    print("  so the solver walked the same 12 CFR 1026.2(a)(6) business days the")
    print("  kernel walks, and proved the two guards exclusive over all of them.")
    if not all(
        p.verdict == PROVED_DISJOINT
        for p in tila.pairs
        if (p.left, p.right) in wanted
    ):
        failures.append("the TILA pack's prose disjointness claims no longer hold")

    # -----------------------------------------------------------------------
    rule("4. coverage — which questions the rulebase cannot answer")

    recording = analyze_pack(RECORDING.relative_to(ROOT), load_pack(RECORDING), registry)
    for result in recording.coverage:
        if result.covered:
            print(f"    COVERED      {result.attribute}")
            continue
        print(f"    UNCOVERED    {result.attribute}")
        print(f"      {result.reason or 'no rule concludes it under this assignment'}")
        witness(result.witness)
    print("\n  county-recording-us documents this on the rule itself: 'An unknown")
    print("  jurisdiction gets NO recordability presumption at all.' The prover")
    print("  finds the region without being told, and names the input that reaches")
    print("  it. A pack that did NOT mean to have that hole would find out here.")
    if all(c.covered for c in recording.coverage):
        failures.append("the recording pack's documented coverage hole vanished")

    # -----------------------------------------------------------------------
    rule("5. equivalence — over the input space, not over a fixture list")

    trid, compiled = load_pack(TRID), load_pack(DMN_PACK)
    good = equivalence_report(trid, compiled, registry)
    print(f"  {good.name_a}  vs  {good.name_b}\n")
    for result in good.decisions:
        print(f"    decision  {result.verdict:<16} {result.attribute}")
    print(f"    trace     {good.trace.verdict:<16} "
          f"{good.trace.shared_rules} shared rule ids")
    print("\n  spec/dmn.md proves this over the committed fixtures and says so")
    print("  plainly: perturbing `> disclosed` to `>= disclosed` leaves the whole")
    print("  equivalence suite green, because no fixture puts the two amounts")
    print("  exactly equal. Perturb it and ask again:\n")

    bad = copy.deepcopy(compiled)
    for r in bad["rules"]:
        r["when"] = [
            c.replace("actual > disclosed", "actual >= disclosed")
            for c in (r.get("when") or [])
        ]
    perturbed = equivalence_report(trid, bad, registry)
    for result in perturbed.decisions:
        print(f"    decision  {result.verdict:<16} {result.attribute}")
    print(f"    trace     {perturbed.trace.verdict:<16} "
          f"{perturbed.trace.shared_rules} shared rule ids")
    for diff in perturbed.trace.differences:
        print(f"      differs: {diff}")
    witness(perturbed.trace.witness, indent="      ")
    print("\n  Caught — at the exact boundary the fixtures miss, and only there.")
    print("  Note which level caught it. The DECISIONS still agree: with the two")
    print("  amounts equal, the cure rule concludes `actual - disclosed`, which is")
    print("  the same 0.00 the default rule concludes. What changed is the receipt")
    print("  — which rule fired, and what it defeated. spec/dmn.md calls this 'a")
    print("  genuine semantic change', and it is; it is a change to the audit")
    print("  chain rather than to the answer, which is a distinction worth having.")
    if perturbed.trace.verdict != NOT_PROVED or perturbed.exit_code != 1:
        failures.append("the >= perturbation was no longer caught")
    if any(d.verdict != PROVED_DISJOINT for d in perturbed.decisions):
        failures.append("the >= perturbation now changes a decision")

    # -----------------------------------------------------------------------
    rule("6. what the prover declines to answer")

    print("  Every verdict is one of three, and the third is a first-class answer:\n")
    print(f"    {PROVED_DISJOINT:<16} the solver showed the guards cannot both hold")
    print(f"    {NOT_PROVED:<16} here is an assignment under which both fire")
    print(f"    {OUT_OF_FRAGMENT:<16} named construct is outside the encoding")
    print("\n  The fragment is booleans, numbers as reals, dates as bounded")
    print("  integers, strings and codes as finite domains resolved from the")
    print("  ontology, and the IR operators that encode faithfully. Money is")
    print("  encoded as its amount, so currency mismatch is NOT modeled; string")
    print("  ordering is refused rather than approximated by index order; a")
    print("  business-day count that is not a literal is refused rather than")
    print("  guessed. spec/pack-verification.md documents the encoding per")
    print("  operator, including the ones it declines.")
    print("\n  The rule is that an approximation only ever WIDENS the input space,")
    print("  so PROVED stays a proof. Where it cannot, the answer is")
    print(f"  {OUT_OF_FRAGMENT} and the reason names the construct.")

    print()
    if failures:
        for failure in failures:
            print(f"FAILED: {failure}")
        return 1
    print("Every claim above is checked by assurance/tests/test_prove*.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
