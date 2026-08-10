"""duly extraction adapters: source document bytes -> rendition + GroundedFacts.

The first-contact API, re-exported here because an adapter author's first
import should not require knowing this package's file layout (finding A1's
lesson, applied to the edge the adopter's guide walks). The protocol is
``ExtractionAdapter``; ``StubAdapter`` is the scripted reference
implementation; ``build_fact``/``verify_fact_span`` are how emitted facts are
sealed and held to their spans; the envelope functions carry a run's facts
into and out of a store as one auditable unit.
"""

from .adapter import (
    ExtractionAdapter,
    ExtractionError,
    ExtractionResult,
    QuoteNotFoundError,
    Rendition,
    SkippedTarget,
    SourceDocument,
    SpanVerificationError,
    QuoteMatch,
    build_fact,
    derive_run_id,
    locate_quote,
    match_confidence,
    verify_fact_span,
)
from .envelope import (
    EnvelopeError,
    EnvelopeVerificationError,
    build_envelope,
    ingest_envelope,
    revoke_run,
    verify_envelope,
)
from .stub import StubAdapter

__all__ = [
    "ExtractionAdapter",
    "ExtractionError",
    "ExtractionResult",
    "QuoteMatch",
    "QuoteNotFoundError",
    "Rendition",
    "SkippedTarget",
    "SourceDocument",
    "SpanVerificationError",
    "StubAdapter",
    "build_fact",
    "build_envelope",
    "derive_run_id",
    "EnvelopeError",
    "EnvelopeVerificationError",
    "ingest_envelope",
    "locate_quote",
    "match_confidence",
    "revoke_run",
    "verify_envelope",
]
