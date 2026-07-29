"""Adapter #2: Docling — derive the rendition from the actual document bytes.

Docling (https://github.com/docling-project/docling) does the document
conversion: PDF bytes in, structured document out, exported here as Markdown
text. That text IS the rendition (spec D4): it is content-addressed, versioned
by the docling release that produced it, and every span offsets into it.

What Docling does not do is decide *which* facts to assert — conversion is not
NLU. Fact proposal in this v1 works from the same targets-file shape the stub
uses: each target's quote is searched in the Docling rendition, exactly first,
then whitespace-normalized (different converters render the same words with
different spacing), and the emitted quote is the actual rendition slice so
span verification holds by construction. Confidence is ``method: "raw"``
reflecting match quality (see adapter.match_confidence) — a proxy, not a
calibrated probability. Targets whose quotes cannot be located are reported in
``ExtractionResult.skipped``, never emitted ungrounded.

A future model-driven proposer replaces the targets file with generated
proposals (e.g. schema-constrained decoding over the rendition), keeping the
same rendition, span-verification, and envelope machinery. That seam is the
``targets`` argument, nothing else.

The ``docling`` import is deferred to first use so this module is importable
(and the rest of the package testable) without the optional ``extraction``
dependency group installed.
"""

from __future__ import annotations

import io

from .adapter import (
    ExtractionError,
    ExtractionResult,
    Rendition,
    SkippedTarget,
    SourceDocument,
    build_fact,
    derive_run_id,
    locate_quote,
    match_confidence,
    verify_fact_span,
)
from .envelope import build_envelope

ADAPTER_NAME = "duly-docling-adapter"
ADAPTER_VERSION = "0.1.0"


def docling_version() -> str:
    """The installed docling release — the rendition is versioned by this."""
    from importlib.metadata import version

    return version("docling")


class DoclingAdapter:
    """Docling document conversion + quote-target fact proposal."""

    name = ADAPTER_NAME
    version = ADAPTER_VERSION

    def __init__(self, converter=None):
        # A pre-built DocumentConverter may be injected (model warm-up is
        # expensive); otherwise one is created lazily on first extract().
        self._converter = converter
        self._docling_version: str | None = None

    # -- rendition -------------------------------------------------------

    def _render_text(self, document: SourceDocument) -> str:
        if document.data is None:
            raise ExtractionError(
                "DoclingAdapter needs the document bytes; got a hash-only SourceDocument"
            )
        from docling.datamodel.base_models import DocumentStream
        from docling.document_converter import DocumentConverter

        if self._converter is None:
            self._converter = DocumentConverter()
        stream = DocumentStream(
            name=document.document_id.replace(":", "_") + ".pdf",
            stream=io.BytesIO(document.data),
        )
        result = self._converter.convert(stream)
        return result.document.export_to_markdown()

    # -- extraction ------------------------------------------------------

    def extract(self, document: SourceDocument, targets: dict) -> ExtractionResult:
        if self._docling_version is None:
            self._docling_version = docling_version()
        text = self._render_text(document)
        rendition = Rendition(
            # The rendition names the converter, not this adapter: the text
            # changes when docling changes (spec D4).
            id=f"rend:docling:{self._docling_version}:{document.sha256[:8]}",
            extractor="docling",
            extractor_version=self._docling_version,
            document_sha256=document.sha256,
            text=text,
        )

        asserted_at = targets["assertedAt"]
        run_id = targets.get("runId") or derive_run_id(document, asserted_at)
        extractor = {
            "name": self.name,
            "version": self.version,
            "modelId": f"docling-{self._docling_version}",
            "runId": run_id,
        }

        facts: list[dict] = []
        skipped: list[SkippedTarget] = []
        notes: list[str] = []
        for target in targets["facts"]:
            match = locate_quote(rendition.text, target["quote"], allow_normalized=True)
            if match is None:
                skipped.append(
                    SkippedTarget(
                        attribute=target["attribute"],
                        quote=target["quote"],
                        reason="quote not found in Docling rendition (exact or normalized)",
                    )
                )
                continue
            if match.occurrences > 1:
                notes.append(
                    f"quote matched {match.occurrences} places, using first: {target['quote']!r}"
                )
            # The emitted quote is the actual rendition slice — on a
            # normalized match it differs from the target's quote in
            # whitespace, and quote == rendition[start:end] must hold.
            quote = rendition.text[match.start:match.end]
            fact = build_fact(
                target,
                document=document,
                rendition=rendition,
                span=(match.start, match.end),
                quote=quote,
                confidence=match_confidence(match),
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
            adapter={"name": self.name, "version": self.version,
                     "modelId": f"docling-{self._docling_version}"},
            document_id=document.document_id,
            document_sha256=document.sha256,
            rendition_id=rendition.id,
            rendition_sha256=rendition.sha256,
            created_at=asserted_at,
            fact_ids=[f["id"] for f in facts],
        )
        return ExtractionResult(
            rendition=rendition, facts=facts, envelope=envelope, skipped=skipped, notes=notes
        )
