"""Extraction-run envelopes: produce -> verify -> ingest -> revoke, and every
tamper path rejected before anything reaches the store."""

import copy
import json

import pytest

from duly_store.store import FactStore, content_hash

from duly_extraction.adapter import SpanVerificationError
from duly_extraction.envelope import (
    EnvelopeVerificationError,
    build_envelope,
    ingest_envelope,
    revoke_run,
    verify_envelope,
)

from extractiontest_helpers import run_stub

KNOWLEDGE = "2026-07-30T16:00:00Z"       # after every starter fact's recordedAt
REVOKED_AT = "2026-07-31T09:00:00Z"
AFTER_REVOKE = "2026-07-31T10:00:00Z"


@pytest.fixture()
def store():
    with FactStore.in_memory() as s:
        s.init_schema()
        yield s


@pytest.fixture()
def run():
    """One committed starter run: (envelope, facts, rendition_text, targets)."""
    result, targets, text = run_stub("notice-ny-dec-page.json")
    return result.envelope, result.facts, text, targets


def rehash_fact(fact: dict) -> dict:
    out = copy.deepcopy(fact)
    digest = content_hash(out)
    out["contentHash"] = digest
    out["id"] = f"urn:duly:fact:sha256:{digest}"
    return out


def rebuild_envelope(envelope: dict, **overrides) -> dict:
    fields = {
        "run_id": envelope["runId"],
        "adapter": envelope["adapter"],
        "document_id": envelope["documentId"],
        "document_sha256": envelope["documentSha256"],
        "rendition_id": envelope["rendition"]["id"],
        "rendition_sha256": envelope["rendition"]["sha256"],
        "created_at": envelope["createdAt"],
        "fact_ids": envelope["factIds"],
    }
    fields.update(overrides)
    return build_envelope(**fields)


# --- shape and integrity of the produced envelope -----------------------------

def test_envelope_is_content_addressed(run):
    envelope, facts, _text, targets = run
    assert envelope["id"] == f"urn:duly:run:sha256:{envelope['contentHash']}"
    assert envelope["contentHash"] == content_hash(envelope)
    assert envelope["runId"] == targets["runId"]
    assert envelope["factIds"] == [f["id"] for f in facts]
    assert envelope["documentSha256"] == facts[0]["grounding"]["documentSha256"]
    assert envelope["rendition"]["id"] == facts[0]["grounding"]["rendition"]["id"]


def test_envelope_validates_against_spec_schema(run):
    jsonschema = pytest.importorskip("jsonschema")
    from extractiontest_helpers import REPO_ROOT

    schema = json.loads(
        (REPO_ROOT / "spec" / "schemas" / "extraction-run.schema.json").read_text(encoding="utf-8")
    )
    envelope, _facts, _text, _targets = run
    jsonschema.Draft202012Validator(schema).validate(envelope)


# --- round trip ----------------------------------------------------------------

def test_round_trip_verify_ingest_revoke(store, run):
    envelope, facts, text, targets = run
    verify_envelope(envelope, facts, text)  # produce -> verify

    assert ingest_envelope(store, envelope, facts, text) == len(facts)  # -> ingest
    case_id = targets["caseId"]
    live = store.as_of(case_id, KNOWLEDGE)
    assert sorted(f["id"] for f in live) == sorted(envelope["factIds"])

    revoked = revoke_run(store, envelope["runId"], REVOKED_AT)  # -> revoke
    assert sorted(revoked) == sorted(envelope["factIds"])
    assert store.as_of(case_id, AFTER_REVOKE) == []
    # Knowledge-time travel still sees the run before the revocation (D7).
    assert len(store.as_of(case_id, KNOWLEDGE)) == len(facts)


def test_ingest_is_idempotent(store, run):
    envelope, facts, text, _targets = run
    assert ingest_envelope(store, envelope, facts, text) == len(facts)
    assert ingest_envelope(store, envelope, facts, text) == 0


def test_revoke_only_touches_its_run(store):
    dec = run_stub("notice-ny-dec-page.json")[0]
    trid = run_stub("trid-loan-estimate.json")[0]
    assert dec.envelope["runId"] != trid.envelope["runId"]
    ingest_envelope(store, dec.envelope, dec.facts, dec.rendition.text)
    ingest_envelope(store, trid.envelope, trid.facts, trid.rendition.text)

    revoked = revoke_run(store, trid.envelope["runId"], REVOKED_AT)
    assert sorted(revoked) == sorted(trid.envelope["factIds"])
    # The other run is untouched...
    assert len(store.as_of("case:policy:HO-77401-NY", AFTER_REVOKE)) == len(dec.facts)
    # ...and revoking again finds nothing live.
    assert revoke_run(store, trid.envelope["runId"], AFTER_REVOKE) == []


def test_revoke_unknown_run_is_a_noop(store, run):
    envelope, facts, text, _targets = run
    ingest_envelope(store, envelope, facts, text)
    assert revoke_run(store, "run:never-happened", REVOKED_AT) == []
    assert len(store.as_of("case:policy:HO-77401-NY", AFTER_REVOKE)) == len(facts)


# --- tamper detection: nothing reaches the store ------------------------------

def assert_rejected_and_store_empty(store, envelope, facts, text, targets, exc=EnvelopeVerificationError):
    with pytest.raises(exc):
        ingest_envelope(store, envelope, facts, text)
    assert store.as_of(targets["caseId"], KNOWLEDGE) == []


def test_modified_fact_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = copy.deepcopy(facts)
    tampered[0]["value"]["value"] = "2027-09-01"  # hash no longer matches
    assert_rejected_and_store_empty(store, envelope, tampered, text, targets)


def test_modified_and_rehashed_fact_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = copy.deepcopy(facts)
    tampered[0]["value"]["value"] = "2027-09-01"
    tampered[0] = rehash_fact(tampered[0])  # hash valid, but not the fact the manifest lists
    assert_rejected_and_store_empty(store, envelope, tampered, text, targets)


def test_modified_manifest_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = copy.deepcopy(envelope)
    tampered["documentSha256"] = "0" * 64  # contentHash no longer matches
    assert_rejected_and_store_empty(store, tampered, facts, text, targets)


def test_rebuilt_manifest_with_foreign_document_hash_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = rebuild_envelope(envelope, document_sha256="0" * 64)
    # The manifest hash verifies, but the facts ground in a different document.
    assert_rejected_and_store_empty(store, tampered, facts, text, targets)


def test_wrong_rendition_hash_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = rebuild_envelope(envelope, rendition_sha256="0" * 64)
    assert_rejected_and_store_empty(store, tampered, facts, text, targets)


def test_wrong_rendition_text_rejected(store, run):
    envelope, facts, _text, targets = run
    assert_rejected_and_store_empty(store, envelope, facts, "not the rendition", targets)


def test_dropped_fact_rejected(store, run):
    envelope, facts, text, targets = run
    assert len(facts) > 1
    assert_rejected_and_store_empty(store, envelope, facts[:-1], text, targets)


def test_reordered_facts_rejected(store, run):
    envelope, facts, text, targets = run
    assert_rejected_and_store_empty(store, envelope, list(reversed(facts)), text, targets)


def test_bad_span_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = copy.deepcopy(facts)
    tampered[0]["grounding"]["charSpan"]["start"] += 1
    tampered[0]["grounding"]["charSpan"]["end"] += 1
    tampered[0] = rehash_fact(tampered[0])
    envelope = rebuild_envelope(envelope, fact_ids=[f["id"] for f in tampered])
    # Manifest and fact hashes all verify — only span verification catches it.
    assert_rejected_and_store_empty(store, envelope, tampered, text, targets, exc=SpanVerificationError)


def test_wrong_run_id_in_fact_rejected(store, run):
    envelope, facts, text, targets = run
    tampered = copy.deepcopy(facts)
    tampered[0]["assertion"]["extractor"]["runId"] = "run:someone-else"
    tampered[0] = rehash_fact(tampered[0])
    envelope = rebuild_envelope(envelope, fact_ids=[f["id"] for f in tampered])
    # Everything hashes, spans verify — but the fact disowns the run, which
    # would break run-level revocation later. Rejected up front.
    assert_rejected_and_store_empty(store, envelope, tampered, text, targets)
