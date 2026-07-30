"""Extraction-run envelopes (spec/grounded-facts.md, resolved question 4).

An envelope is the manifest of one extraction run over one rendition: run id,
adapter name+version, source document hash, rendition hash, and the ordered,
complete list of fact ids the run proposed. It is content-addressed exactly
like facts (SHA-256 over the JCS canonical form excluding ``id`` and
``contentHash``; id = ``urn:duly:run:sha256:<hash>``), so tampering with the
manifest, any fact, or the rendition is detectable before anything reaches
the store. "Signed" at this stage means that integrity hash; asymmetric
signatures are a documented future hook (spec open questions), not built
here — key management is a heavier commitment than the current consumers
justify.

Consumer side: ``ingest_envelope`` verifies the whole run (manifest hash,
every fact hash, every span against the rendition) and only then writes
facts through the store's public ``ingest``; ``revoke_run`` retracts every
live fact carrying the run's id via the store's public ``retract``. Both
live here, not in duly_store — the store's write API is sufficient as-is.
"""

from __future__ import annotations

import hashlib
import json

from duly_conformance import OntologyRegistry, check_fact
from duly_store.store import FactStore, content_hash

from .adapter import verify_fact_span

__all__ = [
    "EnvelopeError",
    "EnvelopeVerificationError",
    "build_envelope",
    "verify_envelope",
    "ingest_envelope",
    "revoke_run",
]

RUN_URN_PREFIX = "urn:duly:run:sha256:"


class EnvelopeError(Exception):
    """Base error for extraction-run envelopes."""


class EnvelopeVerificationError(EnvelopeError):
    """The envelope, its facts, or the rendition failed integrity checks."""


# --- producer -----------------------------------------------------------------

def build_envelope(
    *,
    run_id: str,
    adapter: dict,
    document_id: str,
    document_sha256: str,
    rendition_id: str,
    rendition_sha256: str,
    created_at: str,
    fact_ids: list[str],
) -> dict:
    """Assemble a content-addressed extraction-run manifest.

    ``fact_ids`` is ordered and complete: exactly the facts the run proposed,
    in emission order. ``adapter`` is {"name", "version"} plus an optional
    "modelId" — the same identity the facts carry in assertion.extractor.
    """
    body = {
        "runId": run_id,
        "adapter": adapter,
        "documentId": document_id,
        "documentSha256": document_sha256,
        "rendition": {"id": rendition_id, "sha256": rendition_sha256},
        "createdAt": created_at,
        "factIds": list(fact_ids),
    }
    digest = content_hash(body)
    # Spec-example key order for readability; hashing sorts keys regardless.
    return {"id": RUN_URN_PREFIX + digest, "contentHash": digest, **body}


# --- consumer -----------------------------------------------------------------

def verify_envelope(
    envelope: dict,
    facts: list[dict],
    rendition_text: str,
    registry: OntologyRegistry | None = None,
) -> None:
    """Verify a whole run before it touches the store.

    Checks, in order: manifest content hash and id; rendition text against
    the manifest's rendition hash; the fact list against ``factIds`` (ordered,
    complete, nothing extra); every fact's content hash and id; every fact's
    grounding consistency with the manifest (document hash, rendition id, run
    id); every fact's span against the rendition. Raises
    EnvelopeVerificationError (or SpanVerificationError, a subclass of
    ExtractionError) on the first failure.

    ``registry`` is the OPTIONAL ontology conformance gate
    (spec/ontology-conformance.md): when supplied, every fact is also
    checked against the ontology + version its ``schemaRef`` pins, and a
    nonconforming fact fails the whole run with the gate's attribution
    (fact id, ontology reference, what failed). When omitted, behavior is
    exactly the pre-gate behavior — existing call sites change nothing.
    """
    expected = content_hash(envelope)
    if envelope.get("contentHash") != expected:
        raise EnvelopeVerificationError(
            f"envelope contentHash is {str(envelope.get('contentHash'))[:12]}…, "
            f"canonical form hashes to {expected[:12]}…"
        )
    if envelope.get("id") != RUN_URN_PREFIX + expected:
        raise EnvelopeVerificationError("envelope id does not match its contentHash")

    rendition_sha = hashlib.sha256(rendition_text.encode("utf-8")).hexdigest()
    if rendition_sha != envelope["rendition"]["sha256"]:
        raise EnvelopeVerificationError(
            f"rendition text hashes to {rendition_sha[:12]}…, "
            f"manifest says {envelope['rendition']['sha256'][:12]}…"
        )

    listed = list(envelope["factIds"])
    supplied = [f.get("id") for f in facts]
    if supplied != listed:
        raise EnvelopeVerificationError(
            f"supplied facts do not match the manifest's factIds "
            f"(got {len(supplied)}, manifest lists {len(listed)}, or order/membership differs)"
        )

    for fact in facts:
        digest = content_hash(fact)
        if fact.get("contentHash") != digest:
            raise EnvelopeVerificationError(
                f"fact {fact.get('id')}: contentHash is {str(fact.get('contentHash'))[:12]}…, "
                f"canonical form hashes to {digest[:12]}…"
            )
        if not str(fact.get("id", "")).endswith(digest):
            raise EnvelopeVerificationError(f"fact id {fact.get('id')} does not end with its contentHash")

        grounding = fact.get("grounding", {})
        if grounding.get("documentSha256") != envelope["documentSha256"]:
            raise EnvelopeVerificationError(
                f"fact {fact['id']}: documentSha256 does not match the manifest"
            )
        if grounding.get("rendition", {}).get("id") != envelope["rendition"]["id"]:
            raise EnvelopeVerificationError(
                f"fact {fact['id']}: rendition id does not match the manifest"
            )
        run_id = fact.get("assertion", {}).get("extractor", {}).get("runId")
        if run_id != envelope["runId"]:
            raise EnvelopeVerificationError(
                f"fact {fact['id']}: assertion runId {run_id!r} does not match "
                f"the manifest's {envelope['runId']!r}"
            )
        verify_fact_span(fact, rendition_text)

        if registry is not None:
            issues = check_fact(fact, registry)
            if issues:
                detail = "; ".join(f"[{i.code}] {i.message}" for i in issues)
                raise EnvelopeVerificationError(
                    f"fact {fact['id']}: ontology conformance failed — {detail}"
                )


def ingest_envelope(
    store: FactStore,
    envelope: dict,
    facts: list[dict],
    rendition_text: str,
    registry: OntologyRegistry | None = None,
) -> int:
    """Verify the whole run, then ingest its facts through the store's public
    API. Returns the number of facts newly inserted (idempotent re-ingest of
    an already-stored fact counts zero). Nothing is written if verification
    fails — verification is all-or-nothing and happens first. ``registry``
    is passed through to verify_envelope's optional conformance gate."""
    verify_envelope(envelope, facts, rendition_text, registry)
    inserted = 0
    for fact in facts:
        if store.ingest(fact):
            inserted += 1
    return inserted


def revoke_run(store: FactStore, run_id: str, recorded_at: str) -> list[str]:
    """Retract every live fact asserted by extraction run ``run_id``.

    Facts carry their run id in assertion.extractor.runId, so revocation
    needs only the run id, not the envelope. Retraction uses the store's
    public ``retract`` (an appended event — nothing is deleted, D7);
    already-superseded or already-retracted facts are left alone. Returns
    the retracted fact ids, sorted.

    Candidate lookup reads the store's event table directly: FactStore's
    public API projects by case id and has no run-scoped enumeration, and
    growing the store's API for one consumer isn't warranted yet. This is a
    read-only query against the documented schema (duly_store.store
    SCHEMA_DDL); every write goes through the public API.
    """
    asserted: dict[str, dict] = {}
    for fact_id, payload in store._conn.execute(
        "SELECT fact_id, payload FROM fact_events WHERE event_kind = 'asserted'"
    ):
        asserted[fact_id] = json.loads(payload)
    dead = {
        fact_id
        for (fact_id,) in store._conn.execute(
            "SELECT fact_id FROM fact_events WHERE event_kind IN ('superseded', 'retracted')"
        )
    }

    revoked = []
    for fact_id in sorted(asserted):
        if fact_id in dead:
            continue
        fact = asserted[fact_id]
        extractor = fact.get("assertion", {}).get("extractor", {})
        if extractor.get("runId") == run_id:
            store.retract(fact_id, recorded_at)
            revoked.append(fact_id)
    return revoked
