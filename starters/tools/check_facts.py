#!/usr/bin/env python3
"""Validate the starter-scenario facts, adapted from spec/validate.py.

For every scenario manifest under starters/*/scenario.json this checks:

1. each listed document's `sha256` matches the actual PDF bytes;
2. each fact validates against duly_core's grounded-fact schema;
3. each fact's contentHash matches the canonical-JSON hash (id/contentHash
   excluded) and its id ends with that hash;
4. each fact's documentSha256 matches a manifest document, and the charSpan
   slice of that document's rendition text equals the quote exactly
   (Unicode code point offsets, end-exclusive);
5. the fact's rendition id embeds the first 8 hex chars of the document hash.

Usage (from the repo root): uv run python starters/tools/check_facts.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from duly_core import content_hash as _content_hash, schema_path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    sys.exit("Requires jsonschema>=4.18. Run `uv sync` first.")

REPO = Path(__file__).resolve().parent.parent.parent
STARTERS = REPO / "starters"
SCHEMA_PATH = schema_path("grounded-fact")




def content_hash(doc: dict) -> str:
    return _content_hash(doc, "contentHash")


def main() -> int:
    validator = Draft202012Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )

    failures = 0
    checked = 0
    for manifest_path in sorted(STARTERS.glob("*/scenario.json")):
        scenario_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"scenario {manifest['id']} ({manifest_path.relative_to(REPO)})")

        renditions: dict[str, str] = {}  # documentSha256 -> rendition text
        for doc in manifest["documents"]:
            pdf_path = scenario_dir / doc["pdf"]
            actual = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            if actual != doc["sha256"]:
                print(f"FAIL  {doc['pdf']}: manifest sha256 {doc['sha256'][:12]}… but bytes hash to {actual[:12]}…")
                failures += 1
            else:
                print(f"ok    {doc['pdf']} sha256 matches")
            renditions[doc["sha256"]] = (scenario_dir / doc["rendition"]).read_text(encoding="utf-8")

        for rel in manifest["facts"]:
            path = scenario_dir / rel
            name = f"{manifest['id']}/{rel}"
            fact = json.loads(path.read_text(encoding="utf-8"))
            checked += 1
            ok = True

            for err in validator.iter_errors(fact):
                print(f"FAIL  {name}: {'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}")
                failures += 1
                ok = False

            expected = content_hash(fact)
            if fact["contentHash"] != expected:
                print(f"FAIL  {name}: contentHash is {fact['contentHash'][:12]}…, canonical form hashes to {expected[:12]}…")
                failures += 1
                ok = False
            if not fact["id"].endswith(fact["contentHash"]):
                print(f"FAIL  {name}: id does not end with contentHash")
                failures += 1
                ok = False

            g = fact["grounding"]
            if g["kind"] != "document":
                print(f"FAIL  {name}: expected document grounding, got {g['kind']}")
                failures += 1
                continue
            text = renditions.get(g["documentSha256"])
            if text is None:
                print(f"FAIL  {name}: documentSha256 {g['documentSha256'][:12]}… matches no document in scenario.json")
                failures += 1
                continue
            if g["documentSha256"][:8] not in g["rendition"]["id"]:
                print(f"FAIL  {name}: rendition id {g['rendition']['id']} does not embed doc hash prefix")
                failures += 1
                ok = False
            span = g["charSpan"]
            sliced = text[span["start"]:span["end"]]
            if sliced != g["quote"]:
                print(f"FAIL  {name}: charSpan [{span['start']},{span['end']}) yields {sliced!r}, quote is {g['quote']!r}")
                failures += 1
                ok = False

            if ok:
                print(f"ok    {name}  span=[{span['start']},{span['end']})  quote={g['quote']!r}")
        print()

    if failures:
        print(f"{failures} failure(s) across {checked} fact(s)")
        return 1
    print(f"All {checked} facts valid: schema, content hashes, and quote spans verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
