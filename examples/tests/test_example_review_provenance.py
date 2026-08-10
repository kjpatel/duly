"""`examples/golden/cases/review-0001` IS the output of this review arc.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted, with the arc it needs, from `review/tests/test_golden.py` and
`review/tests/reviewtest_helpers.py`. What stays there is the converter's
contract — only resolved items, the store must hold the case, the pack path
must resolve, ids allocate in the `review-NNNN` series, the output replays —
none of which names a jurisdiction, and all of which runs on the toolkit corpus
in [`fixtures/`](../../fixtures/README.md).

What is here is the other thing entirely: a *provenance lock*. The claim is
not that the exporter works but that these particular committed bytes are the
bytes this arc produces — machine mailed-date at 0.62 against the notice pack's
0.9 floor, so the deciding rule cannot bind and the presumption of compliance
stands; a human confirms 2026-07-25, superseding the machine fact; the decision
resolves non-compliant on 38 days of notice against NY's 45. `review-0001` is
preserved forever (the corpus generator skips `review-*`,
[`golden/README.md`](../golden/README.md)), which is what makes the byte
comparison meaningful rather than merely current — no seed can regenerate it,
so nothing can quietly move the target.

The arc is written out here rather than imported from `review/tests/`. It has
exactly one caller and it dies with the case it explains; leaving it behind
would leave a suite that no longer runs it maintaining facts in a vocabulary
that no longer exists. `finish_fact` is duplicated for the same reason
`exampletest_helpers.value_kinds` is (see its docstring): the two directories
cannot import each other's helpers, and the toolkit's copy must survive this
one's deletion.

Every timestamp is a fixed constant — no wall clock anywhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from exampletest_helpers import EXAMPLES, GOLDEN, RULEPACKS

from duly_kernel.api import adjudicate
from duly_review import ReviewQueue, enqueue_receipt, resolved_item_to_golden_case
from duly_store.store import FactStore, content_hash

#: As `examples/golden/cases/review-0001/case.yaml` records it, and therefore
#: what must be written back for the regeneration to be byte-identical: the
#: path is relative to the *corpus root's parent* (`examples/`), which is what
#: `duly_assurance.corpus.resolve_pack_path` resolves it against. The move
#: under `examples/` deliberately left these references alone for that reason.
PACK_PATH = "rulepacks/termination-notice-us-states/pack.yaml"

ONTOLOGY = "duly-starter-notice"
MAILED = "nc:noticeMailedDate"
QUESTION = "nc:noticeCompliant"

CASE_ID = "case:review:0001"
ENTITY = "notice:review-0001"
POLICY_ENTITY = "policy:review-0001"
MACHINE_TS = "2026-07-25T12:00:00Z"          # extraction time
AS_OF_EFFECTIVE = "2026-07-25"               # the mailed date
AS_OF_KNOWLEDGE = "2026-07-27T12:00:00Z"     # first adjudication
CORRECTION_TS = "2026-07-28T09:00:00Z"       # review resolution
MAILED_CONFIDENCE = {"score": 0.62, "method": "platt"}
REVIEWER = {"id": "reviewer:rq-demo", "role": "compliance-review"}


def finish_fact(doc: dict) -> dict:
    """Stamp contentHash and id onto a fact body (spec D8)."""
    digest = content_hash(doc)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **doc}


def load_notice_pack() -> dict:
    path = RULEPACKS / "termination-notice-us-states" / "pack.yaml"
    assert path.is_file(), f"no committed notice pack at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _notice_fact(
    entity_id: str, entity_type: str, attribute: str, value: dict,
    *, confidence: dict | None = None,
) -> dict:
    """A schema-valid machine-asserted GroundedFact (attestation grounding —
    this fixture, like the golden generator, does not fake document spans)."""
    ts = MACHINE_TS
    doc = {
        "caseId": CASE_ID,
        "entity": {"id": entity_id, "type": entity_type},
        "attribute": attribute,
        "value": value,
        "grounding": {
            "kind": "attestation",
            "actor": "review-arc-fixture",
            "channel": "synthetic",
            "at": ts,
        },
        "assertion": {
            "kind": "machine",
            "at": ts,
            "extractor": {"name": "review-arc-fixture", "version": "0.1.0"},
        },
        "confidence": confidence if confidence is not None else {"score": 1.0, "method": "raw"},
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": {"ontology": ONTOLOGY, "version": "0.1.0"},
    }
    return finish_fact(doc)


def build_notice_arc_facts() -> list[dict]:
    """The four machine facts behind `review-0001`. The mailed date carries a
    below-floor confidence (0.62 < the notice pack's 0.9 attribute floor);
    expiration 2026-09-01 minus mailed 2026-07-25 gives 38 days of notice
    against NY's 45-day minimum."""
    return [
        _notice_fact(
            ENTITY, "nc:TerminationNotice", "nc:noticeType",
            {
                "kind": "code",
                "value": "Nonrenewal",
                "codeSystem": "duly-starter-notice/notice-types",
                "codeSystemVersion": "0.1.0",
            },
        ),
        _notice_fact(
            ENTITY, "nc:TerminationNotice", MAILED,
            {"kind": "date", "value": "2026-07-25"},
            confidence=dict(MAILED_CONFIDENCE),
        ),
        _notice_fact(
            POLICY_ENTITY, "nc:Policy", "nc:governingState",
            {
                "kind": "code",
                "value": "US-NY",
                "codeSystem": "iso-3166-2",
                "codeSystemVersion": "2020",
            },
        ),
        _notice_fact(
            POLICY_ENTITY, "nc:Policy", "nc:policyExpirationDate",
            {"kind": "date", "value": "2026-09-01"},
        ),
    ]


def notice_mailed_fact(facts: list[dict]) -> dict:
    return next(f for f in facts if f["attribute"] == MAILED)


def adjudicate_notice_arc(facts: list[dict]) -> dict:
    return adjudicate(
        facts,
        load_notice_pack(),
        AS_OF_EFFECTIVE,
        AS_OF_KNOWLEDGE,
        QUESTION,
    )


def make_notice_correction(machine_fact: dict) -> dict:
    """The human confirmation that produced `review-0001`'s committed
    mailed-date fact."""
    who = dict(REVIEWER)
    ts = CORRECTION_TS
    doc = {
        "caseId": machine_fact["caseId"],
        "entity": dict(machine_fact["entity"]),
        "attribute": machine_fact["attribute"],
        "value": copy.deepcopy(machine_fact["value"]),
        "grounding": {
            "kind": "attestation",
            "actor": who["id"],
            "channel": "review-queue",
            "at": ts,
        },
        "assertion": {"kind": "human", "at": ts, "actor": who},
        "supersedes": machine_fact["id"],
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": dict(machine_fact["schemaRef"]),
    }
    return finish_fact(doc)


def run_committed_arc(golden_dir: Path, *, case_id: str | None = "review-0001") -> dict:
    """The exact arc behind `review-0001`, end to end through the queue."""
    store = FactStore.in_memory()
    store.init_schema()
    queue = ReviewQueue.in_memory()

    facts = build_notice_arc_facts()
    for f in facts:
        store.ingest(f)
    receipt = adjudicate_notice_arc(facts)
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert [a["reason"] for a in receipt["abstentions"]] == ["low_confidence"]

    (result,) = enqueue_receipt(queue, receipt, recorded_at=AS_OF_KNOWLEDGE)
    correction = make_notice_correction(notice_mailed_fact(facts))
    queue.resolve(result["itemId"], correction, store, CORRECTION_TS)

    return resolved_item_to_golden_case(
        queue,
        store,
        result["itemId"],
        pack_path=PACK_PATH,
        golden_dir=golden_dir,
        repo_root=EXAMPLES,
        case_id=case_id,
    )


def test_committed_case_regenerates_byte_identically(tmp_path):
    """`examples/golden/cases/review-0001` + its receipt ARE this arc's output.

    Reaching for the committed bytes before running the arc: with `examples/`
    deleted this raises `FileNotFoundError` on the pack rather than skipping or
    passing over an empty comparison — but that is only true until the day it
    is deleted along with everything else here, which is the point of the file
    living in this directory.
    """
    assert GOLDEN.is_dir(), f"no committed corpus at {GOLDEN}"

    run_committed_arc(tmp_path)
    produced = sorted(
        str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()
    )
    # The loop below is a byte comparison over whatever the arc wrote, so an
    # arc that wrote nothing would pass it in silence. Name the count.
    assert len(produced) == 6, f"expected 6 regenerated files, got {produced}"
    for rel in produced:
        committed = GOLDEN / rel
        assert committed.is_file(), f"missing committed file examples/golden/{rel}"
        assert (tmp_path / rel).read_bytes() == committed.read_bytes(), (
            f"examples/golden/{rel} differs from the review-arc regeneration"
        )


def test_the_regenerated_case_is_the_one_the_corpus_preserves(tmp_path):
    """A byte comparison is only as good as the file list it walks. Name what
    the arc must have written: the case, its two live facts, and the receipt —
    so a converter that silently stopped emitting one of them would be caught
    by more than a count."""
    run_committed_arc(tmp_path)
    written = {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()}
    assert "cases/review-0001/case.yaml" in written
    assert "receipts/review-0001.json" in written

    case = yaml.safe_load((tmp_path / "cases" / "review-0001" / "case.yaml").read_text())
    assert case["pack"] == PACK_PATH
    assert case["question"] == QUESTION

    receipt = json.loads((tmp_path / "receipts" / "review-0001.json").read_text())
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
