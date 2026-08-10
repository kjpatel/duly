"""Shared helpers for the review-queue tests.

Deliberately NOT a conftest.py (same reasoning as store/tests): these test
dirs have no __init__.py, so a second `conftest` module would shadow
kernel/tests/conftest.py when the suites run together.

Two arcs live here, and the split is the point.

**The fixture arc** (everything above the EXAMPLE CONTENT rule below) is the
one the queue's own suites run on. It is assembled from
[`fixtures/`](../../fixtures/README.md), the toolkit-owned corpus: the
committed case `fx-0003` carries a machine `fx:score` at confidence 0.62,
below the fixture pack's 0.80 floor, so the deciding rule cannot bind and the
default presumption stands; `fx-0004` is that case after review, where a human
correction supersedes the below-floor fact and the decision flips. That is
precisely a review arc, already committed as content — so `build_arc_facts`
does not invent facts, it *retargets the committed ones* (and returns them
unchanged when nothing is retargeted, which `test_the_arc_is_the_committed_
fixture_case` pins).

The queue, its lifecycle, its correction gate, the label export and the
golden-export machinery are all **toolkit**: none of them names a jurisdiction
or a pack. Pointed at `rulepacks/`, every one of those tests would keep passing
if the pack it reached for were deleted — it would simply stop being collected
or start erroring, which is not the same as failing (CLAUDE.md, "a test that
would still pass with its subject deleted is not a test").

**The notice arc** (the EXAMPLE CONTENT section at the bottom) survives for
exactly one test: it is the provenance of the committed golden case
``review-0001``, which `test_golden.py` regenerates and byte-compares. That
test's subject genuinely *is* the committed example, so it moves with
`examples/` rather than converting.

Every timestamp in both arcs is a fixed constant — no wall clock anywhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_store.store import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- the fixture arc (toolkit) ------------------------------------------------

FIXTURE_CORPUS = REPO_ROOT / "fixtures"

# The pack path as a *case* records it. Corpus-relative, which is what
# `duly_assurance.corpus.resolve_pack_path` and `resolved_item_to_golden_case`
# both resolve against the caller's root — and `fixtures/` sits at the repo
# root, where pytest runs, so it resolves for the CLI subprocess and the
# replay verifier alike.
FIXTURE_PACK_PATH = "fixtures/pack.yaml"

ONTOLOGY = "duly-fixture"
SCORE = "fx:score"
CATEGORY = "fx:category"
QUESTION = "fx:permitted"

# The committed fx-0003 -> fx-0004 arc, as fixed constants. Each one is read
# off the committed case rather than chosen here, so a rebuild of the fixture
# corpus that moved any of them fails loudly in
# `test_the_arc_is_the_committed_fixture_case` instead of drifting.
ARC_SOURCE_CASE = "fx-0003"
ARC_CASE_ID = "case:fixture:fx-0003"
ARC_WIDGET_ENTITY = "widget:fx-0003"
ARC_MACHINE_TS = "2026-03-01T00:00:00Z"          # extraction time
ARC_AS_OF_EFFECTIVE = "2026-06-01"               # the effective point
ARC_AS_OF_KNOWLEDGE = "2026-03-02T12:00:00Z"     # first adjudication
ARC_CORRECTION_TS = "2026-03-03T09:00:00Z"       # review resolution
ARC_SCORE_CONFIDENCE = {"score": 0.62, "method": "raw"}
ARC_REVIEWER = {"id": "reviewer:fx-demo", "role": "fixture-review"}


def load_fixture_pack() -> dict:
    return yaml.safe_load((FIXTURE_CORPUS / "pack.yaml").read_text(encoding="utf-8"))


def committed_fixture_facts(case_id: str = ARC_SOURCE_CASE) -> list[dict]:
    """The committed facts of a fixture case, in the corpus's own order."""
    facts_dir = FIXTURE_CORPUS / "cases" / case_id / "facts"
    paths = sorted(facts_dir.glob("*.json"))
    assert paths, f"no committed facts under {facts_dir}"
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def finish_fact(doc: dict) -> dict:
    """Stamp contentHash and id onto a fact body (spec D8)."""
    digest = content_hash(doc)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **doc}


def rehash(fact: dict) -> dict:
    """Copy of `fact` with contentHash and id recomputed after edits."""
    body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
    return finish_fact(json.loads(json.dumps(body)))


def build_arc_facts(
    case_id: str = ARC_CASE_ID,
    *,
    score_confidence: dict | None = None,
    entity: str = ARC_WIDGET_ENTITY,
) -> list[dict]:
    """The machine facts of the review arc, taken from committed fixture
    content rather than hand-assembled.

    Called with no arguments this returns `fixtures/cases/fx-0003/facts/*.json`
    byte-identically (same bodies, therefore same hashes and ids). Retargeting
    the case or entity, or overriding the score's confidence, rehashes — the
    tests that need several independent arcs in one queue vary exactly those.

    The score carries 0.62, below the fixture pack's 0.80 floor, unless
    overridden; the category carries 1.0, which clears the pack's stricter
    per-attribute floor of 0.95 for `fx:category`.
    """
    facts = []
    for base in committed_fixture_facts():
        doc = {k: v for k, v in base.items() if k not in ("id", "contentHash")}
        doc["caseId"] = case_id
        doc["entity"] = {**doc["entity"], "id": entity}
        if doc["attribute"] == SCORE and score_confidence is not None:
            doc["confidence"] = dict(score_confidence)
        facts.append(finish_fact(doc))
    return facts


def scored_fact(facts: list[dict]) -> dict:
    """The below-floor `fx:score` fact — the one the arc abstains over."""
    return next(f for f in facts if f["attribute"] == SCORE)


def rival_fact(machine_fact: dict, *, value: dict, ts: str, confidence: dict) -> dict:
    """A second *machine* fact on the same (entity, attribute), derived from
    the first. Two live machine facts on one attribute is a conflict, which is
    the only shape the queue's C6 carve-out has to be tested against."""
    doc = {k: v for k, v in machine_fact.items() if k not in ("id", "contentHash")}
    doc = json.loads(json.dumps(doc))
    doc["value"] = copy.deepcopy(value)
    doc["confidence"] = dict(confidence)
    doc["recordedAt"] = ts
    doc["grounding"] = {**doc["grounding"], "at": ts}
    doc["assertion"] = {**doc["assertion"], "at": ts}
    return finish_fact(doc)


def adjudicate_arc(facts: list[dict], pack: dict | None = None) -> dict:
    """First adjudication of the arc: the below-floor score abstains, the
    default presumption stands, and the receipt carries one low_confidence
    abstention entry."""
    return adjudicate(
        facts,
        pack if pack is not None else load_fixture_pack(),
        ARC_AS_OF_EFFECTIVE,
        ARC_AS_OF_KNOWLEDGE,
        QUESTION,
    )


def make_correction(
    machine_fact: dict,
    *,
    value: dict | None = None,
    supersedes: bool = True,
    ts: str = ARC_CORRECTION_TS,
    actor: dict | None = None,
) -> dict:
    """A human-asserted correction for `machine_fact` (spec D3/D9):
    assertion.kind human with actor id + role, attestation grounding.
    Default value confirms the machine's read; pass `value` to contradict.

    Built to match `fixtures/cases/fx-0004/facts/fx-score-corrected.json`,
    which is this shape frozen as content.
    """
    who = actor if actor is not None else dict(ARC_REVIEWER)
    doc = {
        "caseId": machine_fact["caseId"],
        "entity": dict(machine_fact["entity"]),
        "attribute": machine_fact["attribute"],
        "value": value if value is not None else copy.deepcopy(machine_fact["value"]),
        "grounding": {
            "kind": "attestation",
            "actor": who["id"],
            "channel": "fixture-review",
            "at": ts,
        },
        "assertion": {"kind": "human", "at": ts, "actor": who},
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": dict(machine_fact["schemaRef"]),
    }
    if supersedes:
        doc["supersedes"] = machine_fact["id"]
    return finish_fact(doc)


# --- EXAMPLE CONTENT (moves with examples/) -----------------------------------
#
# Everything below exists for ONE test: the provenance lock on the committed
# golden case `review-0001` (test_golden.py). Its subject is that committed
# case, not the toolkit, so it stays pointed at the example content and moves
# with it. Nothing else in this suite may import from here — if a second
# caller appears, it is almost certainly a toolkit test that should be using
# the fixture arc above.
#
# `review-0001` is preserved forever (the corpus generator skips `review-*`,
# golden/README.md), so these constants are pinned by bytes that cannot be
# regenerated away.

NOTICE_GOLDEN_DIR = REPO_ROOT / "examples" / "golden"

# As `examples/golden/cases/review-0001/case.yaml` records it, and therefore
# what must be written back for the regeneration to be byte-identical: the path
# is relative to the *corpus root's parent* (`examples/`), which is what
# `duly_assurance.corpus.resolve_pack_path` resolves it against. The move under
# `examples/` deliberately left these references alone for that reason.
NOTICE_PACK_PATH = "rulepacks/termination-notice-us-states/pack.yaml"
NOTICE_REPO_ROOT = REPO_ROOT / "examples"

NOTICE_ONTOLOGY = "duly-starter-notice"
MAILED = "nc:noticeMailedDate"
NOTICE_QUESTION = "nc:noticeCompliant"

NOTICE_CASE_ID = "case:review:0001"
NOTICE_ENTITY = "notice:review-0001"
NOTICE_POLICY_ENTITY = "policy:review-0001"
NOTICE_MACHINE_TS = "2026-07-25T12:00:00Z"          # extraction time
NOTICE_AS_OF_EFFECTIVE = "2026-07-25"               # the mailed date
NOTICE_AS_OF_KNOWLEDGE = "2026-07-27T12:00:00Z"     # first adjudication
NOTICE_CORRECTION_TS = "2026-07-28T09:00:00Z"       # review resolution
NOTICE_MAILED_CONFIDENCE = {"score": 0.62, "method": "platt"}
NOTICE_REVIEWER = {"id": "reviewer:rq-demo", "role": "compliance-review"}


def load_notice_pack() -> dict:
    """EXAMPLE CONTENT (moves with examples/)."""
    return yaml.safe_load(
        (NOTICE_REPO_ROOT / NOTICE_PACK_PATH).read_text(encoding="utf-8")
    )


def _notice_fact(
    entity_id: str, entity_type: str, attribute: str, value: dict,
    *, confidence: dict | None = None,
) -> dict:
    """EXAMPLE CONTENT (moves with examples/). A schema-valid machine-asserted
    GroundedFact (attestation grounding — this fixture, like the golden
    generator, does not fake document spans)."""
    ts = NOTICE_MACHINE_TS
    doc = {
        "caseId": NOTICE_CASE_ID,
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
        "schemaRef": {"ontology": NOTICE_ONTOLOGY, "version": "0.1.0"},
    }
    return finish_fact(doc)


def build_notice_arc_facts() -> list[dict]:
    """EXAMPLE CONTENT (moves with examples/). The four machine facts behind
    `review-0001`. The mailed date carries a below-floor confidence (0.62 <
    the notice pack's 0.9 attribute floor); expiration 2026-09-01 minus mailed
    2026-07-25 gives 38 days of notice against NY's 45-day minimum."""
    return [
        _notice_fact(
            NOTICE_ENTITY, "nc:TerminationNotice", "nc:noticeType",
            {
                "kind": "code",
                "value": "Nonrenewal",
                "codeSystem": "duly-starter-notice/notice-types",
                "codeSystemVersion": "0.1.0",
            },
        ),
        _notice_fact(
            NOTICE_ENTITY, "nc:TerminationNotice", MAILED,
            {"kind": "date", "value": "2026-07-25"},
            confidence=dict(NOTICE_MAILED_CONFIDENCE),
        ),
        _notice_fact(
            NOTICE_POLICY_ENTITY, "nc:Policy", "nc:governingState",
            {
                "kind": "code",
                "value": "US-NY",
                "codeSystem": "iso-3166-2",
                "codeSystemVersion": "2020",
            },
        ),
        _notice_fact(
            NOTICE_POLICY_ENTITY, "nc:Policy", "nc:policyExpirationDate",
            {"kind": "date", "value": "2026-09-01"},
        ),
    ]


def notice_mailed_fact(facts: list[dict]) -> dict:
    """EXAMPLE CONTENT (moves with examples/)."""
    return next(f for f in facts if f["attribute"] == MAILED)


def adjudicate_notice_arc(facts: list[dict]) -> dict:
    """EXAMPLE CONTENT (moves with examples/)."""
    return adjudicate(
        facts,
        load_notice_pack(),
        NOTICE_AS_OF_EFFECTIVE,
        NOTICE_AS_OF_KNOWLEDGE,
        NOTICE_QUESTION,
    )


def make_notice_correction(machine_fact: dict) -> dict:
    """EXAMPLE CONTENT (moves with examples/). The human confirmation that
    produced `review-0001`'s committed mailed-date fact."""
    who = dict(NOTICE_REVIEWER)
    ts = NOTICE_CORRECTION_TS
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
