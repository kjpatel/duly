"""Pack-level abstention policy: low-confidence machine facts are excluded
from binding at decision time (spec/rule-ir.md, "Abstention policy")."""

import copy

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.ir import PackValidationError, validate_pack

from conftest import rehash_fact

AS_OF_EFFECTIVE = "2026-07-25"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"
QUESTION = "nc:noticeCompliant"

MAILED = "nc:noticeMailedDate"


def run(facts, pack):
    return adjudicate(facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, QUESTION)


def with_policy(pack, min_confidence=0.75, attributes=None):
    pack = copy.deepcopy(pack)
    policy = {"minConfidence": min_confidence}
    if attributes is not None:
        policy["attributes"] = attributes
    pack["abstentionPolicy"] = policy
    pack["pack"]["version"] = "2026.3.0"
    return pack


def with_confidence(facts, attribute, confidence):
    """The spec example facts with `attribute`'s fact rescored (or, when
    confidence is None, stripped of its confidence), rehashed to stay
    content-addressed."""
    out = []
    for fact in facts:
        if fact["attribute"] == attribute:
            fact = copy.deepcopy(fact)
            if confidence is None:
                fact.pop("confidence", None)
            else:
                fact["confidence"] = confidence
            fact = rehash_fact(fact)
        out.append(fact)
    return out


# The spec example case is non-compliant (38 < 45 days) whenever the mailed
# date binds; excluding the mailed date leaves the NC-DEF-00 presumption of
# compliance standing, with the exclusion surfaced as an abstention.


class TestThresholdBoundary:
    def test_below_threshold_excludes_and_falls_to_presumption(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.74, "method": "platt"})
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        assert [a["reason"] for a in receipt["abstentions"]] == ["low_confidence"]
        assert "NC-NR-01" not in {r["ruleId"] for r in receipt["rulesFired"]}

    def test_at_threshold_binds(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.75, "method": "platt"})
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []

    def test_above_threshold_binds(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.76, "method": "platt"})
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []


class TestAttributeOverride:
    def test_override_beats_default(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.85, "method": "platt"})
        # 0.85 clears the 0.75 default...
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["abstentions"] == []
        # ...but not a 0.9 per-attribute floor on the mailed date.
        pack = with_policy(ny_pack, min_confidence=0.75, attributes={MAILED: 0.9})
        receipt = run(facts, pack)
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        (entry,) = receipt["abstentions"]
        assert entry["threshold"]["minConfidence"] == 0.9
        assert entry["threshold"]["source"] == "attribute"

    def test_override_on_other_attribute_does_not_apply(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.8, "method": "platt"})
        pack = with_policy(
            ny_pack, min_confidence=0.75, attributes={"nc:policyExpirationDate": 0.99}
        )
        receipt = run(facts, pack)
        # The mailed date is governed by the 0.75 default, which 0.8 clears;
        # the expiration date's own 0.999 score clears its 0.99 override.
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []


class TestExemptions:
    def test_human_facts_are_never_confidence_filtered(self, spec_facts, ny_pack):
        facts = []
        for fact in spec_facts:
            if fact["attribute"] == MAILED:
                fact = copy.deepcopy(fact)
                fact["assertion"] = {
                    "kind": "human",
                    "at": "2026-07-26T09:00:00Z",
                    "actor": {"id": "reviewer:kp", "role": "compliance-review"},
                }
                fact["confidence"] = {"score": 0.1, "method": "raw"}
                fact = rehash_fact(fact)
            facts.append(fact)
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []

    def test_machine_fact_without_confidence_fails_closed(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, None)
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        (entry,) = receipt["abstentions"]
        assert entry["reason"] == "low_confidence"
        assert "confidence" not in entry
        assert entry["details"] == "machine assertion carries no confidence; policy fails closed"

    def test_machine_fact_without_confidence_binds_when_no_policy(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, None)
        receipt = run(facts, ny_pack)
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []


class TestNoPolicyUnchanged:
    def test_no_policy_pack_ignores_low_scores(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.01, "method": "raw"})
        receipt = run(facts, ny_pack)
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert receipt["abstentions"] == []

    def test_no_policy_receipt_is_byte_identical_to_pre_policy_kernel(
        self, spec_facts, ny_pack
    ):
        # The critical invariant: a pack without an abstentionPolicy produces
        # exactly the receipt it produced before the policy feature existed.
        # The pinned hash was computed by running the pre-policy kernel (the
        # M2 tree) over these same facts and fixture pack at this asOf pair.
        receipt = run(spec_facts, ny_pack)
        assert receipt["receiptSha256"] == (
            "eed6c2e754d9056ef1e44c28517518e52ecf9c69e55b000e43b72c5d2656788f"
        )


class TestReceiptEntry:
    def test_entry_shape(self, spec_facts, ny_pack):
        facts = with_confidence(spec_facts, MAILED, {"score": 0.85, "method": "platt"})
        pack = with_policy(ny_pack, min_confidence=0.75, attributes={MAILED: 0.9})
        receipt = run(facts, pack)
        mailed_fact = next(f for f in facts if f["attribute"] == MAILED)
        (entry,) = receipt["abstentions"]
        assert entry == {
            "entity": mailed_fact["entity"]["id"],
            "attribute": MAILED,
            "reason": "low_confidence",
            "facts": [mailed_fact["id"]],
            "confidence": {"score": 0.85, "method": "platt"},
            "threshold": {
                "minConfidence": 0.9,
                "source": "attribute",
                "pack": pack["pack"]["name"],
                "packVersion": "2026.3.0",
            },
        }

    def test_exclusion_precedes_conflict_detection(self, spec_facts, ny_pack):
        """A below-floor machine duplicate does not poison the attribute:
        the surviving fact binds and no conflict is recorded."""
        facts = list(spec_facts)
        mailed = next(f for f in facts if f["attribute"] == MAILED)
        dup = copy.deepcopy(mailed)
        dup["value"] = {"kind": "date", "value": "2026-06-01"}
        dup["confidence"] = {"score": 0.5, "method": "platt"}
        facts.append(rehash_fact(dup))
        receipt = run(facts, with_policy(ny_pack, min_confidence=0.75))
        # The confident 2026-07-25 mailing binds: 38 < 45, non-compliant.
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert [a["reason"] for a in receipt["abstentions"]] == ["low_confidence"]


class TestPolicyValidation:
    def test_policy_must_be_mapping(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = 0.75
        with pytest.raises(PackValidationError, match="must be a mapping"):
            validate_pack(pack)

    def test_min_confidence_required(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = {"attributes": {MAILED: 0.9}}
        with pytest.raises(PackValidationError, match="minConfidence"):
            validate_pack(pack)

    def test_floor_must_be_in_unit_interval(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = {"minConfidence": 1.5}
        with pytest.raises(PackValidationError, match=r"within \[0, 1\]"):
            validate_pack(pack)

    def test_boolean_floor_rejected(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = {"minConfidence": True}
        with pytest.raises(PackValidationError, match="must be a number"):
            validate_pack(pack)

    def test_unknown_keys_rejected(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = {"minConfidence": 0.75, "minConfidenceByRule": {}}
        with pytest.raises(PackValidationError, match="unknown key"):
            validate_pack(pack)

    def test_attribute_floor_validated(self, ny_pack):
        pack = copy.deepcopy(ny_pack)
        pack["abstentionPolicy"] = {"minConfidence": 0.75, "attributes": {MAILED: "0.9"}}
        with pytest.raises(PackValidationError, match="must be a number"):
            validate_pack(pack)
