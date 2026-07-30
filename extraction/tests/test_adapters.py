"""Adapter interface conformance and span-faithful fact emission."""

import json

import pytest

from duly_extraction.adapter import (
    ExtractionAdapter,
    QuoteNotFoundError,
    SourceDocument,
    SpanVerificationError,
    locate_quote,
    match_confidence,
    verify_fact_span,
)
from duly_extraction.stub import StubAdapter

from extractiontest_helpers import (
    STARTER_RUNS,
    STARTERS,
    load_targets,
    run_stub,
)


# --- interface conformance ---------------------------------------------------

def test_stub_satisfies_protocol():
    adapter = StubAdapter("some rendition text")
    assert isinstance(adapter, ExtractionAdapter)
    assert adapter.name and adapter.version


def test_docling_adapter_satisfies_protocol_without_docling_installed():
    # The module (and the protocol check) must not require the optional
    # dependency; only a live extract() call does.
    from duly_extraction.docling_adapter import DoclingAdapter

    assert isinstance(DoclingAdapter(), ExtractionAdapter)


# --- the stub reproduces the committed starter facts byte-for-byte -----------

@pytest.mark.parametrize("targets_name", sorted(STARTER_RUNS))
def test_stub_reproduces_committed_facts(targets_name):
    result, targets, _text = run_stub(targets_name)
    scenario, _doc = STARTER_RUNS[targets_name]
    assert len(result.facts) == len(targets["facts"])
    for target, fact in zip(targets["facts"], result.facts):
        committed_path = STARTERS / scenario / "facts" / target["file"]
        # Byte-for-byte, including key order — the same serialization
        # starters/tools/extract.py writes.
        assert json.dumps(fact, indent=2, ensure_ascii=False) + "\n" == committed_path.read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize("targets_name", sorted(STARTER_RUNS))
def test_every_emitted_fact_is_span_faithful(targets_name):
    """The acceptance test: quote == rendition_text[start:end], every fact."""
    result, _targets, text = run_stub(targets_name)
    for fact in result.facts:
        span = fact["grounding"]["charSpan"]
        assert text[span["start"]:span["end"]] == fact["grounding"]["quote"]
        verify_fact_span(fact, text)  # and the packaged checker agrees


def test_stub_raises_on_missing_quote():
    targets = load_targets("notice-ny-dec-page.json")
    document = SourceDocument(targets["documentId"], "0" * 64)
    with pytest.raises(QuoteNotFoundError):
        StubAdapter("a rendition without the quotes").extract(document, targets)


def test_stub_notes_ambiguous_quote():
    targets = load_targets("notice-ny-dec-page.json")
    targets["facts"] = [dict(targets["facts"][0], quote="09/01/2025")]
    text = "period 09/01/2025 to 09/01/2025"
    document = SourceDocument(targets["documentId"], "0" * 64)
    result = StubAdapter(text).extract(document, targets)
    assert len(result.facts) == 1
    assert result.facts[0]["grounding"]["charSpan"] == {"start": 7, "end": 17}  # first occurrence
    assert any("more than once" in note for note in result.notes)


# --- verify_fact_span rejects what it should ---------------------------------

def test_verify_fact_span_rejects_wrong_offsets():
    result, _targets, text = run_stub("notice-ny-dec-page.json")
    fact = json.loads(json.dumps(result.facts[0]))
    fact["grounding"]["charSpan"]["start"] += 1
    with pytest.raises(SpanVerificationError):
        verify_fact_span(fact, text)


def test_verify_fact_span_rejects_attestation_and_missing_span():
    with pytest.raises(SpanVerificationError):
        verify_fact_span({"id": "x", "grounding": {"kind": "attestation"}}, "text")
    with pytest.raises(SpanVerificationError):
        verify_fact_span({"id": "x", "grounding": {"kind": "document", "quote": "t"}}, "text")


# --- quote location and raw match confidence (the Docling proposal seam) -----

def test_locate_quote_exact_and_unique():
    match = locate_quote("alpha beta gamma", "beta")
    assert (match.start, match.end, match.occurrences, match.exact) == (6, 10, 1, True)
    assert match_confidence(match) == {"score": 0.9, "method": "raw"}


def test_locate_quote_exact_ambiguous():
    match = locate_quote("beta x beta", "beta")
    assert (match.start, match.occurrences, match.exact) == (0, 2, True)
    assert match_confidence(match) == {"score": 0.6, "method": "raw"}


def test_locate_quote_normalized_across_whitespace():
    text = "POLICY   PERIOD:\n09/01/2025    to 09/01/2026 end"
    quote = "POLICY PERIOD: 09/01/2025 to 09/01/2026"
    assert locate_quote(text, quote) is None  # exact search fails
    match = locate_quote(text, quote, allow_normalized=True)
    assert match is not None and not match.exact and match.occurrences == 1
    # The caller must emit the actual slice as the quote for spans to verify.
    assert text[match.start:match.end] == "POLICY   PERIOD:\n09/01/2025    to 09/01/2026"
    assert match_confidence(match) == {"score": 0.7, "method": "raw"}


def test_locate_quote_normalized_ambiguous():
    match = locate_quote("a  b then a\nb", "a b", allow_normalized=True)
    assert match is not None and not match.exact and match.occurrences == 2
    assert match_confidence(match) == {"score": 0.5, "method": "raw"}


def test_locate_quote_not_found():
    assert locate_quote("nothing here", "absent", allow_normalized=True) is None
    assert locate_quote("nothing here", "   ", allow_normalized=True) is None
