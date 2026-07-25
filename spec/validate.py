#!/usr/bin/env python3
"""Validate the spec examples against the schemas and verify content hashes.

Usage: uv run spec/validate.py   (after: uv sync)

Hash verification uses JSON canonicalization per RFC 8785 restricted to the
subset these documents use (object keys sorted, minimal separators, UTF-8,
no exotic floats), computed over the document minus its `id` and hash field.
"""

import hashlib
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:
    sys.exit("Requires jsonschema>=4.18. Run `uv sync`, then `uv run spec/validate.py`.")

SPEC = Path(__file__).parent
HASH_FIELDS = {"GroundedFact": "contentHash", "DecisionReceipt": "receiptSha256"}


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(doc: dict, hash_field: str) -> str:
    body = {k: v for k, v in doc.items() if k not in ("id", hash_field)}
    return hashlib.sha256(canonical(body)).hexdigest()


def main() -> int:
    schemas = {}
    registry = Registry()
    for path in sorted((SPEC / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text())
        schemas[schema["title"]] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))

    validators = {
        title: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for title, schema in schemas.items()
    }

    failures = 0
    fact_ids = set()
    examples = sorted((SPEC / "examples").glob("*.json"))
    for path in examples:
        doc = json.loads(path.read_text())
        title = "DecisionReceipt" if "receiptSha256" in doc else "GroundedFact"
        errors = list(validators[title].iter_errors(doc))
        for err in errors:
            print(f"FAIL  {path.name}: {'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}")
            failures += 1

        hash_field = HASH_FIELDS[title]
        expected = content_hash(doc, hash_field)
        if doc[hash_field] != expected:
            print(f"FAIL  {path.name}: {hash_field} is {doc[hash_field][:12]}…, canonical form hashes to {expected[:12]}…")
            failures += 1
        if not doc["id"].endswith(doc[hash_field]):
            print(f"FAIL  {path.name}: id does not end with {hash_field}")
            failures += 1

        if title == "GroundedFact":
            fact_ids.add(doc["id"])
        if not errors:
            print(f"ok    {path.name} ({title})")

    for path in examples:
        doc = json.loads(path.read_text())
        if "receiptSha256" not in doc:
            continue
        input_ids = {f["id"] for f in doc["inputFacts"]}
        for missing in sorted(input_ids - fact_ids):
            print(f"FAIL  {path.name}: inputFacts references {missing[:40]}… which is not among the example facts")
            failures += 1

        def walk(node):
            for p in node.get("premises", []):
                if "factId" in p:
                    yield p["factId"]
                else:
                    yield from walk(p)

        for fid in walk(doc["derivation"]):
            if fid not in input_ids:
                print(f"FAIL  {path.name}: derivation cites {fid[:40]}… missing from inputFacts")
                failures += 1

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print("\nAll examples valid, hashes verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
