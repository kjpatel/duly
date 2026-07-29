"""CLI for the duly fact store.

Usage:
    python -m duly_store init    --db PATH
    python -m duly_store ingest  --db PATH --facts DIR
    python -m duly_store query   --db PATH --case CASE --knowledge TS [--effective TS]
    python -m duly_store history --db PATH --fact-id ID
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import FactStore, FactStoreError


def _cmd_init(args: argparse.Namespace) -> int:
    with FactStore(args.db) as store:
        store.init_schema()
    print(f"initialized {args.db}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    facts_dir = Path(args.facts)
    if not facts_dir.is_dir():
        print(f"error: not a directory: {facts_dir}", file=sys.stderr)
        return 2
    ingested = skipped = errors = 0
    with FactStore(args.db) as store:
        store.init_schema()
        for path in sorted(facts_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if "receiptSha256" in doc:
                continue  # a DecisionReceipt, not a fact
            try:
                if store.ingest(doc):
                    ingested += 1
                    print(f"ingested  {path.name}")
                else:
                    skipped += 1
                    print(f"unchanged {path.name}")
            except FactStoreError as exc:
                errors += 1
                print(f"REJECTED  {path.name}: {exc}", file=sys.stderr)
    print(f"{ingested} ingested, {skipped} unchanged, {errors} rejected")
    return 1 if errors else 0


def _cmd_query(args: argparse.Namespace) -> int:
    with FactStore(args.db) as store:
        facts = store.as_of(args.case, args.knowledge, args.effective)
    json.dump(facts, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    with FactStore(args.db) as store:
        events = store.history(args.fact_id)
    json.dump(events, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="duly_store", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the schema")
    p.add_argument("--db", required=True, help="path to the SQLite database")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("ingest", help="ingest all *.json fact files from a directory")
    p.add_argument("--db", required=True)
    p.add_argument("--facts", required=True, help="directory of GroundedFact JSON files")
    p.set_defaults(func=_cmd_ingest)

    p = sub.add_parser("query", help="project a case as of a bitemporal point")
    p.add_argument("--db", required=True)
    p.add_argument("--case", required=True, help="case id")
    p.add_argument("--knowledge", required=True, help="knowledge horizon (ISO-8601)")
    p.add_argument("--effective", default=None, help="effective point (ISO-8601, optional)")
    p.set_defaults(func=_cmd_query)

    p = sub.add_parser("history", help="print the event history / supersession chain of a fact")
    p.add_argument("--db", required=True)
    p.add_argument("--fact-id", required=True)
    p.set_defaults(func=_cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FactStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
