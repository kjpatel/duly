"""Adapter #1: the honest scripted stub, extracted from starters/tools/extract.py.

This is deliberately a stub — it does NOT read the source document. The
rendition text is supplied at construction (the committed starters/*/renditions
.txt files), the document bytes contribute only their SHA-256, and each target
quote is located by exact substring search. Its value is that it exercises the
whole contract for real: spans verify, hashes verify, envelopes verify. A real
deployment swaps in an adapter that derives the rendition from the bytes
(docling_adapter.py is the first); nothing downstream changes.

Output is byte-compatible with the facts extract.py has always produced (the
committed starter facts regression-test this), including passing the targets'
scripted confidence values through verbatim — those are demo values, not real
calibration; adapters that measure anything should emit ``method: "raw"``.
"""

from __future__ import annotations

from .adapter import (
    ExtractionResult,
    QuoteNotFoundError,
    Rendition,
    SourceDocument,
    build_fact,
    derive_run_id,
    locate_quote,
    verify_fact_span,
)
from .envelope import build_envelope

EXTRACTOR_NAME = "duly-demo-extractor"
EXTRACTOR_VERSION = "0.1.0"


class StubAdapter:
    """Quote-target extraction against a pre-supplied rendition text."""

    def __init__(
        self,
        rendition_text: str,
        *,
        name: str = EXTRACTOR_NAME,
        version: str = EXTRACTOR_VERSION,
    ):
        self.name = name
        self.version = version
        self._rendition_text = rendition_text

    def extract(self, document: SourceDocument, targets: dict) -> ExtractionResult:
        rendition = Rendition(
            # "demo-extractor" is kept verbatim (not derived from `name`) for
            # byte-compatibility with the committed starter facts.
            id=f"rend:demo-extractor:{self.version}:{document.sha256[:8]}",
            extractor=self.name,
            extractor_version=self.version,
            document_sha256=document.sha256,
            text=self._rendition_text,
        )

        asserted_at = targets["assertedAt"]
        run_id = targets.get("runId") or derive_run_id(document, asserted_at)
        extractor = {"name": self.name, "version": self.version, "runId": run_id}

        facts: list[dict] = []
        notes: list[str] = []
        for target in targets["facts"]:
            match = locate_quote(rendition.text, target["quote"])
            if match is None:
                # The stub's targets are scripted against its rendition; a miss
                # is an authoring error, not a proposal to skip.
                raise QuoteNotFoundError(f"quote not found in rendition: {target['quote']!r}")
            if match.occurrences > 1:
                notes.append(
                    f"quote occurs more than once, using first occurrence: {target['quote']!r}"
                )
            fact = build_fact(
                target,
                document=document,
                rendition=rendition,
                span=(match.start, match.end),
                quote=target["quote"],
                confidence=target["confidence"],  # scripted demo values, passed through
                case_id=targets["caseId"],
                schema_ref=targets["schemaRef"],
                asserted_at=asserted_at,
                extractor=extractor,
                page=targets.get("page", 1),
            )
            verify_fact_span(fact, rendition.text)  # adapter acceptance test
            facts.append(fact)

        envelope = build_envelope(
            run_id=run_id,
            adapter={"name": self.name, "version": self.version},
            document_id=document.document_id,
            document_sha256=document.sha256,
            rendition_id=rendition.id,
            rendition_sha256=rendition.sha256,
            created_at=asserted_at,
            fact_ids=[f["id"] for f in facts],
        )
        return ExtractionResult(rendition=rendition, facts=facts, envelope=envelope, notes=notes)
