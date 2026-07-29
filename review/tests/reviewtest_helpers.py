"""Shared helpers for the review-queue tests.

Deliberately NOT a conftest.py (same reasoning as store/tests): these test
dirs have no __init__.py, so a second `conftest` module would shadow
kernel/tests/conftest.py when the suites run together.

The "review arc" built here is also the provenance of the committed golden
case ``review-0001`` (see test_golden.py, which regenerates it and
byte-compares): a machine-asserted mailed date abstains under the notice
pack's 0.9 per-attribute floor, a human confirms the date (superseding the
machine fact), and the decision flips from the compliance presumption to
non-compliant. Every timestamp is a fixed constant — no wall clock anywhere.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_store.store import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTICE_PACK_PATH = "rulepacks/termination-notice-us-states/pack.yaml"

ONTOLOGY = "duly-starter-notice"
MAILED = "nc:noticeMailedDate"
QUESTION = "nc:noticeCompliant"

# The committed review-0001 arc, as fixed constants.
ARC_CASE_ID = "case:review:0001"
ARC_NOTICE_ENTITY = "notice:review-0001"
ARC_POLICY_ENTITY = "policy:review-0001"
ARC_MACHINE_TS = "2026-07-25T12:00:00Z"          # extraction time
ARC_AS_OF_EFFECTIVE = "2026-07-25"               # the mailed date
ARC_AS_OF_KNOWLEDGE = "2026-07-27T12:00:00Z"     # first adjudication
ARC_CORRECTION_TS = "2026-07-28T09:00:00Z"       # review resolution
ARC_MAILED_CONFIDENCE = {"score": 0.62, "method": "platt"}
ARC_REVIEWER = {"id": "reviewer:rq-demo", "role": "compliance-review"}


def load_notice_pack() -> dict:
    return yaml.safe_load((REPO_ROOT / NOTICE_PACK_PATH).read_text(encoding="utf-8"))


def finish_fact(doc: dict) -> dict:
    """Stamp contentHash and id onto a fact body (spec D8)."""
    digest = content_hash(doc)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **doc}


def make_fact(
    case_id: str,
    entity_id: str,
    entity_type: str,
    attribute: str,
    value: dict,
    ts: str,
    *,
    confidence: dict | None = None,
) -> dict:
    """A schema-valid machine-asserted GroundedFact (attestation grounding —
    this fixture, like the golden generator, does not fake document spans)."""
    doc = {
        "caseId": case_id,
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


def build_arc_facts(
    case_id: str = ARC_CASE_ID,
    *,
    mailed_confidence: dict | None = None,
    notice_entity: str = ARC_NOTICE_ENTITY,
    policy_entity: str = ARC_POLICY_ENTITY,
) -> list[dict]:
    """The four machine facts of the review arc. The mailed date carries a
    below-floor confidence (0.62 < the pack's 0.9 attribute floor) unless
    overridden; expiration 2026-09-01 minus mailed 2026-07-25 gives 38 days
    of notice against NY's 45-day minimum."""
    conf = mailed_confidence if mailed_confidence is not None else dict(ARC_MAILED_CONFIDENCE)
    ts = ARC_MACHINE_TS
    return [
        make_fact(
            case_id, notice_entity, "nc:TerminationNotice", "nc:noticeType",
            {
                "kind": "code",
                "value": "Nonrenewal",
                "codeSystem": "duly-starter-notice/notice-types",
                "codeSystemVersion": "0.1.0",
            },
            ts,
        ),
        make_fact(
            case_id, notice_entity, "nc:TerminationNotice", MAILED,
            {"kind": "date", "value": "2026-07-25"},
            ts, confidence=conf,
        ),
        make_fact(
            case_id, policy_entity, "nc:Policy", "nc:governingState",
            {
                "kind": "code",
                "value": "US-NY",
                "codeSystem": "iso-3166-2",
                "codeSystemVersion": "2020",
            },
            ts,
        ),
        make_fact(
            case_id, policy_entity, "nc:Policy", "nc:policyExpirationDate",
            {"kind": "date", "value": "2026-09-01"},
            ts,
        ),
    ]


def mailed_fact(facts: list[dict]) -> dict:
    return next(f for f in facts if f["attribute"] == MAILED)


def adjudicate_arc(facts: list[dict], pack: dict | None = None) -> dict:
    """First adjudication of the arc: the below-floor mailed date abstains,
    the compliance presumption stands, and the receipt carries one
    low_confidence abstention entry."""
    return adjudicate(
        facts,
        pack if pack is not None else load_notice_pack(),
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
    Default value confirms the machine's read; pass `value` to contradict."""
    who = actor if actor is not None else dict(ARC_REVIEWER)
    doc = {
        "caseId": machine_fact["caseId"],
        "entity": dict(machine_fact["entity"]),
        "attribute": machine_fact["attribute"],
        "value": value if value is not None else copy.deepcopy(machine_fact["value"]),
        "grounding": {
            "kind": "attestation",
            "actor": who["id"],
            "channel": "review-queue",
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


def rehash(fact: dict) -> dict:
    """Copy of `fact` with contentHash and id recomputed after edits."""
    body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
    return finish_fact(json.loads(json.dumps(body)))
