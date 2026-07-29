"""Core FactStore behavior: ingest, idempotency, integrity, projections."""

import copy

import pytest

from duly_store.store import (
    DuplicateFactError,
    FactStore,
    FactStoreError,
    HashMismatchError,
)

from storetest_helpers import CASE_ID, load_spec_facts, rehash

KNOWLEDGE = "2026-07-30T16:00:00Z"  # after every example fact's recordedAt


@pytest.fixture()
def spec_facts() -> list[dict]:
    return load_spec_facts()


def make_store(facts=()):
    store = FactStore.in_memory()
    store.init_schema()
    for fact in facts:
        store.ingest(fact)
    return store


def test_ingest_and_project(spec_facts):
    store = make_store(spec_facts)
    projected = store.as_of(CASE_ID, KNOWLEDGE)
    assert sorted(f["id"] for f in projected) == sorted(f["id"] for f in spec_facts)
    by_id = {f["id"]: f for f in spec_facts}
    for fact in projected:
        assert fact == by_id[fact["id"]]  # payload round-trips intact


def test_projection_is_scoped_to_case(spec_facts):
    store = make_store(spec_facts)
    assert store.as_of("case:other", KNOWLEDGE) == []


def test_projection_before_any_knowledge_is_empty(spec_facts):
    store = make_store(spec_facts)
    assert store.as_of(CASE_ID, "2026-07-01T00:00:00Z") == []


def test_idempotent_reingest(spec_facts):
    store = make_store()
    assert store.ingest(spec_facts[0]) is True
    assert store.ingest(spec_facts[0]) is False  # no-op
    assert len(store.history(spec_facts[0]["id"])) == 1
    assert len(store.as_of(CASE_ID, KNOWLEDGE)) == 1


def test_different_payload_under_existing_id_rejected(spec_facts):
    store = make_store([spec_facts[0]])
    # A self-consistent hash but the *old* id: the classic "recomputed the
    # hash, forgot to update the id" client bug.
    tampered = rehash({**copy.deepcopy(spec_facts[0]), "attribute": "nc:somethingElse"})
    tampered["id"] = spec_facts[0]["id"]
    with pytest.raises(DuplicateFactError):
        store.ingest(tampered)


def test_hash_verification_rejects_tampered_fact(spec_facts):
    store = make_store()
    tampered = copy.deepcopy(spec_facts[0])
    tampered["value"] = {"kind": "date", "value": "1999-01-01"}  # hash left stale
    with pytest.raises(HashMismatchError):
        store.ingest(tampered)
    assert store.as_of(CASE_ID, KNOWLEDGE) == []  # nothing was written


def test_minimal_shape_validation():
    store = make_store()
    with pytest.raises(FactStoreError):
        store.ingest({"id": "urn:duly:fact:sha256:abc", "contentHash": "abc"})


def test_deterministic_ordering(spec_facts):
    forward = make_store(spec_facts)
    backward = make_store(list(reversed(spec_facts)))
    ids_forward = [f["id"] for f in forward.as_of(CASE_ID, KNOWLEDGE)]
    ids_backward = [f["id"] for f in backward.as_of(CASE_ID, KNOWLEDGE)]
    assert ids_forward == ids_backward == sorted(ids_forward)


def test_retraction(spec_facts):
    store = make_store(spec_facts)
    target = spec_facts[0]["id"]
    store.retract(target, "2026-07-29T10:00:00Z")

    before = store.as_of(CASE_ID, "2026-07-29T09:59:59Z")
    assert target in {f["id"] for f in before}

    at = store.as_of(CASE_ID, "2026-07-29T10:00:00Z")  # horizon is inclusive
    assert target not in {f["id"] for f in at}
    assert len(at) == len(spec_facts) - 1

    events = store.history(target)
    assert [e["event_kind"] for e in events] == ["asserted", "retracted"]
    assert events[1]["recorded_at"] == "2026-07-29T10:00:00Z"


def test_effective_window_filtering(spec_facts):
    # A fact with a bounded window [2026-07-25, 2026-08-01) ...
    windowed = copy.deepcopy(spec_facts[0])
    windowed["effectiveFrom"] = "2026-07-25T00:00:00Z"
    windowed["effectiveTo"] = "2026-08-01T00:00:00Z"
    windowed = rehash(windowed)
    # ... and a fact with no window at all, which always participates.
    unwindowed = copy.deepcopy(spec_facts[1])
    unwindowed.pop("effectiveFrom", None)
    unwindowed.pop("effectiveTo", None)
    unwindowed = rehash(unwindowed)

    store = make_store([windowed, unwindowed])

    def ids(effective):
        return {f["id"] for f in store.as_of(CASE_ID, KNOWLEDGE, effective)}

    assert ids("2026-07-24T00:00:00Z") == {unwindowed["id"]}   # before the window
    assert ids("2026-07-25T00:00:00Z") == {windowed["id"], unwindowed["id"]}  # from-inclusive
    assert ids("2026-07-31T23:59:59Z") == {windowed["id"], unwindowed["id"]}
    assert ids("2026-08-01T00:00:00Z") == {unwindowed["id"]}   # to-exclusive
    # No effective point given: windows are not applied at all.
    assert ids(None) == {windowed["id"], unwindowed["id"]}


def test_bare_date_points_accepted(spec_facts):
    store = make_store(spec_facts)
    # Bare dates normalize to midnight UTC, matching the kernel's convention.
    assert store.as_of(CASE_ID, "2026-07-31", "2026-07-25") == store.as_of(
        CASE_ID, "2026-07-31T00:00:00Z", "2026-07-25T00:00:00Z"
    )
