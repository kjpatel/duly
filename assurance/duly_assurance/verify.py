"""Replay verifier: python -m duly_assurance verify [--golden golden].

For every case in the golden corpus, re-adjudicate from the committed facts
and pack, recompute the DecisionReceipt, and byte-compare it against the
committed receipt: the recomputed receiptSha256 must equal the committed one
and the receipt documents must be identical. Per golden/README.md, exit
non-zero on the first mismatch, printing the case id and the differing
top-level fields. On success print "verified N cases" and exit 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "rulepacks").is_dir():
        return root
    return Path.cwd()


def _differing_fields(recomputed: dict, committed: dict) -> list[str]:
    keys = set(recomputed) | set(committed)
    return sorted(k for k in keys if recomputed.get(k) != committed.get(k))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance verify",
        description="Re-adjudicate every golden case and byte-compare receipts.",
    )
    parser.add_argument("--golden", default="golden", help="golden corpus directory (default: golden)")
    args = parser.parse_args(argv)

    golden = Path(args.golden)
    cases_dir = golden / "cases"
    receipts_dir = golden / "receipts"
    if not cases_dir.is_dir():
        print(f"no cases directory at {cases_dir}", file=sys.stderr)
        return 1

    root = repo_root()
    packs: dict[str, dict] = {}
    case_ids: set[str] = set()
    verified = 0

    for case_dir in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        case = yaml.safe_load((case_dir / "case.yaml").read_text())
        case_id = str(case["id"])
        case_ids.add(case_id)

        receipt_path = receipts_dir / f"{case_id}.json"
        if not receipt_path.is_file():
            print(f"MISMATCH {case_id}: missing golden receipt {receipt_path}")
            return 1
        committed = json.loads(receipt_path.read_text())

        fact_paths = sorted((case_dir / "facts").glob("*.json"))
        facts = [json.loads(p.read_text()) for p in fact_paths]

        pack_rel = str(case["pack"])
        if pack_rel not in packs:
            packs[pack_rel] = yaml.safe_load((root / pack_rel).read_text())

        try:
            recomputed = adjudicate(
                facts,
                packs[pack_rel],
                str(case["asOfEffective"]),
                str(case["asOfKnowledge"]),
                str(case["question"]),
            )
        except AdjudicationError as exc:
            print(f"MISMATCH {case_id}: re-adjudication failed: {exc}")
            return 1

        if (
            recomputed["receiptSha256"] != committed.get("receiptSha256")
            or recomputed != committed
        ):
            fields = _differing_fields(recomputed, committed)
            print(f"MISMATCH {case_id}: differing fields: {', '.join(fields)}")
            return 1
        verified += 1

    orphans = sorted(p.stem for p in receipts_dir.glob("*.json") if p.stem not in case_ids)
    if orphans:
        print(f"MISMATCH: receipts without cases: {', '.join(orphans)}")
        return 1

    print(f"verified {verified} cases")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
