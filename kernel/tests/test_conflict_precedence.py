"""Conflict-resolution policy: a lone human assertion outranks machine facts."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError

REPO = Path(__file__).resolve().parents[2]
PACK = yaml.safe_load((REPO / "kernel/tests/fixtures/ny-pack.yaml").read_text())


def _facts():
    facts = []
    for p in sorted((REPO / "spec/examples").glob("fact-*.json")):
        facts.append(json.loads(p.read_text()))
    return facts


def _human_variant(fact, new_value):
    """A human-asserted correction of `fact` carrying a different value."""
    dup = copy.deepcopy(fact)
    dup["id"] = fact["id"].replace("sha256:", "sha256:0f") [: len(fact["id"])]
    dup["value"] = new_value
    dup["assertion"] = {
        "kind": "human",
        "at": "2026-07-29T09:00:00Z",
        "actor": {"id": "reviewer:kp", "role": "compliance-review"},
    }
    dup["grounding"] = {
        "kind": "attestation",
        "actor": "reviewer:kp",
        "channel": "review-queue",
        "at": "2026-07-29T09:00:00Z",
    }
    dup.pop("confidence", None)
    return dup


def test_single_human_assertion_outranks_machine():
    facts = _facts()
    mailed = next(f for f in facts if f["attribute"] == "nc:noticeMailedDate")
    # Human review corrects the mailing date to 45+ days before expiration.
    facts.append(_human_variant(mailed, {"kind": "date", "value": "2026-07-01"}))

    receipt = adjudicate(
        facts=facts,
        pack=PACK,
        as_of_effective="2026-07-25",
        as_of_knowledge="2026-07-29T23:59:59Z",
        decision_attribute="nc:noticeCompliant",
    )
    # 2026-07-01 → 2026-09-01 is 62 days, over the 45-day minimum: compliant.
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert receipt["abstentions"] == []


def test_machine_machine_conflict_still_abstains():
    facts = _facts()
    mailed = next(f for f in facts if f["attribute"] == "nc:noticeMailedDate")
    dup = copy.deepcopy(mailed)
    dup["id"] = mailed["id"].replace("sha256:", "sha256:0f")[: len(mailed["id"])]
    dup["value"] = {"kind": "date", "value": "2026-07-01"}
    facts.append(dup)

    # Both assertions are machine-made: the attribute is unbindable, the
    # deficiency rule cannot fire, and the default presumption decides —
    # with the conflict surfaced as an abstention on the receipt.
    receipt = adjudicate(
        facts=facts,
        pack=PACK,
        as_of_effective="2026-07-25",
        as_of_knowledge="2026-07-29T23:59:59Z",
        decision_attribute="nc:noticeCompliant",
    )
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert len(receipt["abstentions"]) == 1
    entry = receipt["abstentions"][0]
    assert entry["reason"] == "conflict"
    assert entry["attribute"] == "nc:noticeMailedDate"
    assert len(entry["facts"]) == 2


def test_two_human_assertions_also_abstain():
    facts = _facts()
    mailed = next(f for f in facts if f["attribute"] == "nc:noticeMailedDate")
    h1 = _human_variant(mailed, {"kind": "date", "value": "2026-07-01"})
    h2 = _human_variant(mailed, {"kind": "date", "value": "2026-07-02"})
    h2["id"] = h2["id"].replace("sha256:0f", "sha256:0e")
    facts.extend([h1, h2])

    receipt = adjudicate(
        facts=facts,
        pack=PACK,
        as_of_effective="2026-07-25",
        as_of_knowledge="2026-07-29T23:59:59Z",
        decision_attribute="nc:noticeCompliant",
    )
    assert any(a["reason"] == "conflict" for a in receipt["abstentions"])
