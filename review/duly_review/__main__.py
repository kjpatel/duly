"""CLI for the duly review queue.

Usage:
    python -m duly_review init    --db PATH
    python -m duly_review items   --db PATH [--status open|resolved|dismissed] [--case CASE]
    python -m duly_review pairs   --db PATH
    python -m duly_review golden  --db PATH --facts-db PATH --item ID --pack PACK
                                  [--golden golden] [--case-id review-NNNN]

`golden` is the roadmap's "human corrections auto-become golden regression
cases" hook: it freezes a resolved item as a replayable golden case (see
duly_review.golden). Serving/mutating the queue over HTTP is the FastAPI
app's job (duly_review.api), not the CLI's.
"""

from __future__ import annotations

import argparse
import json
import sys

from duly_store.store import FactStore

from .golden import resolved_item_to_golden_case
from .queue import ReviewQueue, ReviewQueueError


def _cmd_init(args: argparse.Namespace) -> int:
    with ReviewQueue(args.db) as queue:
        queue.init_schema()
    print(f"initialized {args.db}")
    return 0


def _cmd_items(args: argparse.Namespace) -> int:
    with ReviewQueue(args.db) as queue:
        items = queue.items(status=args.status, case_id=args.case)
    json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def _cmd_pairs(args: argparse.Namespace) -> int:
    with ReviewQueue(args.db) as queue:
        pairs = queue.calibration_pairs()
    json.dump([list(p) for p in pairs], sys.stdout, indent=2, ensure_ascii=False)
    print()
    print(
        "note: censored sample — pairs label abstained (below-floor) facts only; "
        "fitting on them alone does not calibrate the full score range",
        file=sys.stderr,
    )
    return 0


def _cmd_golden(args: argparse.Namespace) -> int:
    with ReviewQueue(args.db) as queue, FactStore(args.facts_db) as store:
        result = resolved_item_to_golden_case(
            queue,
            store,
            args.item,
            pack_path=args.pack,
            golden_dir=args.golden,
            case_id=args.case_id,
        )
    print(f"wrote golden case {result['caseId']}: {result['caseDir']}")
    print(f"receipt: {result['receiptPath']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="duly_review", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the queue schema")
    p.add_argument("--db", required=True, help="path to the queue SQLite database")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("items", help="project queue items")
    p.add_argument("--db", required=True)
    p.add_argument("--status", default=None, choices=("open", "resolved", "dismissed"))
    p.add_argument("--case", default=None, help="filter by case id")
    p.set_defaults(func=_cmd_items)

    p = sub.add_parser("pairs", help="export calibration (score, correct) pairs")
    p.add_argument("--db", required=True)
    p.set_defaults(func=_cmd_pairs)

    p = sub.add_parser("golden", help="freeze a resolved item as a golden regression case")
    p.add_argument("--db", required=True, help="queue SQLite database")
    p.add_argument("--facts-db", required=True, help="fact store SQLite database")
    p.add_argument("--item", required=True, help="resolved review item id")
    p.add_argument("--pack", required=True, help="repo-relative pack path for case.yaml")
    p.add_argument("--golden", default="golden", help="golden corpus directory (default: golden)")
    p.add_argument("--case-id", default=None, help="explicit case id (default: next review-NNNN)")
    p.set_defaults(func=_cmd_golden)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ReviewQueueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
