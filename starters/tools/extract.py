#!/usr/bin/env python3
"""Honest extraction stub: turn quote targets into contract-conformant GroundedFacts.

Since M3 this is a thin CLI over extraction/duly_extraction — the stub is
adapter #1 (duly_extraction.stub.StubAdapter); this file keeps the tool and
its flags working unchanged. Given a rendition .txt, the SHA-256 of the
source document bytes, and a targets file listing (attribute, entity, value,
quote) tuples, the adapter finds each quote's character span in the rendition
via substring search and emits fact JSON conforming to
duly_core's grounded-fact schema, with the content hash computed the
same way spec/validate.py verifies it:

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
import json
import sys
from pathlib import Path

from duly_extraction.adapter import SourceDocument
from duly_extraction.stub import EXTRACTOR_NAME, EXTRACTOR_VERSION, StubAdapter


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
    ap.add_argument("--envelope", type=Path, help="Optional path to also write the extraction-run envelope JSON.")
    ap.add_argument("--extractor-name", default=EXTRACTOR_NAME)
    ap.add_argument("--extractor-version", default=EXTRACTOR_VERSION)
    args = ap.parse_args()

    spec = json.loads(args.targets.read_text(encoding="utf-8"))
    if args.pdf is not None:
        document = SourceDocument.from_bytes(spec["documentId"], args.pdf.read_bytes())
    else:
        document = SourceDocument(spec["documentId"], args.document_sha256)
    rendition_text = args.rendition.read_text(encoding="utf-8")

    adapter = StubAdapter(rendition_text, name=args.extractor_name, version=args.extractor_version)
    result = adapter.extract(document, spec)
    for note in result.notes:
        print(f"note: {note}", file=sys.stderr)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for target, fact in zip(spec["facts"], result.facts):
        out_path = args.out_dir / target["file"]
        out_path.write_text(json.dumps(fact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        span = fact["grounding"]["charSpan"]
        print(f"wrote {out_path}  span=[{span['start']},{span['end']})  {target['attribute']}")

    if args.envelope is not None:
        args.envelope.parent.mkdir(parents=True, exist_ok=True)
        args.envelope.write_text(
            json.dumps(result.envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.envelope}  run={result.envelope['runId']}  {len(result.facts)} fact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
