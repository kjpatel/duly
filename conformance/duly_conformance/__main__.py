"""CLI: python -m duly_conformance <check|list> ...

check — validate fact JSON files (or directories of them) against the
ontology registry; receipts and envelopes encountered in a directory sweep
are skipped, matching spec/validate.py's document classification. Exit 1
on any nonconformity.

list — show the registry contents: each ontology, its classes, and per
class its attribute CURIEs with their value kinds.

Both verbs need a registry directory, and there is no default for it: pass
`--ontologies DIR` or set `DULY_ONTOLOGIES`. Your ontologies are yours, and
duly does not know where you keep them.

Exit codes: 0 success, 1 nonconformity found, 2 the registry could not be
loaded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .gate import check_fact
from .linkml_subset import OntologySubsetError
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


def _resolve_ontologies(args, parser: argparse.ArgumentParser) -> str:
    """The registry directory, from the flag or ``DULY_ONTOLOGIES``.

    There is deliberately **no path default**. `ontologies` used to be one,
    which is duly's own layout relative to whatever directory the command was
    run from: correct inside this repository, and meaningless everywhere else.
    An adopter's ontologies live where that adopter keeps them, which is the
    same reason `load_repo_registry` takes a directory rather than finding one
    (registry.py, "Library code takes a registry, never a repo path").
    """
    ontologies = args.ontologies or os.environ.get("DULY_ONTOLOGIES")
    if not ontologies:
        parser.error(
            "no ontology registry given. Pass --ontologies DIR (a directory of "
            "<name>/<version>.yaml files) or set DULY_ONTOLOGIES. There is no "
            "default: your ontologies are yours, and duly does not know where "
            "you keep them."
        )
    return ontologies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="duly-conformance")
    parser.add_argument(
        "--ontologies",
        help="registry directory of <name>/<version>.yaml files. Required; "
        "may also be given as DULY_ONTOLOGIES. No default — see the error text.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check fact JSON files or directories")
    check.add_argument("paths", nargs="+", help="fact files or directories to sweep")
    check.add_argument("-v", "--verbose", action="store_true", help="print each conforming fact")
    sub.add_parser("list", help="show registry contents")
    args = parser.parse_args(argv)
    args.ontologies = _resolve_ontologies(args, parser)

    # A registry that cannot be loaded is a diagnosis, not a stack trace. The
    # traceback that used to come out of registry.py named the exception class
    # and a path, which reads as a duly bug rather than as "you pointed me at
    # the wrong directory" — and outside this repository it was the *first*
    # thing an adopter saw.
    try:
        if args.command == "check":
            return _cmd_check(args)
        return _cmd_list(args)
    except OntologySubsetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
