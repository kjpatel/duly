"""The optional ontology-conformance gate on envelope verification.

Registry supplied: a nonconforming fact rejects the whole run loudly, with
attribution, and nothing reaches the store. Registry omitted: byte-for-byte
the pre-gate behavior — existing call sites change nothing.
"""

import copy
from pathlib import Path

import pytest

from duly_conformance import load_repo_registry
from duly_store.store import FactStore, content_hash
from duly_extraction.envelope import (
    EnvelopeVerificationError,
    build_envelope,
    ingest_envelope,
    verify_envelope,
)

from extractiontest_helpers import run_stub

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def registry():
    return load_repo_registry(REPO / "ontologies")


@pytest.fixture()
def run():
    result, targets, text = run_stub("notice-ny-dec-page.json")
    return result.envelope, result.facts, text


def _with_misspelled_attribute(envelope: dict, facts: list[dict]) -> tuple[dict, list[dict]]:
    """A run whose second fact carries a misspelled attribute, with hashes
    and the manifest recomputed so integrity checks all pass — only the
    ontology gate can catch it."""
    facts = copy.deepcopy(facts)
    bad = facts[1]
    bad["attribute"] = "nc:policyExpirationDat"
    digest = content_hash(bad)
    bad["contentHash"] = digest
    bad["id"] = f"urn:duly:fact:sha256:{digest}"
    rebuilt = build_envelope(
        run_id=envelope["runId"],
        adapter=envelope["adapter"],
        document_id=envelope["documentId"],
        document_sha256=envelope["documentSha256"],
        rendition_id=envelope["rendition"]["id"],
        rendition_sha256=envelope["rendition"]["sha256"],
        created_at=envelope["createdAt"],
        fact_ids=[f["id"] for f in facts],
    )
    return rebuilt, facts


def test_conforming_run_verifies_with_registry(run, registry):
    envelope, facts, text = run
    verify_envelope(envelope, facts, text, registry)  # does not raise


def test_without_registry_behavior_is_unchanged(run):
    envelope, facts, text = run
    bad_envelope, bad_facts = _with_misspelled_attribute(envelope, facts)
    # The misspelled attribute passes every integrity check — this IS the
    # pre-gate behavior the optional argument must preserve.
    verify_envelope(bad_envelope, bad_facts, text)


def test_registry_rejects_the_run_with_attribution(run, registry):
    envelope, facts, text = run
    bad_envelope, bad_facts = _with_misspelled_attribute(envelope, facts)
    with pytest.raises(EnvelopeVerificationError) as exc:
        verify_envelope(bad_envelope, bad_facts, text, registry)
    message = str(exc.value)
    assert bad_facts[1]["id"] in message
    assert "unknown_attribute" in message
    assert "duly-starter-notice@0.1.0" in message
    assert "did you mean 'nc:policyExpirationDate'" in message


def test_ingest_with_registry_writes_nothing_on_rejection(run, registry):
    envelope, facts, text = run
    bad_envelope, bad_facts = _with_misspelled_attribute(envelope, facts)
    with FactStore.in_memory() as store:
        store.init_schema()
        with pytest.raises(EnvelopeVerificationError):
            ingest_envelope(store, bad_envelope, bad_facts, text, registry)
        assert store.as_of(facts[0]["caseId"], knowledge="2026-12-31T00:00:00Z") == []
        # And the clean run still ingests through the same gate.
        assert ingest_envelope(store, envelope, facts, text, registry) == len(facts)
