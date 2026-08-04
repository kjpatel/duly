"""CLI: python -m duly_whatif — solve a rule pack backwards.

    uv run --with z3-solver python -m duly_whatif --ontologies ontologies \
        --case golden/cases/notice-ny-0001 --free nc:noticeMailedDate --target true

Exit codes: 0 SATISFIABLE, 1 UNSATISFIABLE, 2 UNSUPPORTED (or a bad
invocation). A solver/kernel contradiction exits 3 and prints both artifacts:
it is not a query that failed, it is a defect.

`--ontologies` has no path default — an adopter's ontologies are not in duly's
directory — and is optional, since kinds can often be inferred from the pack.
When it is absent the report says so, because the answer is weaker in a way
nothing else in the output reveals.

Nothing here reaches a receipt. Like `prove`, this is an analysis tool beside
adjudication rather than inside it (spec/whatif.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from .query import (
    AS_OF,
    Query,
    SolverKernelContradiction,
    Unsupported,
    Z3_MISSING,
    solve,
)
from .render import render, report_json

EXIT_CONTRADICTION = 3


class BadOntologies(Exception):
    """`--ontologies` named a directory that is not there."""


def _resolve_ontologies(args) -> str | None:
    """The registry directory, from the flag or ``DULY_ONTOLOGIES``, or None.

    **No path default.** `ontologies` used to be one — duly's own directory,
    relative to the working directory — which is right in this repository and
    wrong everywhere else (M5 plan, finding A9).

    Unlike `duly_conformance`, absence is legal here: what-if works without a
    registry, inferring value kinds from the pack's own use. What it must not
    do is *stay quiet* about that, which is the half of A9 worth caring about
    — a weaker answer that looks identical to a stronger one. `solve()` puts
    the absence in the report's notes.
    """
    return args.ontologies or os.environ.get("DULY_ONTOLOGIES") or None


def _registry(path: str | None):
    """The ontology registry, when the deployment has one.

    Enums sharpen the answer — a closed `permissible_values` set turns a code
    symbol's domain from "these literals plus anything else" into exactly the
    permitted values.

    No path is a legal state. A path that *is* given and does not exist is
    not: it was typed on purpose, so silently proceeding without it hands
    back the weaker answer under the appearance of the stronger one.
    """
    if path is None:
        return None
    root = Path(path)
    if not root.is_dir():
        raise BadOntologies(
            f"no ontology registry at {path!r}. Pass an existing directory of "
            "<name>/<version>.yaml files, or omit --ontologies entirely — "
            "what-if runs without one and says so in its notes."
        )
    from duly_conformance.registry import load_repo_registry

    return load_repo_registry(root)


def _load_case(directory: Path) -> tuple[dict, list[dict], dict]:
    case = yaml.safe_load((directory / "case.yaml").read_text())
    facts = [
        json.loads(p.read_text()) for p in sorted((directory / "facts").glob("*.json"))
    ]
    # A case names its pack as a path, so something must say what that path is
    # relative to. Not this package's install location, which is the repository
    # only from a checkout — the defect `corpus.resolve_pack_path` already
    # fixed for verify/impact/generate. Shared rather than copied: a fourth
    # answer to one question is how the three came to disagree.
    from duly_assurance.corpus import resolve_pack_path

    pack_path = resolve_pack_path(str(case["pack"]), directory.resolve().parent.parent)
    pack = yaml.safe_load(pack_path.read_text())
    return case, facts, pack


def _decision_kind(pack: dict, attribute: str) -> tuple[str, str | None]:
    """(value kind, currency) the pack's own rules conclude for `attribute`.

    Read from the rules rather than from the ontology because it is the rules
    that have to produce the target: a target the pack cannot conclude is a
    question with no answer, and it should say so in those terms.
    """
    kinds, currency = set(), None
    for rule in pack["rules"]:
        if rule["then"]["attribute"] != attribute:
            continue
        spec = rule["then"]["value"]
        kinds.add(spec.get("kind"))
        currency = currency or spec.get("currency")
    if len(kinds) != 1:
        raise Unsupported(
            f"{attribute}: this pack concludes it with "
            f"{len(kinds)} different value kinds ({', '.join(sorted(map(str, kinds)))})"
            if kinds else
            f"no rule in this pack concludes {attribute}"
        )
    return next(iter(kinds)), currency


def _parse_target(text: str, kind: str, currency: str | None) -> dict:
    if text == "none":
        raise ValueError  # handled by the caller as "no decision at all"
    if kind == "boolean":
        if text not in ("true", "false"):
            raise Unsupported(
                f"--target for a boolean decision must be true or false, not {text!r}"
            )
        return {"kind": "boolean", "value": text == "true"}
    if kind in ("money", "decimal"):
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise Unsupported(
                f"--target for a {kind} decision must be a number, not {text!r}"
            ) from exc
        if kind == "money":
            return {"kind": "money", "amount": str(amount), "currency": currency or "USD"}
        return {"kind": "decimal", "value": str(amount)}
    if kind == "date":
        return {"kind": "date", "value": text}
    return {"kind": kind, "value": text}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m duly_whatif",
        description=(
            "Free one input and ask which of its values produce a target "
            "decision, plus the extremal one. Every answer is verified by "
            "running the kernel; nothing here reaches a receipt."
        ),
    )
    parser.add_argument(
        "--case", help="a case directory (case.yaml + facts/), e.g. golden/cases/trid-0001"
    )
    parser.add_argument("--facts", help="a directory of GroundedFact JSON files")
    parser.add_argument("--pack", help="pack.yaml path (required with --facts)")
    parser.add_argument("--as-of-effective", help="evaluation point (default: the case's)")
    parser.add_argument("--as-of-knowledge", help="knowledge point (default: the case's)")
    parser.add_argument("--decision", help="decision attribute CURIE (default: the case's)")
    parser.add_argument(
        "--free", required=True,
        help=f"the input to free: an attribute CURIE, or {AS_OF!r} for the evaluation point",
    )
    parser.add_argument(
        "--target",
        help="the decision value to reach ('true', '0.00', a date, a code); "
             "'none' means 'reach no decision at all'",
    )
    parser.add_argument(
        "--flip", action="store_true",
        help="target whatever today's decision is not (boolean decisions)",
    )
    parser.add_argument(
        "--extremal", choices=("max", "min"), default="max",
        help="which end of the satisfying range to report (default: max)",
    )
    parser.add_argument(
        "--scale", type=int,
        help="decimal grid for a freed decimal/money input (default: the scale "
             "the case's own value carries)",
    )
    parser.add_argument(
        "--ontologies",
        help="a directory of <name>/<version>.yaml ontologies; may also be "
             "given as DULY_ONTOLOGIES. No default, and optional — without one "
             "value kinds are inferred from the pack, which the report says.",
    )
    parser.add_argument("--verbose", action="store_true", help="print domain assumptions")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if bool(args.target) == bool(args.flip):
        print("give exactly one of --target and --flip", file=sys.stderr)
        return 2
    if not args.case and not (args.facts and args.pack):
        print("give --case, or both --facts and --pack", file=sys.stderr)
        return 2

    try:
        import z3  # noqa: F401
    except ImportError:
        print(Z3_MISSING, file=sys.stderr)
        return 2

    try:
        registry = _registry(_resolve_ontologies(args))
    except BadOntologies as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.case:
        case, facts, pack = _load_case(Path(args.case))
    else:
        case = {}
        facts = [json.loads(p.read_text()) for p in sorted(Path(args.facts).glob("*.json"))]
        pack = yaml.safe_load(Path(args.pack).read_text())

    decision = args.decision or case.get("question")
    effective = args.as_of_effective or case.get("asOfEffective")
    knowledge = args.as_of_knowledge or case.get("asOfKnowledge")
    missing = [
        name for name, value in
        (("--decision", decision), ("--as-of-effective", effective),
         ("--as-of-knowledge", knowledge))
        if not value
    ]
    if missing:
        print(f"missing and not supplied by the case: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        target = None
        if args.target and args.target != "none":
            kind, currency = _decision_kind(pack, str(decision))
            target = _parse_target(args.target, kind, currency)
        report = solve(
            Query(
                facts=facts, pack=pack, as_of_effective=str(effective),
                as_of_knowledge=str(knowledge), decision=str(decision),
                free=args.free, target=target, flip=args.flip,
                extremal=args.extremal, scale=args.scale,
            ),
            registry,
        )
    except Unsupported as exc:
        print(f"UNSUPPORTED: {exc}", file=sys.stderr)
        return 2
    except SolverKernelContradiction as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONTRADICTION

    print(report_json(report) if args.json else render(report, verbose=args.verbose))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
