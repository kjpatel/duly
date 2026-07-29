"""Corrections auto-become golden regression cases.

Includes the provenance lock for the committed case: ``review-0001`` in
golden/ was produced by exactly the arc `run_committed_arc` replays, and
`test_committed_case_regenerates_byte_identically` proves it stays true.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviewtest_helpers import (  # noqa: E402
    ARC_AS_OF_KNOWLEDGE,
    ARC_CORRECTION_TS,
    NOTICE_PACK_PATH,
    REPO_ROOT,
    adjudicate_arc,
    build_arc_facts,
    mailed_fact,
    make_correction,
)

from duly_assurance.verify import main as verify_main  # noqa: E402
from duly_review import (  # noqa: E402
    GoldenCaseError,
    ReviewQueue,
    enqueue_receipt,
    next_review_case_id,
    resolved_item_to_golden_case,
)
from duly_store.store import FactStore  # noqa: E402

T0 = ARC_AS_OF_KNOWLEDGE
T1 = ARC_CORRECTION_TS


def run_committed_arc(golden_dir: Path, *, case_id: str | None = "review-0001") -> dict:
    """The exact arc behind the committed golden case review-0001:
    machine mailed-date abstains (0.62 < the pack's 0.9 floor) -> the
    presumption stands -> human confirms the date, superseding the machine
    fact -> the decision resolves to non-compliant (38 < 45 days)."""
    store = FactStore.in_memory()
    store.init_schema()
    queue = ReviewQueue.in_memory()

    facts = build_arc_facts()
    for f in facts:
        store.ingest(f)
    receipt = adjudicate_arc(facts)
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert [a["reason"] for a in receipt["abstentions"]] == ["low_confidence"]

    (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
    correction = make_correction(mailed_fact(facts))
    queue.resolve(result["itemId"], correction, store, T1)

    return resolved_item_to_golden_case(
        queue,
        store,
        result["itemId"],
        pack_path=NOTICE_PACK_PATH,
        golden_dir=golden_dir,
        case_id=case_id,
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class TestGoldenGeneration:
    def test_full_arc_produces_a_verifiable_golden_case(self, tmp_path):
        out = run_committed_arc(tmp_path, case_id=None)
        assert out["caseId"] == "review-0001"
        case = yaml.safe_load((tmp_path / "cases" / "review-0001" / "case.yaml").read_text())
        assert case == {
            "id": "review-0001",
            "pack": NOTICE_PACK_PATH,
            "question": "nc:noticeCompliant",
            "asOfEffective": "2026-07-25T00:00:00Z",
            "asOfKnowledge": T1,
        }
        # Post-correction facts: the human mailed date, no machine duplicate.
        facts_dir = tmp_path / "cases" / "review-0001" / "facts"
        names = sorted(p.name for p in facts_dir.glob("*.json"))
        assert names == [
            "nc-governingState.json",
            "nc-noticeMailedDate.json",
            "nc-noticeType.json",
            "nc-policyExpirationDate.json",
        ]
        import json

        mailed = json.loads((facts_dir / "nc-noticeMailedDate.json").read_text())
        assert mailed["assertion"]["kind"] == "human"
        assert mailed["supersedes"].startswith("urn:duly:fact:sha256:")
        # The decision flipped: presumption-compliant became non-compliant.
        assert out["receipt"]["decision"]["value"] == {"kind": "boolean", "value": False}
        assert out["receipt"]["abstentions"] == []
        # And the replay verifier accepts the case byte-for-byte.
        assert verify_main(["--golden", str(tmp_path)]) == 0

    def test_committed_case_regenerates_byte_identically(self, tmp_path):
        """golden/cases/review-0001 + its receipt ARE this arc's output."""
        run_committed_arc(tmp_path)
        for rel in sorted(
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if p.is_file()
        ):
            committed = REPO_ROOT / "golden" / rel
            assert committed.is_file(), f"missing committed file golden/{rel}"
            assert (tmp_path / rel).read_bytes() == committed.read_bytes(), (
                f"golden/{rel} differs from the review-arc regeneration"
            )

    def test_next_review_case_id_allocation(self, tmp_path):
        assert next_review_case_id(tmp_path) == "review-0001"
        run_committed_arc(tmp_path)
        assert next_review_case_id(tmp_path) == "review-0002"
        # A stray receipt without a case dir still blocks its id.
        (tmp_path / "receipts" / "review-0002.json").write_text("{}")
        assert next_review_case_id(tmp_path) == "review-0003"

    def test_existing_case_id_refused(self, tmp_path):
        run_committed_arc(tmp_path)
        with pytest.raises(GoldenCaseError, match="already exists"):
            run_committed_arc(tmp_path)

    def test_only_resolved_items_convert(self, tmp_path):
        store = FactStore.in_memory()
        store.init_schema()
        queue = ReviewQueue.in_memory()
        facts = build_arc_facts()
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        with pytest.raises(GoldenCaseError, match="only resolved items"):
            resolved_item_to_golden_case(
                queue, store, result["itemId"],
                pack_path=NOTICE_PACK_PATH, golden_dir=tmp_path,
            )
        queue.dismiss(result["itemId"], "unusable", T1)
        with pytest.raises(GoldenCaseError, match="only resolved items"):
            resolved_item_to_golden_case(
                queue, store, result["itemId"],
                pack_path=NOTICE_PACK_PATH, golden_dir=tmp_path,
            )

    def test_store_without_the_case_refused(self, tmp_path):
        """Golden cases are projections of the store: pointing the converter
        at a store that never saw the case (a wrong --facts-db) fails loudly
        instead of freezing an empty case."""
        store = FactStore.in_memory()
        store.init_schema()
        queue = ReviewQueue.in_memory()
        facts = build_arc_facts()
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(mailed_fact(facts)), store, T1)
        other_store = FactStore.in_memory()
        other_store.init_schema()
        with pytest.raises(GoldenCaseError, match="no facts"):
            resolved_item_to_golden_case(
                queue, other_store, result["itemId"],
                pack_path=NOTICE_PACK_PATH, golden_dir=tmp_path,
            )

    def test_bad_pack_path_refused(self, tmp_path):
        store = FactStore.in_memory()
        store.init_schema()
        queue = ReviewQueue.in_memory()
        facts = build_arc_facts()
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(mailed_fact(facts)), store, T1)
        with pytest.raises(GoldenCaseError, match="pack not found"):
            resolved_item_to_golden_case(
                queue, store, result["itemId"],
                pack_path="rulepacks/does-not-exist/pack.yaml", golden_dir=tmp_path,
            )


class TestCli:
    def test_python_m_duly_review_golden(self, tmp_path):
        """The CLI hook end to end, over file-backed databases."""
        queue_db = tmp_path / "review.db"
        facts_db = tmp_path / "facts.db"
        golden = tmp_path / "golden"

        store = FactStore(str(facts_db))
        store.init_schema()
        queue = ReviewQueue(str(queue_db))
        queue.init_schema()
        facts = build_arc_facts()
        for f in facts:
            store.ingest(f)
        receipt = adjudicate_arc(facts)
        (result,) = enqueue_receipt(queue, receipt, recorded_at=T0)
        queue.resolve(result["itemId"], make_correction(mailed_fact(facts)), store, T1)
        store.close()
        queue.close()

        proc = subprocess.run(
            [
                sys.executable, "-m", "duly_review", "golden",
                "--db", str(queue_db),
                "--facts-db", str(facts_db),
                "--item", result["itemId"],
                "--pack", NOTICE_PACK_PATH,
                "--golden", str(golden),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        assert "wrote golden case review-0001" in proc.stdout
        assert verify_main(["--golden", str(golden)]) == 0
