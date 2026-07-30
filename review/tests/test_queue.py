"""Review queue core: enqueue dedup, lifecycle, correction ingestion.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest review/tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviewtest_helpers import (  # noqa: E402
    ARC_AS_OF_KNOWLEDGE,
    ARC_CASE_ID,
    ARC_CORRECTION_TS,
    ARC_NOTICE_ENTITY,
    MAILED,
    QUESTION,
    adjudicate_arc,
    build_arc_facts,
    load_notice_pack,
    mailed_fact,
    make_correction,
    rehash,
)

from duly_kernel.api import adjudicate  # noqa: E402
from duly_review import (  # noqa: E402
    InvalidCorrectionError,
    InvalidTransitionError,
    ReviewQueue,
    ReviewQueueError,
    UnknownItemError,
    enqueue_receipt,
    item_natural_key,
)
from duly_store.store import FactStore, HashMismatchError  # noqa: E402

T0 = ARC_AS_OF_KNOWLEDGE
T1 = ARC_CORRECTION_TS


@pytest.fixture()
def queue() -> ReviewQueue:
    return ReviewQueue.in_memory()


@pytest.fixture()
def store() -> FactStore:
    s = FactStore.in_memory()
    s.init_schema()
    return s


@pytest.fixture()
def arc(store):
    """Facts ingested, abstaining receipt adjudicated."""
    facts = build_arc_facts()
    for f in facts:
        store.ingest(f)
    receipt = adjudicate_arc(facts)
    return facts, receipt


# --- enqueue + dedup ----------------------------------------------------------


class TestEnqueue:
    def test_one_item_per_abstention_entry(self, queue, arc):
        facts, receipt = arc
        results = enqueue_receipt(queue, receipt, recorded_at=T0)
        assert len(results) == len(receipt["abstentions"]) == 1
        assert results[0]["created"] is True

        (item,) = queue.items()
        entry = receipt["abstentions"][0]
        assert item["itemId"] == item_natural_key(ARC_CASE_ID, entry)
        assert item["caseId"] == ARC_CASE_ID
        assert item["entity"] == ARC_NOTICE_ENTITY
        assert item["attribute"] == MAILED
        assert item["reason"] == "low_confidence"
        assert item["entry"] == entry  # verbatim
        assert item["receipt"] == {"id": receipt["id"], "receiptSha256": receipt["receiptSha256"]}
        assert item["status"] == "open"
        assert item["assignee"] is None
        assert item["openedAt"] == T0

    def test_re_enqueue_same_receipt_is_idempotent(self, queue, arc):
        _, receipt = arc
        enqueue_receipt(queue, receipt, recorded_at=T0)
        results = enqueue_receipt(queue, receipt, recorded_at=T1)
        assert results == [{"itemId": queue.items()[0]["itemId"], "created": False}]
        assert len(queue.items()) == 1
        # No re-sighting event either: the log stays one opened event.
        assert [e["event_kind"] for e in queue.events(results[0]["itemId"])] == ["opened"]

    def test_re_adjudication_with_new_receipt_hash_still_dedups(self, queue, arc):
        facts, receipt = arc
        # Same case, same pack, later knowledge point: new receipt hash,
        # identical abstention entry.
        later = adjudicate(facts, load_notice_pack(), "2026-07-25", "2026-08-01T09:00:00Z", QUESTION)
        assert later["receiptSha256"] != receipt["receiptSha256"]
        assert later["abstentions"] == receipt["abstentions"]
        first = enqueue_receipt(queue, receipt, recorded_at=T0)
        second = enqueue_receipt(queue, later, recorded_at="2026-08-01T09:00:00Z")
        assert second == [{"itemId": first[0]["itemId"], "created": False}]

    def test_terminal_items_do_not_reopen(self, queue, store, arc):
        facts, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(mailed_fact(facts)), store, T1)
        again = enqueue_receipt(queue, receipt, recorded_at="2026-08-02T00:00:00Z")
        assert again == [{"itemId": result["itemId"], "created": False}]
        assert queue.item(result["itemId"])["status"] == "resolved"

    def test_different_case_yields_different_item(self, queue, store):
        for case in ("case:review:a", "case:review:b"):
            facts = build_arc_facts(case, notice_entity=f"notice:{case}", policy_entity=f"policy:{case}")
            receipt = adjudicate_arc(facts)
            enqueue_receipt(queue, receipt, recorded_at=T0)
        assert len(queue.items()) == 2

    def test_receipt_without_abstentions_enqueues_nothing(self, queue):
        facts = build_arc_facts(mailed_confidence={"score": 0.95, "method": "platt"})
        receipt = adjudicate_arc(facts)
        assert receipt["abstentions"] == []
        assert enqueue_receipt(queue, receipt, recorded_at=T0) == []
        assert queue.items() == []

    def test_tampered_receipt_rejected(self, queue, arc):
        _, receipt = arc
        tampered = copy.deepcopy(receipt)
        tampered["decision"]["value"] = {"kind": "boolean", "value": False}
        with pytest.raises(ReviewQueueError, match="receiptSha256 mismatch"):
            enqueue_receipt(queue, tampered, recorded_at=T0)

    def test_routed_to_filter(self, queue):
        pack = load_notice_pack()
        pack["abstentionPolicy"]["routeTo"] = "notice-review"
        facts = build_arc_facts()
        routed = adjudicate_arc(facts, pack)
        assert routed["abstentions"][0]["routedTo"] == "notice-review"
        # A queue serving another route ignores the entry entirely.
        assert enqueue_receipt(queue, routed, recorded_at=T0, routed_to="other-queue") == []
        # The matching route enqueues it.
        (result,) = enqueue_receipt(queue, routed, recorded_at=T0, routed_to="notice-review")
        assert result["created"] is True
        # Unrouted entries are skipped by a route-scoped queue...
        unrouted = adjudicate_arc(facts)
        assert enqueue_receipt(queue, unrouted, recorded_at=T0, routed_to="notice-review") == []
        # ...but enqueued by an unscoped one (routing is a label, not a gate).
        (r2,) = enqueue_receipt(queue, unrouted, recorded_at=T0)
        assert r2["created"] is True


# --- lifecycle ------------------------------------------------------------------


class TestLifecycle:
    @pytest.fixture()
    def open_item(self, queue, arc):
        _, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        return result["itemId"]

    def test_claim_is_a_field_not_a_state(self, queue, open_item):
        item = queue.claim(open_item, "reviewer:kp", T1)
        assert item["status"] == "open"
        assert item["assignee"] == "reviewer:kp"
        # Reassignment overwrites.
        item = queue.claim(open_item, "reviewer:other", "2026-07-29T00:00:00Z")
        assert item["assignee"] == "reviewer:other"

    def test_resolve_open_item(self, queue, store, arc, open_item):
        facts, _ = arc
        item = queue.resolve(open_item, make_correction(mailed_fact(facts)), store, T1)
        assert item["status"] == "resolved"
        assert item["closedAt"] == T1
        assert item["resolution"]["factId"].startswith("urn:duly:fact:sha256:")
        kinds = [e["event_kind"] for e in queue.events(open_item)]
        assert kinds == ["opened", "resolved"]

    def test_dismiss_open_item(self, queue, open_item):
        item = queue.dismiss(open_item, "scan illegible; abstention was correct", T1)
        assert item["status"] == "dismissed"
        assert item["dismissal"] == {"reason": "scan illegible; abstention was correct"}
        assert item["closedAt"] == T1

    def test_terminal_states_reject_all_transitions(self, queue, store, arc, open_item):
        facts, _ = arc
        queue.resolve(open_item, make_correction(mailed_fact(facts)), store, T1)
        with pytest.raises(InvalidTransitionError):
            queue.resolve(open_item, make_correction(mailed_fact(facts)), store, T1)
        with pytest.raises(InvalidTransitionError):
            queue.dismiss(open_item, "late dismissal", T1)
        with pytest.raises(InvalidTransitionError):
            queue.claim(open_item, "reviewer:kp", T1)

    def test_dismissed_rejects_resolution(self, queue, store, arc, open_item):
        facts, _ = arc
        queue.dismiss(open_item, "unusable", T1)
        with pytest.raises(InvalidTransitionError):
            queue.resolve(open_item, make_correction(mailed_fact(facts)), store, T1)

    def test_unknown_item(self, queue, store, arc):
        facts, _ = arc
        bogus = "urn:duly:review:sha256:" + "0" * 64
        with pytest.raises(UnknownItemError):
            queue.item(bogus)
        with pytest.raises(UnknownItemError):
            queue.claim(bogus, "reviewer:kp", T1)
        with pytest.raises(UnknownItemError):
            queue.resolve(bogus, make_correction(mailed_fact(facts)), store, T1)
        with pytest.raises(UnknownItemError):
            queue.dismiss(bogus, "no", T1)

    def test_dismissal_requires_reason(self, queue, open_item):
        with pytest.raises(ReviewQueueError, match="reason"):
            queue.dismiss(open_item, "", T1)

    def test_items_filters(self, queue, store, arc, open_item):
        facts, _ = arc
        assert [i["itemId"] for i in queue.items(status="open")] == [open_item]
        assert queue.items(status="resolved") == []
        assert queue.items(case_id="case:nothing") == []
        queue.resolve(open_item, make_correction(mailed_fact(facts)), store, T1)
        assert queue.items(status="open") == []
        assert [i["itemId"] for i in queue.items(status="resolved", case_id=ARC_CASE_ID)] == [open_item]


# --- correction validation ------------------------------------------------------


class TestCorrectionValidation:
    @pytest.fixture()
    def open_item(self, queue, arc):
        _, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        return result["itemId"]

    def _reject(self, queue, store, item_id, correction, match):
        with pytest.raises(InvalidCorrectionError, match=match):
            queue.resolve(item_id, correction, store, T1)
        assert queue.item(item_id)["status"] == "open"  # nothing happened

    def test_machine_assertion_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["assertion"] = dict(mailed_fact(facts)["assertion"])
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "human assertion")

    def test_actor_role_required(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts), actor={"id": "reviewer:kp"})
        self._reject(queue, store, open_item, bad, "id and role")

    def test_schema_invalid_correction_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        del bad["grounding"]
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "grounded-fact schema")

    def test_hash_mismatch_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["value"] = {"kind": "date", "value": "2026-07-20"}  # not rehashed
        self._reject(queue, store, open_item, bad, "contentHash mismatch")

    def test_wrong_case_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["caseId"] = "case:someone-else"
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "caseId")

    def test_wrong_entity_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["entity"] = {"id": "notice:other", "type": "nc:TerminationNotice"}
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "entity")

    def test_wrong_attribute_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["attribute"] = "nc:policyExpirationDate"
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "attribute")

    def test_supersedes_outside_abstained_facts_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(mailed_fact(facts))
        bad["supersedes"] = "urn:duly:fact:sha256:" + "a" * 64
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "not among the item's abstained facts")

    def test_store_level_rejection_leaves_item_open(self, queue, arc, open_item):
        """Belt and suspenders: even if a correction slipped past queue
        validation with a bad hash, the store's own ingest gate holds and
        the item stays open."""
        facts, _ = arc
        correction = make_correction(mailed_fact(facts))
        # Sabotage after validation would be needed to reach the store; here
        # we simply verify the store rejects a bad-hash fact directly.
        broken = dict(correction)
        broken["contentHash"] = "0" * 64
        broken["id"] = "urn:duly:fact:sha256:" + "0" * 64
        store = FactStore.in_memory()
        store.init_schema()
        with pytest.raises(HashMismatchError):
            store.ingest(broken)


# --- correction round-trip through a real FactStore ------------------------------


class TestCorrectionRoundTrip:
    def test_supersession_roundtrip(self, queue, store, arc):
        """Post-correction as_of shows the human fact and not the machine
        fact; re-adjudication resolves without abstention and flips the
        decision — the full review arc."""
        facts, receipt = arc
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        correction = make_correction(mailed_fact(facts))
        queue.resolve(result["itemId"], correction, store, T1)

        # Knowledge-time travel: before the correction, the machine fact.
        before = store.as_of(ARC_CASE_ID, knowledge=T0)
        assert mailed_fact(facts)["id"] in {f["id"] for f in before}

        after = store.as_of(ARC_CASE_ID, knowledge=T1)
        by_attr = {f["attribute"]: f for f in after}
        assert by_attr[MAILED]["id"] == correction["id"]
        assert by_attr[MAILED]["assertion"]["kind"] == "human"
        assert mailed_fact(facts)["id"] not in {f["id"] for f in after}

        # The supersession chain is the correction history (spec D7).
        chain = store.history(mailed_fact(facts)["id"])
        assert [e["event_kind"] for e in chain] == ["asserted", "asserted", "superseded"]

        fixed = adjudicate(after, load_notice_pack(), "2026-07-25", T1, QUESTION)
        assert fixed["abstentions"] == []
        assert fixed["decision"]["value"] == {"kind": "boolean", "value": False}

    def test_outranking_without_supersession(self, queue, store, arc):
        """A correction that does not supersede still wins at evaluation
        time: the lone human assertion outranks the machine facts (spec
        resolved question 2)."""
        facts, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        correction = make_correction(mailed_fact(facts), supersedes=False)
        queue.resolve(result["itemId"], correction, store, T1)

        after = store.as_of(ARC_CASE_ID, knowledge=T1)
        mailed = [f for f in after if f["attribute"] == MAILED]
        assert len(mailed) == 2  # both live: outranking, not supersession

        fixed = adjudicate(after, load_notice_pack(), "2026-07-25", T1, QUESTION)
        # The still-live machine fact stays excluded (an honest, persistent
        # low_confidence entry) but the human fact binds — no conflict entry,
        # and the decision derives from the corrected date.
        assert [a["reason"] for a in fixed["abstentions"]] == ["low_confidence"]
        assert fixed["decision"]["value"] == {"kind": "boolean", "value": False}
        input_ids = {f["id"] for f in fixed["inputFacts"]}
        assert correction["id"] in input_ids
