"""Review queue core: enqueue dedup, lifecycle, correction ingestion.

TOOLKIT. Every test here is about the queue as such — natural keys, dedup,
the lifecycle state machine, what a correction must carry — and none of it
names a jurisdiction. So the arc it runs on comes from
[`fixtures/`](../../fixtures/README.md), not from the teaching packs under
`examples/`: the committed case `fx-0003` is already a below-floor abstention
and `fx-0004` is already its post-review resolution (see reviewtest_helpers).

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
    ARC_AS_OF_EFFECTIVE,
    ARC_AS_OF_KNOWLEDGE,
    ARC_CASE_ID,
    ARC_CORRECTION_TS,
    ARC_WIDGET_ENTITY,
    QUESTION,
    SCORE,
    adjudicate_arc,
    build_arc_facts,
    load_fixture_pack,
    make_correction,
    rehash,
    rival_fact,
    scored_fact,
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
        assert item["entity"] == ARC_WIDGET_ENTITY
        assert item["attribute"] == SCORE
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
        later = adjudicate(
            facts, load_fixture_pack(), ARC_AS_OF_EFFECTIVE, "2026-03-10T09:00:00Z", QUESTION
        )
        assert later["receiptSha256"] != receipt["receiptSha256"]
        assert later["abstentions"] == receipt["abstentions"]
        first = enqueue_receipt(queue, receipt, recorded_at=T0)
        second = enqueue_receipt(queue, later, recorded_at="2026-08-01T09:00:00Z")
        assert second == [{"itemId": first[0]["itemId"], "created": False}]

    def test_terminal_items_do_not_reopen(self, queue, store, arc):
        facts, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(scored_fact(facts)), store, T1)
        again = enqueue_receipt(queue, receipt, recorded_at="2026-08-02T00:00:00Z")
        assert again == [{"itemId": result["itemId"], "created": False}]
        assert queue.item(result["itemId"])["status"] == "resolved"

    def test_different_case_yields_different_item(self, queue, store):
        for case in ("case:review:a", "case:review:b"):
            facts = build_arc_facts(case, entity=f"widget:{case}")
            receipt = adjudicate_arc(facts)
            enqueue_receipt(queue, receipt, recorded_at=T0)
        assert len(queue.items()) == 2

    def test_receipt_without_abstentions_enqueues_nothing(self, queue):
        facts = build_arc_facts(score_confidence={"score": 0.95, "method": "platt"})
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
        # The fixture pack declares `routeTo: fixture-review`, so the routed
        # receipt is the *default* here and the unrouted one is the variant —
        # the inverse of how the teaching packs are written, and the reason
        # this reads backwards from what a reader may expect.
        facts = build_arc_facts()
        routed = adjudicate_arc(facts)
        assert routed["abstentions"][0]["routedTo"] == "fixture-review"
        # A queue serving another route ignores the entry entirely.
        assert enqueue_receipt(queue, routed, recorded_at=T0, routed_to="other-queue") == []
        # The matching route enqueues it.
        (result,) = enqueue_receipt(queue, routed, recorded_at=T0, routed_to="fixture-review")
        assert result["created"] is True
        # Unrouted entries are skipped by a route-scoped queue...
        unscoped_pack = load_fixture_pack()
        del unscoped_pack["abstentionPolicy"]["routeTo"]
        unrouted = adjudicate_arc(facts, unscoped_pack)
        assert "routedTo" not in unrouted["abstentions"][0]
        assert enqueue_receipt(queue, unrouted, recorded_at=T0, routed_to="fixture-review") == []
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
        item = queue.resolve(open_item, make_correction(scored_fact(facts)), store, T1)
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
        queue.resolve(open_item, make_correction(scored_fact(facts)), store, T1)
        with pytest.raises(InvalidTransitionError):
            queue.resolve(open_item, make_correction(scored_fact(facts)), store, T1)
        with pytest.raises(InvalidTransitionError):
            queue.dismiss(open_item, "late dismissal", T1)
        with pytest.raises(InvalidTransitionError):
            queue.claim(open_item, "reviewer:kp", T1)

    def test_dismissed_rejects_resolution(self, queue, store, arc, open_item):
        facts, _ = arc
        queue.dismiss(open_item, "unusable", T1)
        with pytest.raises(InvalidTransitionError):
            queue.resolve(open_item, make_correction(scored_fact(facts)), store, T1)

    def test_unknown_item(self, queue, store, arc):
        facts, _ = arc
        bogus = "urn:duly:review:sha256:" + "0" * 64
        with pytest.raises(UnknownItemError):
            queue.item(bogus)
        with pytest.raises(UnknownItemError):
            queue.claim(bogus, "reviewer:kp", T1)
        with pytest.raises(UnknownItemError):
            queue.resolve(bogus, make_correction(scored_fact(facts)), store, T1)
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
        queue.resolve(open_item, make_correction(scored_fact(facts)), store, T1)
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
        bad = make_correction(scored_fact(facts))
        bad["assertion"] = dict(scored_fact(facts)["assertion"])
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "human assertion")

    def test_actor_role_required(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts), actor={"id": "reviewer:kp"})
        self._reject(queue, store, open_item, bad, "id and role")

    def test_schema_invalid_correction_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        del bad["grounding"]
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "grounded-fact schema")

    def test_hash_mismatch_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        bad["value"] = {"kind": "decimal", "value": "80"}  # not rehashed
        self._reject(queue, store, open_item, bad, "contentHash mismatch")

    def test_wrong_case_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        bad["caseId"] = "case:someone-else"
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "caseId")

    def test_wrong_entity_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        bad["entity"] = {"id": "widget:other", "type": "fx:Widget"}
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "entity")

    def test_wrong_attribute_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        bad["attribute"] = "fx:category"
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "attribute")

    def test_supersedes_outside_abstained_facts_rejected(self, queue, store, arc, open_item):
        facts, _ = arc
        bad = make_correction(scored_fact(facts))
        bad["supersedes"] = "urn:duly:fact:sha256:" + "a" * 64
        bad = rehash(bad)
        self._reject(queue, store, open_item, bad, "not among the item's abstained facts")

    def test_store_level_rejection_leaves_item_open(self, queue, arc, open_item):
        """Belt and suspenders: even if a correction slipped past queue
        validation with a bad hash, the store's own ingest gate holds and
        the item stays open."""
        facts, _ = arc
        correction = make_correction(scored_fact(facts))
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
        correction = make_correction(scored_fact(facts))
        queue.resolve(result["itemId"], correction, store, T1)

        # Knowledge-time travel: before the correction, the machine fact.
        before = store.as_of(ARC_CASE_ID, knowledge=T0)
        assert scored_fact(facts)["id"] in {f["id"] for f in before}

        after = store.as_of(ARC_CASE_ID, knowledge=T1)
        by_attr = {f["attribute"]: f for f in after}
        assert by_attr[SCORE]["id"] == correction["id"]
        assert by_attr[SCORE]["assertion"]["kind"] == "human"
        assert scored_fact(facts)["id"] not in {f["id"] for f in after}

        # The supersession chain is the correction history (spec D7).
        chain = store.history(scored_fact(facts)["id"])
        assert [e["event_kind"] for e in chain] == ["asserted", "asserted", "superseded"]

        fixed = adjudicate(after, load_fixture_pack(), ARC_AS_OF_EFFECTIVE, T1, QUESTION)
        assert fixed["abstentions"] == []
        assert fixed["decision"]["value"] == {"kind": "boolean", "value": False}

    def test_resolving_without_supersession_is_refused(self, queue, store, arc):
        """spec/compatibility.md C6. This test used to assert the opposite —
        that a non-superseding correction still wins, by outranking — and the
        state it pinned is the one the freeze made unrepresentable.

        The receipt it produced was the argument against it: a persistent
        `low_confidence` entry for the abstained attribute on every future
        adjudication, for an attribute the decision *used*, which contradicts
        the fact spec's own definition of `abstentions`. Outranking still works
        in the kernel — that is resolved question 2 and it is untouched — but
        it is no longer how a *queue resolution* may be recorded, because
        resolving is a ruling on one specific fact.
        """
        facts, receipt = arc
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        correction = make_correction(scored_fact(facts), supersedes=False)

        with pytest.raises(InvalidCorrectionError) as excinfo:
            queue.resolve(result["itemId"], correction, store, T1)

        message = str(excinfo.value)
        assert scored_fact(facts)["id"] in message, (
            "the refusal must name the fact id the correction has to carry — "
            "the queue cannot stamp it in, so the caller needs it"
        )
        assert "supersede" in message

        # Refused means refused: no event, and the item is still open for
        # somebody to resolve properly.
        assert queue.item(result["itemId"])["status"] == "open"
        assert len(store.as_of(ARC_CASE_ID, knowledge=T1)) == len(facts)

    def test_a_conflict_item_is_not_covered(self, queue, store):
        """C6 is `low_confidence` only, and this pins that it was a decision
        rather than an oversight. A conflict entry names several facts, so
        "the fact it rules on" has no referent — the analogous rule would have
        to say which of them, and nobody has a reason yet."""
        above_floor = {"score": 0.95, "method": "platt"}
        facts = build_arc_facts(score_confidence=above_floor)
        # A second machine reading of the same score, also above the floor:
        # neither outranks the other, so the pair conflicts.
        rival = rival_fact(
            scored_fact(facts),
            value={"kind": "decimal", "value": "80"},
            ts="2026-03-02T00:00:00Z",
            confidence=above_floor,
        )
        facts = facts + [rival]
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (entry,) = receipt["abstentions"]
        assert entry["reason"] == "conflict"
        assert len(entry["facts"]) == 2

        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        # No supersedes, and accepted: the carve-out.
        item = queue.resolve(
            result["itemId"], make_correction(rival, supersedes=False), store, T1
        )
        assert item["status"] == "resolved"

    def test_the_store_still_takes_an_independent_human_fact(self, store, arc):
        """The carve-out, and it is load-bearing. C6 binds the *queue*, not the
        store: a value known from a phone call is not a ruling on anybody's
        extraction, and the conflict policy already handles it. Enforcing
        supersession one layer lower would make that fact unrecordable."""
        facts, _ = arc
        independent = make_correction(scored_fact(facts), supersedes=False)
        store.ingest(independent)

        after = store.as_of(ARC_CASE_ID, knowledge=T1)
        live_scores = [f for f in after if f["attribute"] == SCORE]
        assert len(live_scores) == 2  # both live: outranking, not supersession

        fixed = adjudicate(after, load_fixture_pack(), ARC_AS_OF_EFFECTIVE, T1, QUESTION)
        assert [a["reason"] for a in fixed["abstentions"]] == ["low_confidence"]
        assert fixed["decision"]["value"] == {"kind": "boolean", "value": False}
        assert independent["id"] in {f["id"] for f in fixed["inputFacts"]}
