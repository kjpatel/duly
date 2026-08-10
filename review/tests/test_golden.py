"""Corrections auto-become golden regression cases.

This file is deliberately in two halves.

`TestGoldenGeneration` and `TestCli` are **toolkit**: the converter's contract
(only resolved items, the store must hold the case, the pack path must
resolve, ids allocate in the `review-NNNN` series, the output replays) says
nothing about any jurisdiction, so they run on the corpus in
[`fixtures/`](../../fixtures/README.md).

`TestCommittedProvenance` is **example content**: its subject genuinely is the
committed golden case `review-0001`, so it stays pointed at
`examples/golden/` and moves with it. That case is preserved forever — the
corpus generator skips `review-*` — which is what makes a byte comparison
against it meaningful rather than merely current.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest review/tests -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviewtest_helpers import (  # noqa: E402
    ARC_AS_OF_KNOWLEDGE,
    ARC_CORRECTION_TS,
    ARC_SOURCE_CASE,
    FIXTURE_CORPUS,
    FIXTURE_PACK_PATH,
    NOTICE_AS_OF_KNOWLEDGE,
    NOTICE_CORRECTION_TS,
    NOTICE_GOLDEN_DIR,
    NOTICE_PACK_PATH,
    NOTICE_REPO_ROOT,
    REPO_ROOT,
    adjudicate_arc,
    adjudicate_notice_arc,
    build_arc_facts,
    build_notice_arc_facts,
    committed_fixture_facts,
    make_correction,
    make_notice_correction,
    notice_mailed_fact,
    scored_fact,
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


def run_fixture_arc(golden_dir: Path, *, case_id: str | None = "review-0001") -> dict:
    """The fixture corpus's own review arc, run through the queue: the
    below-floor `fx:score` abstains (0.62 < the pack's 0.80 floor) -> the
    default presumption stands -> a human confirms the score, superseding the
    machine fact -> the decision resolves to not-permitted (12 < the 2026
    threshold of 50).

    This is `fixtures/cases/fx-0003` becoming `fixtures/cases/fx-0004`, which
    is why the corpus can anchor it (see `test_the_arc_is_the_committed_
    fixture_case`) rather than merely resemble it.
    """
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
    correction = make_correction(scored_fact(facts))
    queue.resolve(result["itemId"], correction, store, T1)

    return resolved_item_to_golden_case(
        queue,
        store,
        result["itemId"],
        pack_path=FIXTURE_PACK_PATH,
        golden_dir=golden_dir,
        repo_root=REPO_ROOT,
        case_id=case_id,
    )


class TestGoldenGeneration:
    def test_the_arc_is_the_committed_fixture_case(self):
        """The anchor, and the reason this suite's arc is not arbitrary.

        `build_arc_facts()` does not build a case that *looks like* fx-0003 —
        it returns fx-0003's committed facts, and `make_correction` returns
        fx-0004's committed correction. A helper that merely resembled the
        corpus would drift from it silently, and every assertion downstream
        would still pass while testing a shape nothing else in the repo has.
        """
        facts = build_arc_facts()
        assert facts == committed_fixture_facts(), (
            "the arc's machine facts must BE fixtures/cases/fx-0003/facts/*.json"
        )
        committed_receipt = json.loads(
            (FIXTURE_CORPUS / "receipts" / f"{ARC_SOURCE_CASE}.json").read_text()
        )
        assert adjudicate_arc(facts) == committed_receipt, (
            "the arc's first adjudication must BE the committed fx-0003 receipt"
        )
        committed_correction = json.loads(
            (
                FIXTURE_CORPUS / "cases" / "fx-0004" / "facts" / "fx-score-corrected.json"
            ).read_text()
        )
        assert make_correction(scored_fact(facts)) == committed_correction, (
            "the arc's correction must BE fx-0004's committed corrected fact"
        )

    def test_full_arc_produces_a_verifiable_golden_case(self, tmp_path):
        out = run_fixture_arc(tmp_path, case_id=None)
        assert out["caseId"] == "review-0001"
        case = yaml.safe_load((tmp_path / "cases" / "review-0001" / "case.yaml").read_text())
        assert case == {
            "id": "review-0001",
            "pack": FIXTURE_PACK_PATH,
            "question": "fx:permitted",
            "asOfEffective": "2026-06-01T00:00:00Z",
            "asOfKnowledge": T1,
        }
        # Post-correction facts: the human score, no machine duplicate.
        facts_dir = tmp_path / "cases" / "review-0001" / "facts"
        names = sorted(p.name for p in facts_dir.glob("*.json"))
        assert names == ["fx-category.json", "fx-score.json"]

        score = json.loads((facts_dir / "fx-score.json").read_text())
        assert score["assertion"]["kind"] == "human"
        assert score["supersedes"].startswith("urn:duly:fact:sha256:")
        # The decision flipped: presumption-permitted became not-permitted.
        assert out["receipt"]["decision"]["value"] == {"kind": "boolean", "value": False}
        assert out["receipt"]["abstentions"] == []
        # And the replay verifier accepts the case byte-for-byte.
        assert verify_main(["--golden", str(tmp_path)]) == 0

    def test_next_review_case_id_allocation(self, tmp_path):
        assert next_review_case_id(tmp_path) == "review-0001"
        run_fixture_arc(tmp_path)
        assert next_review_case_id(tmp_path) == "review-0002"
        # A stray receipt without a case dir still blocks its id.
        (tmp_path / "receipts" / "review-0002.json").write_text("{}")
        assert next_review_case_id(tmp_path) == "review-0003"

    def test_existing_case_id_refused(self, tmp_path):
        run_fixture_arc(tmp_path)
        with pytest.raises(GoldenCaseError, match="already exists"):
            run_fixture_arc(tmp_path)

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
                pack_path=FIXTURE_PACK_PATH, golden_dir=tmp_path, repo_root=REPO_ROOT,
            )
        queue.dismiss(result["itemId"], "unusable", T1)
        with pytest.raises(GoldenCaseError, match="only resolved items"):
            resolved_item_to_golden_case(
                queue, store, result["itemId"],
                pack_path=FIXTURE_PACK_PATH, golden_dir=tmp_path, repo_root=REPO_ROOT,
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
        queue.resolve(result["itemId"], make_correction(scored_fact(facts)), store, T1)
        other_store = FactStore.in_memory()
        other_store.init_schema()
        with pytest.raises(GoldenCaseError, match="no facts"):
            resolved_item_to_golden_case(
                queue, other_store, result["itemId"],
                pack_path=FIXTURE_PACK_PATH, golden_dir=tmp_path, repo_root=REPO_ROOT,
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
        queue.resolve(result["itemId"], make_correction(scored_fact(facts)), store, T1)
        with pytest.raises(GoldenCaseError, match="pack not found"):
            resolved_item_to_golden_case(
                queue, store, result["itemId"],
                pack_path="fixtures/does-not-exist/pack.yaml", golden_dir=tmp_path,
                repo_root=REPO_ROOT,
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
        queue.resolve(result["itemId"], make_correction(scored_fact(facts)), store, T1)
        store.close()
        queue.close()

        proc = subprocess.run(
            [
                sys.executable, "-m", "duly_review", "golden",
                "--db", str(queue_db),
                "--facts-db", str(facts_db),
                "--item", result["itemId"],
                "--pack", FIXTURE_PACK_PATH,
                "--golden", str(golden),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        assert "wrote golden case review-0001" in proc.stdout
        assert verify_main(["--golden", str(golden)]) == 0


# --- EXAMPLE CONTENT (moves with examples/) -----------------------------------


def run_committed_arc(golden_dir: Path, *, case_id: str | None = "review-0001") -> dict:
    """EXAMPLE CONTENT (moves with examples/). The exact arc behind the
    committed golden case review-0001: machine mailed-date abstains (0.62 <
    the notice pack's 0.9 floor) -> the presumption stands -> human confirms
    the date, superseding the machine fact -> the decision resolves to
    non-compliant (38 < 45 days).
    """
    store = FactStore.in_memory()
    store.init_schema()
    queue = ReviewQueue.in_memory()

    facts = build_notice_arc_facts()
    for f in facts:
        store.ingest(f)
    receipt = adjudicate_notice_arc(facts)
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert [a["reason"] for a in receipt["abstentions"]] == ["low_confidence"]

    (result,) = enqueue_receipt(queue, receipt, recorded_at=NOTICE_AS_OF_KNOWLEDGE)
    correction = make_notice_correction(notice_mailed_fact(facts))
    queue.resolve(result["itemId"], correction, store, NOTICE_CORRECTION_TS)

    return resolved_item_to_golden_case(
        queue,
        store,
        result["itemId"],
        pack_path=NOTICE_PACK_PATH,
        golden_dir=golden_dir,
        # `case.yaml` records the pack path relative to the *corpus root's
        # parent* — `rulepacks/...`, not `examples/rulepacks/...` — which is
        # what `duly_assurance.corpus.resolve_pack_path` resolves it against
        # and why the move under `examples/` left those references alone.
        # Writing anything else here would change the committed bytes.
        repo_root=NOTICE_REPO_ROOT,
        case_id=case_id,
    )


class TestCommittedProvenance:
    """EXAMPLE CONTENT (moves with examples/). The subject is the committed
    case, not the converter."""

    def test_committed_case_regenerates_byte_identically(self, tmp_path):
        """examples/golden/cases/review-0001 + its receipt ARE this arc's
        output."""
        run_committed_arc(tmp_path)
        produced = sorted(
            str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()
        )
        # The loop below is a byte comparison over whatever the arc wrote, so
        # an arc that wrote nothing would pass it in silence. Name the count.
        assert len(produced) == 6, f"expected 6 regenerated files, got {produced}"
        for rel in produced:
            committed = NOTICE_GOLDEN_DIR / rel
            assert committed.is_file(), f"missing committed file examples/golden/{rel}"
            assert (tmp_path / rel).read_bytes() == committed.read_bytes(), (
                f"examples/golden/{rel} differs from the review-arc regeneration"
            )
