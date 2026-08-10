"""Calibration label export: (raw_score, correct) pairs and value equality.

TOOLKIT. The export's contract (duly_review.queue.ReviewQueue.calibration_pairs):
confirm -> (score, 1); contradict -> (score, 0); dismissals, no-confidence
entries, and store-unknown machine facts -> NO pair, never a guessed one.

None of that is about any particular pack, so the arcs come from
[`fixtures/`](../../fixtures/README.md). `TestValueEquality` below is purer
still — it calls `values_equal` on literal value documents and reaches no
corpus at all, which is why it was the only part of this file the move did
not break.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviewtest_helpers import (  # noqa: E402
    ARC_AS_OF_KNOWLEDGE,
    ARC_CORRECTION_TS,
    ARC_SCORE_CONFIDENCE,
    SCORE,
    adjudicate_arc,
    build_arc_facts,
    make_correction,
    rehash,
    scored_fact,
)

from duly_calibration import PlattCalibrator  # noqa: E402
from duly_calibration.base import validate_pairs  # noqa: E402
from duly_review import ReviewQueue, calibration_pairs, enqueue_receipt  # noqa: E402
from duly_store.store import FactStore  # noqa: E402

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


def _open_arc(queue, store, case_suffix: str, *, score_confidence=None, ingest=True):
    """One enqueued arc; returns (facts, item_id)."""
    case = f"case:review:labels-{case_suffix}"
    facts = build_arc_facts(
        case,
        score_confidence=score_confidence,
        entity=f"widget:{case_suffix}",
    )
    if ingest:
        for f in facts:
            store.ingest(f)
    receipt = adjudicate_arc(facts)
    (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
    return facts, result["itemId"]


class TestPairEmission:
    def test_confirmation_yields_correct_1(self, queue, store):
        facts, item_id = _open_arc(queue, store, "confirm")
        queue.resolve(item_id, make_correction(scored_fact(facts)), store, T1)
        assert calibration_pairs(queue) == [(ARC_SCORE_CONFIDENCE["score"], 1)]

    def test_contradiction_yields_correct_0(self, queue, store):
        facts, item_id = _open_arc(queue, store, "contradict")
        wrong_score_fixed = make_correction(
            scored_fact(facts), value={"kind": "decimal", "value": "80"}
        )
        queue.resolve(item_id, wrong_score_fixed, store, T1)
        assert calibration_pairs(queue) == [(ARC_SCORE_CONFIDENCE["score"], 0)]

    def test_dismissal_yields_no_pair(self, queue, store):
        _, item_id = _open_arc(queue, store, "dismiss")
        queue.dismiss(item_id, "scan illegible", T1)
        assert calibration_pairs(queue) == []

    def test_no_confidence_entry_yields_no_pair(self, queue, store):
        """A machine fact with no confidence fails closed under the policy;
        its entry carries no score, so there is nothing honest to pair."""
        facts = build_arc_facts("case:review:labels-nc", entity="widget:nc")
        target = scored_fact(facts)
        stripped = {k: v for k, v in target.items() if k != "confidence"}
        stripped = rehash(stripped)
        facts = [stripped if f["attribute"] == SCORE else f for f in facts]
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (entry,) = receipt["abstentions"]
        assert "confidence" not in entry
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(stripped), store, T1)
        assert queue.item(result["itemId"])["status"] == "resolved"
        assert calibration_pairs(queue) == []

    def test_machine_fact_not_in_store_yields_no_pair(self, queue, store):
        """When the abstained fact never reached the store, no machine value
        exists to compare against — no pair, never a guessed one."""
        facts, item_id = _open_arc(queue, store, "nostore", ingest=False)
        queue.resolve(item_id, make_correction(scored_fact(facts)), store, T1)
        assert queue.item(item_id)["status"] == "resolved"
        assert calibration_pairs(queue) == []

    def test_open_items_yield_no_pair(self, queue, store):
        _open_arc(queue, store, "still-open")
        assert calibration_pairs(queue) == []

    def test_export_order_is_enqueue_order(self, queue, store):
        pairs_in = []
        for i, (suffix, confirm) in enumerate(
            [("a", 1), ("b", 0), ("c", 1)]
        ):
            score = 0.5 + i / 10
            facts, item_id = _open_arc(
                queue, store, suffix, score_confidence={"score": score, "method": "platt"}
            )
            value = None if confirm else {"kind": "decimal", "value": "80"}
            queue.resolve(item_id, make_correction(scored_fact(facts), value=value), store, T1)
            pairs_in.append((score, confirm))
        assert calibration_pairs(queue) == pairs_in

    def test_pairs_are_consumable_by_duly_calibration(self, queue, store):
        """The seam the M3 loop exists for: the export type-checks through
        duly_calibration's pair validation and (given both classes) fits."""
        for i in range(4):
            confirm = i % 2 == 0
            facts, item_id = _open_arc(
                queue, store, f"fit-{i}",
                score_confidence={"score": 0.3 + i / 10, "method": "platt"},
            )
            value = None if confirm else {"kind": "decimal", "value": "80"}
            queue.resolve(item_id, make_correction(scored_fact(facts), value=value), store, T1)
        pairs = calibration_pairs(queue)
        assert validate_pairs(pairs, require_both_classes=True) == pairs
        params = PlattCalibrator().fit(pairs)
        assert set(params) == {"a", "b"}


class TestValueEquality:
    """values_equal semantics, kind by kind (documented on the function)."""

    def test_decimal_numeric_equality(self):
        from duly_review import values_equal

        assert values_equal({"kind": "decimal", "value": "45"}, {"kind": "decimal", "value": "45.0"})
        assert not values_equal({"kind": "decimal", "value": "45"}, {"kind": "decimal", "value": "45.1"})

    def test_money_amount_and_currency(self):
        from duly_review import values_equal

        a = {"kind": "money", "amount": "100.0", "currency": "USD"}
        assert values_equal(a, {"kind": "money", "amount": "100.00", "currency": "USD"})
        assert not values_equal(a, {"kind": "money", "amount": "100.00", "currency": "EUR"})
        assert not values_equal(a, {"kind": "money", "amount": "100.01", "currency": "USD"})

    def test_datetime_instant_equality(self):
        from duly_review import values_equal

        a = {"kind": "datetime", "value": "2026-07-25T00:00:00Z"}
        assert values_equal(a, {"kind": "datetime", "value": "2026-07-25T00:00:00+00:00"})
        assert not values_equal(a, {"kind": "datetime", "value": "2026-07-25T00:00:01Z"})

    def test_date_exact_string(self):
        from duly_review import values_equal

        assert values_equal({"kind": "date", "value": "2026-07-25"}, {"kind": "date", "value": "2026-07-25"})
        assert not values_equal({"kind": "date", "value": "2026-07-25"}, {"kind": "date", "value": "2026-07-24"})

    def test_code_ignores_code_system_version(self):
        from duly_review import values_equal

        a = {"kind": "code", "value": "US-NY", "codeSystem": "iso-3166-2", "codeSystemVersion": "2020"}
        b = {"kind": "code", "value": "US-NY", "codeSystem": "iso-3166-2", "codeSystemVersion": "2024"}
        assert values_equal(a, b)
        assert not values_equal(a, {"kind": "code", "value": "US-NY", "codeSystem": "other"})

    def test_kind_mismatch_is_never_equal(self):
        from duly_review import values_equal

        assert not values_equal(
            {"kind": "string", "value": "45"}, {"kind": "decimal", "value": "45"}
        )

    def test_boolean_and_string_exact(self):
        from duly_review import values_equal

        assert values_equal({"kind": "boolean", "value": True}, {"kind": "boolean", "value": True})
        assert not values_equal({"kind": "boolean", "value": True}, {"kind": "boolean", "value": False})
        assert not values_equal({"kind": "string", "value": "a"}, {"kind": "string", "value": "A"})
