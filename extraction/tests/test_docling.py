"""Live Docling adapter tests: real PDF in, rendition + span-verified facts out.

Marked `docling` and skipped when the optional dependency isn't installed
(`uv sync --extra extraction`). First run downloads Docling's layout models.
These tests convert the committed fixture PDF (`fixtures/scenario/documents/`)
— they are the integration proof that the adapter interface holds for an
extractor that actually derives its rendition from the document bytes, so they
run on the toolkit corpus rather than on example content.
"""

import pytest

pytest.importorskip("docling", reason="optional extraction dependency group not installed")

pytestmark = pytest.mark.docling

from duly_store.store import FactStore  # noqa: E402

from duly_extraction.adapter import ExtractionAdapter, SourceDocument, verify_fact_span  # noqa: E402
from duly_extraction.docling_adapter import DoclingAdapter, docling_version  # noqa: E402
from duly_extraction.envelope import ingest_envelope, revoke_run, verify_envelope  # noqa: E402

from extractiontest_helpers import load_fixture_pdf_bytes, load_fixture_targets  # noqa: E402


@pytest.fixture(scope="module")
def adapter():
    return DoclingAdapter()  # one converter (model load is expensive) for the module


@pytest.fixture(scope="module")
def widget_report_result(adapter):
    targets = load_fixture_targets()
    document = SourceDocument.from_bytes(targets["documentId"], load_fixture_pdf_bytes())
    return adapter.extract(document, targets), targets


def test_satisfies_protocol(adapter):
    assert isinstance(adapter, ExtractionAdapter)


def test_rendition_is_derived_and_content_addressed(widget_report_result):
    result, _targets = widget_report_result
    ver = docling_version()
    assert result.rendition.text.strip()  # actually read the PDF
    # The fixture document's title line (fixtures/build.py DOC_LINES).
    assert "WIDGET INSPECTION REPORT" in result.rendition.text
    assert result.rendition.extractor == "docling"
    assert result.rendition.extractor_version == ver
    assert result.rendition.id.startswith(f"rend:docling:{ver}:")
    assert len(result.rendition.sha256) == 64


def test_facts_are_span_faithful_with_raw_confidence(widget_report_result):
    result, targets = widget_report_result
    # Every target is accounted for: emitted or explicitly skipped.
    assert len(result.facts) + len(result.skipped) == len(targets["facts"])
    assert result.facts, (
        "Docling found none of the fixture quotes — rendition text was: "
        f"{result.rendition.text[:400]!r}"
    )
    for fact in result.facts:
        verify_fact_span(fact, result.rendition.text)
        assert fact["confidence"]["method"] == "raw"
        assert 0 < fact["confidence"]["score"] <= 1
        assert fact["assertion"]["extractor"]["name"] == "duly-docling-adapter"
        assert fact["assertion"]["extractor"]["modelId"] == f"docling-{docling_version()}"


def test_envelope_round_trip_from_docling_run(widget_report_result):
    result, _targets = widget_report_result
    verify_envelope(result.envelope, result.facts, result.rendition.text)
    with FactStore.in_memory() as store:
        store.init_schema()
        assert ingest_envelope(
            store, result.envelope, result.facts, result.rendition.text
        ) == len(result.facts)
        revoked = revoke_run(store, result.envelope["runId"], "2026-07-31T09:00:00Z")
        assert sorted(revoked) == sorted(result.envelope["factIds"])


def test_hash_only_document_is_refused(adapter):
    from duly_extraction.adapter import ExtractionError

    targets = load_fixture_targets()
    with pytest.raises(ExtractionError):
        adapter.extract(SourceDocument(targets["documentId"], "0" * 64), targets)
