#!/usr/bin/env python3
"""Honest extraction stub: turn quote targets into contract-conformant GroundedFacts.

Given a rendition .txt, the SHA-256 of the source document bytes, and a targets
file listing (attribute, entity, value, quote) tuples, this tool finds each
quote's character span in the rendition via substring search and emits fact
JSON conforming to spec/schemas/grounded-fact.schema.json, with the content
hash computed the same way spec/validate.py verifies it:

    sha256( json.dumps(body, sort_keys=True, separators=(",",":"),
                       ensure_ascii=False).encode("utf-8") )

over the fact minus its `id` and `contentHash`; id = urn:duly:fact:sha256:<hash>.

Char spans are Unicode code point offsets into the rendition text, end-exclusive.
This is deliberately a stub — a real deployment swaps in a document-AI extractor
that produces the same contract; nothing downstream changes.

Targets file shape (JSON):

    {
      "documentId": "doc:dec-page:HO-77401-NY:2025-09-01",
      "caseId": "case:policy:HO-77401-NY",
      "schemaRef": {"ontology": "duly-starter-notice", "version": "0.1.0"},
      "assertedAt": "2026-07-28T14:05:41Z",
      "runId": "run:2026-07-28:007",
      "page": 1,
      "facts": [
        {
          "file": "fact-decpage-expiration.json",
          "entity": {"id": "policy:HO-77401-NY", "type": "nc:Policy"},
          "attribute": "nc:policyExpirationDate",
          "value": {"kind": "date", "value": "2026-09-01"},
          "quote": "POLICY PERIOD: 09/01/2025 to 09/01/2026",
          "confidence": {"score": 0.995, "method": "conformal"},
          "effectiveFrom": "2025-09-01T00:00:00Z"
        }
      ]
    }

Example (from the repo root):

    uv run python starters/tools/extract.py \
        --rendition starters/notice-ny/renditions/dec-page.txt \
        --pdf starters/notice-ny/documents/dec-page.pdf \
        --targets starters/tools/targets/notice-ny-dec-page.json \
        --out-dir starters/notice-ny/facts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXTRACTOR_NAME = "duly-demo-extractor"
EXTRACTOR_VERSION = "0.1.0"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(body: dict) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def find_span(text: str, quote: str) -> tuple[int, int]:
    """First occurrence of `quote` in `text`, as [start, end) code point offsets."""
    start = text.find(quote)
    if start < 0:
        raise ValueError(f"quote not found in rendition: {quote!r}")
    if text.find(quote, start + 1) >= 0:
        print(f"note: quote occurs more than once, using first occurrence: {quote!r}", file=sys.stderr)
    return start, start + len(quote)


def build_fact(
    target: dict,
    *,
    document_id: str,
    document_sha256: str,
    case_id: str,
    schema_ref: dict,
    asserted_at: str,
    run_id: str | None,
    rendition_text: str,
    page: int,
    extractor_name: str,
    extractor_version: str,
) -> dict:
    start, end = find_span(rendition_text, target["quote"])
    assert rendition_text[start:end] == target["quote"]

    extractor = {"name": extractor_name, "version": extractor_version}
    if run_id:
        extractor["runId"] = run_id

    body = {
        "caseId": case_id,
        "entity": target["entity"],
        "attribute": target["attribute"],
        "value": target["value"],
        "grounding": {
            "kind": "document",
            "documentId": document_id,
            "documentSha256": document_sha256,
            "rendition": {
                "id": f"rend:demo-extractor:{extractor_version}:{document_sha256[:8]}",
                "extractor": extractor_name,
                "extractorVersion": extractor_version,
            },
            "page": target.get("page", page),
            "charSpan": {"start": start, "end": end},
            "quote": target["quote"],
        },
        "assertion": {"kind": "machine", "at": asserted_at, "extractor": extractor},
        "confidence": target["confidence"],
        "recordedAt": asserted_at,
        "status": "asserted",
        "schemaRef": schema_ref,
    }
    if "effectiveFrom" in target:
        body["effectiveFrom"] = target["effectiveFrom"]
    if "effectiveTo" in target:
        body["effectiveTo"] = target["effectiveTo"]

    digest = content_hash(body)
    # Present keys in the spec-example order for readability; key order does
    # not affect the hash (canonicalization sorts keys).
    ordered = {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest}
    for key in (
        "caseId", "entity", "attribute", "value", "grounding", "assertion",
        "confidence", "effectiveFrom", "effectiveTo", "recordedAt", "status", "schemaRef",
    ):
        if key in body:
            ordered[key] = body[key]
    return ordered


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extract GroundedFacts from a document rendition by quote lookup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Targets file shape")[0],
    )
    ap.add_argument("--rendition", required=True, type=Path, help="Path to the rendition .txt the spans index into.")
    sha = ap.add_mutually_exclusive_group(required=True)
    sha.add_argument("--document-sha256", help="SHA-256 (hex) of the source document bytes.")
    sha.add_argument("--pdf", type=Path, help="Path to the source document; its SHA-256 is computed.")
    ap.add_argument("--targets", required=True, type=Path, help="JSON targets file (see module docstring).")
    ap.add_argument("--out-dir", required=True, type=Path, help="Directory to write fact JSON files into.")
    ap.add_argument("--extractor-name", default=EXTRACTOR_NAME)
    ap.add_argument("--extractor-version", default=EXTRACTOR_VERSION)
    args = ap.parse_args()

    document_sha256 = args.document_sha256 or hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    rendition_text = args.rendition.read_text(encoding="utf-8")
    spec = json.loads(args.targets.read_text(encoding="utf-8"))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for target in spec["facts"]:
        fact = build_fact(
            target,
            document_id=spec["documentId"],
            document_sha256=document_sha256,
            case_id=spec["caseId"],
            schema_ref=spec["schemaRef"],
            asserted_at=spec["assertedAt"],
            run_id=spec.get("runId"),
            rendition_text=rendition_text,
            page=spec.get("page", 1),
            extractor_name=args.extractor_name,
            extractor_version=args.extractor_version,
        )
        out_path = args.out_dir / target["file"]
        out_path.write_text(json.dumps(fact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        span = fact["grounding"]["charSpan"]
        print(f"wrote {out_path}  span=[{span['start']},{span['end']})  {target['attribute']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
