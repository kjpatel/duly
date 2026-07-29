"""CLI for the duly reference kernel.

    uv run python -m duly_kernel \
        --facts spec/examples \
        --pack kernel/tests/fixtures/ny-pack.yaml \
        --asof 2026-07-25 \
        --question nc:noticeCompliant

Prints the DecisionReceipt JSON to stdout. Never reads the wall clock:
--asof is required, and --asof-knowledge defaults to the same date at
23:59:59Z.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import adjudicate
from .engine import AdjudicationError, normalize_point
from .expr import ExprError, format_datetime
from .ir import PackValidationError, load_pack


def _load_facts(directory: Path) -> list[dict]:
    facts = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" in doc:
            continue  # a DecisionReceipt, not a fact
        facts.append(doc)
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_kernel",
        description="Adjudicate a case with the duly reference kernel.",
    )
    parser.add_argument("--facts", required=True, help="Directory of GroundedFact JSON files.")
    parser.add_argument("--pack", required=True, help="Rule pack YAML file.")
    parser.add_argument("--asof", required=True, help="Effective asOf (ISO date or datetime).")
    parser.add_argument(
        "--asof-knowledge",
        default=None,
        help="Knowledge asOf (ISO date or datetime). Default: --asof at 23:59:59Z.",
    )
    parser.add_argument("--question", required=True, help="Decision attribute CURIE.")
    args = parser.parse_args(argv)

    facts_dir = Path(args.facts)
    if not facts_dir.is_dir():
        parser.error(f"--facts: not a directory: {facts_dir}")

    if args.asof_knowledge is not None:
        knowledge = args.asof_knowledge
    else:
        knowledge = format_datetime(normalize_point(args.asof, end_of_day=True))

    try:
        pack = load_pack(args.pack)
        facts = _load_facts(facts_dir)
        receipt = adjudicate(facts, pack, args.asof, knowledge, args.question)
    except (PackValidationError, AdjudicationError, ExprError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    json.dump(receipt, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
