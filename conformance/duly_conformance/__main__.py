"""CLI: python -m duly_conformance <check|list> ...

check — validate fact JSON files (or directories of them) against the
ontology registry; receipts and envelopes encountered in a directory sweep
are skipped, matching spec/validate.py's document classification. Exit 1
on any nonconformity.

list — show the registry contents: each ontology, its classes, and per
class its attribute CURIEs with their value kinds.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gate import check_fact
from .registry import load_repo_registry


def _is_fact(doc: dict) -> bool:
    # A directory sweep also encounters receipts, envelopes, scenario
    # manifests, and extraction targets files; only a GroundedFact carries
    # grounding + attribute + value together (spec/schemas/grounded-fact).
    if "receiptSha256" in doc or "factIds" in doc:
        return False
    return "grounding" in doc and "attribute" in doc and "value" in doc


def _iter_fact_paths(paths: list[str]):
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(path.rglob("*.json"))
        else:
            yield path


def _cmd_check(args) -> int:
    registry = load_repo_registry(args.ontologies)
    failures = 0
    checked = 0
    for path in _iter_fact_paths(args.paths):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not _is_fact(doc):
            continue
        checked += 1
        issues = check_fact(doc, registry)
        if issues:
            for issue in issues:
                print(f"FAIL  {path}: [{issue.code}] {issue.message}")
            failures += len(issues)
        elif args.verbose:
            ref = doc.get("schemaRef", {})
            print(f"ok    {path} conforms to {ref.get('ontology')}@{ref.get('version')}")
    if failures:
        print(f"\n{failures} issue(s) across {checked} fact(s)")
        return 1
    print(f"All {checked} fact(s) conform ({', '.join(registry.refs())}).")
    return 0


def _cmd_list(args) -> int:
    registry = load_repo_registry(args.ontologies)
    for ontology in sorted(registry, key=lambda o: o.ref):
        print(f"{ontology.ref}  (prefixes: {', '.join(sorted(ontology.prefixes))})")
        for curie in sorted(ontology.classes):
            cls = ontology.classes[curie]
            print(f"  {curie}")
            for slot_curie in sorted(cls.slots):
                slot = cls.slots[slot_curie]
                enum = ""
                if slot.enum is not None:
                    members = "open" if slot.enum.open_code_set else f"{len(slot.enum.values)} values"
                    enum = f"  [{slot.enum.code_system or slot.enum.name}: {members}]"
                print(f"    {slot_curie}: {slot.kind}{enum}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m duly_conformance")
    parser.add_argument(
        "--ontologies",
        default="ontologies",
        help="registry directory of <name>/<version>.yaml files (default: ontologies)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check fact JSON files or directories")
    check.add_argument("paths", nargs="+", help="fact files or directories to sweep")
    check.add_argument("-v", "--verbose", action="store_true", help="print each conforming fact")
    sub.add_parser("list", help="show registry contents")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _cmd_check(args)
    return _cmd_list(args)


if __name__ == "__main__":
    sys.exit(main())
