#!/usr/bin/env python3
"""Validate the spec examples against the schemas and verify content hashes.

Usage: uv run spec/validate.py   (after: uv sync)

Hash verification uses JSON canonicalization per RFC 8785 restricted to the
subset these documents use (object keys sorted, minimal separators, UTF-8,
no exotic floats), computed over the document minus its `id` and hash field.
"""

import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:
    sys.exit("Requires jsonschema>=4.18. Run `uv sync`, then `uv run spec/validate.py`.")

try:
    from duly_conformance import check_fact, load_repo_registry
except ImportError:
    check_fact = load_repo_registry = None  # validated additively below when available

SPEC = Path(__file__).parent
HASH_FIELDS = {
    "GroundedFact": "contentHash",
    "DecisionReceipt": "receiptSha256",
    "ExtractionRunEnvelope": "contentHash",
}


def classify(doc: dict) -> str:
    if "receiptSha256" in doc:
        return "DecisionReceipt"
    if "factIds" in doc:
        return "ExtractionRunEnvelope"
    return "GroundedFact"


# Imported rather than reimplemented. A second copy of these three lines was
# never an independent check on the first: it has no algorithmic diversity, so
# it could only catch a typo, while looking like it verified the definition.
# What verifies the definition is spec/canonical-vectors.json, below.
from duly_core import SCHEMAS, canonical, content_hash  # noqa: E402


PROV_NS = "http://www.w3.org/ns/prov#"
DULY_NS = "https://duly.dev/spec/v0/vocab#"


def check_contexts() -> int:
    """Structural checks on the PROV-O JSON-LD contexts (spec/contexts/).

    Deliberately processor-free: real expansion against committed documents is
    covered by kernel/tests/test_provo.py (pyld, dev dependency). Here we check
    what a context file must declare to be usable at all: JSON-LD 1.1 mode, the
    expected namespace bindings, and that every term maps to a keyword, to a
    compact IRI under a declared prefix, or to an absolute IRI.
    """
    failures = 0
    paths = sorted((SPEC / "contexts").glob("*.context.jsonld"))
    if not paths:
        print("FAIL  spec/contexts/: no *.context.jsonld files found")
        return 1
    for path in paths:
        try:
            ctx = json.loads(path.read_text())["@context"]
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"FAIL  {path.name}: not a JSON-LD context document ({exc})")
            failures += 1
            continue
        problems = []
        if ctx.get("@version") != 1.1:
            problems.append("@version is not 1.1")
        if ctx.get("prov") != PROV_NS:
            problems.append(f"prov prefix is not {PROV_NS}")
        if ctx.get("duly") != DULY_NS:
            problems.append(f"duly prefix is not {DULY_NS}")
        prefixes = {k for k, v in ctx.items() if isinstance(v, str) and v.startswith("http")}

        def iri_ok(iri: str) -> bool:
            if iri.startswith("@"):
                return True
            if ":" in iri and iri.split(":", 1)[0] in prefixes:
                return True
            return iri.startswith("http")

        def walk_terms(mapping: dict, at: str):
            for term, defn in mapping.items():
                if term.startswith("@"):
                    continue
                where = f"{at}{term}"
                if isinstance(defn, str):
                    if not iri_ok(defn):
                        problems.append(f"{where}: unresolvable mapping {defn!r}")
                elif isinstance(defn, dict):
                    iri = defn.get("@id")
                    if iri is None or not iri_ok(iri):
                        problems.append(f"{where}: unresolvable @id {iri!r}")
                    if "@context" in defn:
                        walk_terms(defn["@context"], where + ".")
                else:
                    problems.append(f"{where}: unexpected term definition type")

        walk_terms(ctx, "")
        for problem in problems:
            print(f"FAIL  {path.name}: {problem}")
            failures += 1
        if not problems:
            print(f"ok    {path.name} (JSON-LD context)")
    return failures


def main() -> int:
    schemas = {}
    registry = Registry()
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        schemas[schema["title"]] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))

    validators = {
        title: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for title, schema in schemas.items()
    }

    # Ontology conformance gate (spec/ontology-conformance.md), additive:
    # committed example facts must conform to the committed ontologies.
    ontology_registry = None
    if load_repo_registry is not None and (SPEC.parent / "ontologies").is_dir():
        ontology_registry = load_repo_registry(SPEC.parent / "ontologies")

    failures = 0
    fact_ids = set()
    facts_by_id = {}
    # Envelope examples live in examples/envelopes/ so that tooling globbing
    # examples/*.json for facts (kernel/demo/store fixtures) is unaffected.
    examples = sorted((SPEC / "examples").rglob("*.json"))
    for path in examples:
        doc = json.loads(path.read_text())
        title = classify(doc)
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
            facts_by_id[doc["id"]] = doc
            if ontology_registry is not None:
                for issue in check_fact(doc, ontology_registry):
                    print(f"FAIL  {path.name}: conformance [{issue.code}] {issue.message}")
                    failures += 1
                    errors = True
        if not errors:
            print(f"ok    {path.name} ({title})")

    for path in examples:
        doc = json.loads(path.read_text())
        if classify(doc) == "ExtractionRunEnvelope":
            for fid in doc["factIds"]:
                fact = facts_by_id.get(fid)
                if fact is None:
                    print(f"FAIL  {path.name}: factIds references {fid[:40]}… which is not among the example facts")
                    failures += 1
                elif fact["grounding"].get("documentSha256") != doc["documentSha256"]:
                    print(f"FAIL  {path.name}: fact {fid[:40]}… grounds in a different documentSha256 than the manifest")
                    failures += 1
                elif fact["grounding"].get("rendition", {}).get("id") != doc["rendition"]["id"]:
                    print(f"FAIL  {path.name}: fact {fid[:40]}… grounds in a different rendition than the manifest")
                    failures += 1
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

    failures += check_contexts()

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    conformance = (
        f", facts conform to ontologies ({', '.join(ontology_registry.refs())})"
        if ontology_registry is not None
        else ""
    )
    print(f"\nAll examples valid, hashes verified, contexts well-formed{conformance}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
