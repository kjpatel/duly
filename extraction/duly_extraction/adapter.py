"""Extraction adapter contract (spec/grounded-facts.md D3/D4/D5).

An adapter turns one source document into:

- a **rendition** — the immutable extracted-text artifact spans index into
  (D4): extractor name + version + the text itself, content-addressed by the
  SHA-256 of its UTF-8 bytes and tied to the SHA-256 of the source bytes;
- proposed **GroundedFacts** whose ``charSpan`` offsets are Unicode code
  point offsets into that rendition, end-exclusive, and whose ``quote``
  equals ``rendition.text[start:end]`` exactly — enforced on every emission
  by ``verify_fact_span`` (the adapter acceptance test);
- an **extraction-run envelope** — the manifest that lets a whole run be
  verified or revoked at once (see envelope.py and the spec, resolved
  question 4).

The interface is derived from what the two concrete adapters — the scripted
demo stub (stub.py) and Docling (docling_adapter.py) — genuinely share, and
no more. In particular, both need to be told *which* attributes to look for:
document conversion gives you text, not an ontology. That fact-proposal seam
is the ``targets`` dict, the same shape starters/tools/extract.py has always
documented ({documentId, caseId, schemaRef, assertedAt, runId?, page?,
facts: [{entity, attribute, value, quote, confidence?, sensitivity?, ...}]}). A future
model-driven proposer (an LLM or trained extractor deciding what to assert)
replaces the targets file with generated proposals; the rendition, span
verification, fact shape, and envelope stay exactly as they are here.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# The store owns the canonicalization convention (RFC 8785 subset); reuse it
# rather than keeping a fourth copy in sync.
from duly_store.store import content_hash


class ExtractionError(Exception):
    """Base error for extraction adapters."""


class SpanVerificationError(ExtractionError):
    """A fact's quote does not equal the rendition slice its span names."""


class QuoteNotFoundError(ExtractionError):
    """A target quote could not be located in the rendition."""


# --- inputs and outputs ------------------------------------------------------

@dataclass(frozen=True)
class SourceDocument:
    """A source document pinned by the SHA-256 of its bytes.

    ``data`` may be omitted when only the hash is known — the stub adapter
    never reads the bytes (its rendition text is supplied), while the Docling
    adapter requires them.
    """

    document_id: str
    sha256: str
    data: bytes | None = None

    @classmethod
    def from_bytes(cls, document_id: str, data: bytes) -> "SourceDocument":
        return cls(document_id, hashlib.sha256(data).hexdigest(), data)


@dataclass(frozen=True)
class Rendition:
    """The immutable extracted-text artifact offsets are defined against (D4).

    ``extractor``/``extractor_version`` name the thing that *produced the
    text* (e.g. docling 2.x), which is not always the adapter that asserts
    the facts (e.g. duly-docling-adapter 0.1.0) — the text changes when the
    converter changes, so that is what the rendition is versioned by.
    """

    id: str
    extractor: str
    extractor_version: str
    document_sha256: str
    text: str

    @property
    def sha256(self) -> str:
        """Content address of the rendition text (SHA-256 of its UTF-8 bytes)."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def record(self) -> dict:
        """The ``grounding.rendition`` record embedded in each fact."""
        return {
            "id": self.id,
            "extractor": self.extractor,
            "extractorVersion": self.extractor_version,
        }


@dataclass(frozen=True)
class SkippedTarget:
    """A target the adapter declined to emit — never a silently dropped one."""

    attribute: str
    quote: str
    reason: str


@dataclass
class ExtractionResult:
    rendition: Rendition
    facts: list[dict]
    envelope: dict
    skipped: list[SkippedTarget] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class ExtractionAdapter(Protocol):
    """What every adapter provides: a name/version for the assertion record,
    and one call from (document, targets) to (rendition, facts, envelope)."""

    name: str
    version: str

    def extract(self, document: SourceDocument, targets: dict) -> ExtractionResult: ...


# --- quote location ----------------------------------------------------------

@dataclass(frozen=True)
class QuoteMatch:
    """Where a quote landed in the rendition and how good the match was."""

    start: int
    end: int
    occurrences: int  # how many places the quote (or its relaxation) matched
    exact: bool       # False when only a whitespace-normalized match was found


def locate_quote(text: str, quote: str, *, allow_normalized: bool = False) -> QuoteMatch | None:
    """Locate ``quote`` in ``text`` as [start, end) code point offsets.

    Exact substring search first (the stub's contract); with
    ``allow_normalized`` a whitespace-flexible fallback is tried, because a
    different converter (Docling vs. the plain-text rendition the targets
    were authored against) renders the same words with different spacing.
    The caller must re-read the actual slice as the fact's quote so that
    quote == rendition[start:end] still holds. Returns None when not found;
    always the first occurrence.
    """
    start = text.find(quote)
    if start >= 0:
        occurrences = 1
        probe = start
        while (probe := text.find(quote, probe + 1)) >= 0:
            occurrences += 1
        return QuoteMatch(start, start + len(quote), occurrences, exact=True)

    if not allow_normalized:
        return None
    tokens = quote.split()
    if not tokens:
        return None
    # Same tokens, any whitespace between them (spaces, newlines, collapsed runs).
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    first = matches[0]
    return QuoteMatch(first.start(), first.end(), len(matches), exact=False)


def match_confidence(match: QuoteMatch) -> dict:
    """Machine confidence for a quote-search proposal: ``method: "raw"``.

    An honest heuristic proxy for match quality, NOT a calibrated
    probability — calibration (temperature/Platt/conformal) is the M3
    calibration module's job, downstream of the adapter (spec D5):

    - exact and unique in the rendition        -> 0.90
    - exact but ambiguous (first occurrence)   -> 0.60
    - whitespace-normalized, unique            -> 0.70
    - whitespace-normalized, ambiguous         -> 0.50
    """
    if match.exact:
        score = 0.9 if match.occurrences == 1 else 0.6
    else:
        score = 0.7 if match.occurrences == 1 else 0.5
    return {"score": score, "method": "raw"}


# --- fact construction and the acceptance test -------------------------------

def verify_fact_span(fact: dict, rendition_text: str) -> None:
    """The adapter acceptance test (same check as starters/tools/check_facts.py):
    the quote must equal the rendition slice, code point offsets, end-exclusive."""
    grounding = fact.get("grounding", {})
    if grounding.get("kind") != "document":
        raise SpanVerificationError(f"fact {fact.get('id')} has no document grounding")
    span = grounding.get("charSpan")
    if span is None:
        raise SpanVerificationError(f"fact {fact.get('id')} has no charSpan")
    sliced = rendition_text[span["start"]:span["end"]]
    if sliced != grounding.get("quote"):
        raise SpanVerificationError(
            f"fact {fact.get('id')}: charSpan [{span['start']},{span['end']}) yields "
            f"{sliced!r}, quote is {grounding.get('quote')!r}"
        )


def build_fact(
    target: dict,
    *,
    document: SourceDocument,
    rendition: Rendition,
    span: tuple[int, int],
    quote: str,
    confidence: dict,
    case_id: str,
    schema_ref: dict,
    asserted_at: str,
    extractor: dict,
    page: int,
) -> dict:
    """Assemble one contract-conformant GroundedFact, content-addressed the
    same way spec/validate.py verifies it (D8)."""
    start, end = span
    body = {
        "caseId": case_id,
        "entity": target["entity"],
        "attribute": target["attribute"],
        "value": target["value"],
        "grounding": {
            "kind": "document",
            "documentId": document.document_id,
            "documentSha256": document.sha256,
            "rendition": rendition.record(),
            "page": target.get("page", page),
            "charSpan": {"start": start, "end": end},
            "quote": quote,
        },
        "assertion": {"kind": "machine", "at": asserted_at, "extractor": extractor},
        "confidence": confidence,
        "recordedAt": asserted_at,
        "status": "asserted",
        "schemaRef": schema_ref,
    }
    if "effectiveFrom" in target:
        body["effectiveFrom"] = target["effectiveFrom"]
    if "effectiveTo" in target:
        body["effectiveTo"] = target["effectiveTo"]
    # `sensitivity` is a property of the *content* a target names, not of the
    # extraction: whether a quote carries PII is knowable when the target is
    # authored and not knowable from the span. So it passes through here, the
    # same way the effective dates do. Nothing is inferred — an adapter that
    # guessed at PII would be asserting a handling class it cannot ground, and
    # the absent field already means `internal` (spec/grounded-facts.md, open
    # question 3). Without this pass-through the only way to hold a `pii` fact
    # was to write it by hand, i.e. outside the adapter that verifies spans.
    if "sensitivity" in target:
        body["sensitivity"] = target["sensitivity"]

    digest = content_hash(body)
    # Present keys in the spec-example order for readability; key order does
    # not affect the hash (canonicalization sorts keys).
    ordered = {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest}
    for key in (
        "caseId", "entity", "attribute", "value", "grounding", "assertion",
        "confidence", "effectiveFrom", "effectiveTo", "recordedAt", "status", "schemaRef",
        "sensitivity",
    ):
        if key in body:
            ordered[key] = body[key]
    return ordered


def derive_run_id(document: SourceDocument, asserted_at: str) -> str:
    """Deterministic fallback run id when the targets file names none."""
    return f"run:{document.sha256[:12]}:{asserted_at}"
