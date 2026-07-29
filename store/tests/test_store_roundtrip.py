"""End-to-end: store projection feeds the kernel and reproduces the
committed receipt's decision (noticeCompliant = false at effective
2026-07-25, knowledge 2026-07-30T16:00:00Z)."""

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.ir import load_pack
from duly_store.store import FactStore

from storetest_helpers import (
    CASE_ID,
    NY_PACK,
    correction,
    load_expected_receipt,
    load_spec_facts,
    rehash,
)


@pytest.fixture()
def spec_facts() -> list[dict]:
    return load_spec_facts()


@pytest.fixture()
def expected_receipt() -> dict:
    return load_expected_receipt()

AS_OF_EFFECTIVE = "2026-07-25T00:00:00Z"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"
DECISION_ATTR = "nc:noticeCompliant"


def test_ingest_project_adjudicate_matches_committed_receipt(spec_facts, expected_receipt):
    store = FactStore.in_memory()
    store.init_schema()
    for fact in spec_facts:
        assert store.ingest(fact) is True

    projected = store.as_of(CASE_ID, AS_OF_KNOWLEDGE, AS_OF_EFFECTIVE)
    assert sorted(f["id"] for f in projected) == sorted(f["id"] for f in spec_facts)

    pack = load_pack(NY_PACK)
    receipt = adjudicate(projected, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, DECISION_ATTR)

    assert receipt["decision"] == expected_receipt["decision"]
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
    assert {f["id"] for f in receipt["inputFacts"]} == {
        f["id"] for f in expected_receipt["inputFacts"]
    }


def test_adjudication_from_pre_correction_horizon_uses_original_facts(spec_facts):
    """Time-travel through the full pipeline: a correction recorded later
    must not leak into a decision replayed at an earlier knowledge point."""
    store = FactStore.in_memory()
    store.init_schema()
    for fact in spec_facts:
        store.ingest(fact)

    # Later correction: notice actually mailed 2026-06-01 — 45+ days before
    # expiration (2026-09-01), which flips the decision to compliant.
    mailed = next(f for f in spec_facts if f["attribute"] == "nc:noticeMailedDate")
    corrected = correction(
        mailed,
        value={"kind": "date", "value": "2026-06-01"},
        recorded_at="2026-08-01T09:00:00Z",
        supersedes=mailed["id"],
    )
    corrected["effectiveFrom"] = "2026-06-01T00:00:00Z"
    corrected = rehash(corrected)
    store.ingest(corrected)

    pack = load_pack(NY_PACK)

    # Replay at the original knowledge horizon: still non-compliant.
    replayed = adjudicate(
        store.as_of(CASE_ID, AS_OF_KNOWLEDGE, AS_OF_EFFECTIVE),
        pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, DECISION_ATTR,
    )
    assert replayed["decision"]["value"] == {"kind": "boolean", "value": False}

    # Evaluate with the correction known: compliant.
    now_known = adjudicate(
        store.as_of(CASE_ID, "2026-08-01T09:00:00Z", AS_OF_EFFECTIVE),
        pack, AS_OF_EFFECTIVE, "2026-08-01T09:00:00Z", DECISION_ATTR,
    )
    assert now_known["decision"]["value"] == {"kind": "boolean", "value": True}
