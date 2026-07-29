"""Acceptance tests: the NY nonrenewal pack against the spec example facts
must reproduce spec/examples/receipt-ny-nonrenewal-notice.json."""

import copy
import json

from duly_kernel.api import adjudicate
from duly_kernel.receipt import content_hash

from conftest import rehash_fact

AS_OF_EFFECTIVE = "2026-07-25"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"
QUESTION = "nc:noticeCompliant"


def run(facts, pack):
    return adjudicate(facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, QUESTION)


class TestNyNonrenewalReceipt:
    def test_decision_block(self, spec_facts, ny_pack, expected_receipt):
        receipt = run(spec_facts, ny_pack)
        assert receipt["decision"] == expected_receipt["decision"]

    def test_rules_fired(self, spec_facts, ny_pack, expected_receipt):
        receipt = run(spec_facts, ny_pack)
        got = [
            (r["ruleId"], r["version"], r["priority"], r["defeated"])
            for r in receipt["rulesFired"]
        ]
        want = [
            (r["ruleId"], r["version"], r["priority"], r["defeated"])
            for r in expected_receipt["rulesFired"]
        ]
        assert got == want

    def test_derivation_structure(self, spec_facts, ny_pack, expected_receipt):
        receipt = run(spec_facts, ny_pack)

        def shape(node):
            if "factId" in node:
                return {"factId": node["factId"]}
            return {
                "conclusion": node["conclusion"],
                "rule": node.get("rule"),
                "premises": [shape(p) for p in node.get("premises", [])],
            }

        assert shape(receipt["derivation"]) == shape(expected_receipt["derivation"])

    def test_input_facts(self, spec_facts, ny_pack, expected_receipt):
        receipt = run(spec_facts, ny_pack)
        got = {(f["id"], f["contentHash"]) for f in receipt["inputFacts"]}
        want = {(f["id"], f["contentHash"]) for f in expected_receipt["inputFacts"]}
        assert got == want

    def test_no_abstentions(self, spec_facts, ny_pack):
        assert run(spec_facts, ny_pack)["abstentions"] == []

    def test_receipt_is_self_consistent(self, spec_facts, ny_pack):
        receipt = run(spec_facts, ny_pack)
        assert receipt["receiptSha256"] == content_hash(receipt, "receiptSha256")
        assert receipt["id"] == f"urn:duly:receipt:sha256:{receipt['receiptSha256']}"

    def test_determinism(self, spec_facts, ny_pack):
        a = run(spec_facts, ny_pack)
        b = run(list(reversed(spec_facts)), ny_pack)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


class TestDefeat:
    def test_early_mailing_leaves_default_standing(self, spec_facts, ny_pack):
        """Mail the notice 60+ days early: NC-NR-01's arithmetic no longer
        fails, so NC-DEF-00 survives and the notice is compliant."""
        facts = []
        for fact in spec_facts:
            if fact["attribute"] == "nc:noticeMailedDate":
                fact = copy.deepcopy(fact)
                fact["value"]["value"] = "2026-06-01"
                fact["effectiveFrom"] = "2026-06-01T00:00:00Z"
                fact = rehash_fact(fact)
            facts.append(fact)

        receipt = run(facts, ny_pack)
        fired = [r["ruleId"] for r in receipt["rulesFired"]]
        assert "NC-DEF-00" in fired
        assert "NC-NR-01" not in fired
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        assert receipt["derivation"]["rule"] == "NC-DEF-00"
        # Nothing defeats the default in this run.
        for r in receipt["rulesFired"]:
            assert r["defeated"] == []


class TestEffectiveDating:
    def test_rule_not_yet_effective_does_not_fire(self, spec_facts, ny_pack):
        """With NY-NR-45 effective only from 2026-08-01, an adjudication as
        of 2026-07-25 must not fire it (and NC-NR-01 loses its derived
        binding, so the default stands)."""
        pack = copy.deepcopy(ny_pack)
        for rule in pack["rules"]:
            if rule["id"] == "NY-NR-45":
                rule["effectiveFrom"] = "2026-08-01"

        receipt = run(spec_facts, pack)
        fired = [r["ruleId"] for r in receipt["rulesFired"]]
        assert "NY-NR-45" not in fired
        assert "NC-NR-01" not in fired
        assert fired == ["NC-DEF-00"]
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}

    def test_rule_expired_does_not_fire(self, spec_facts, ny_pack):
        """effectiveTo is exclusive: a rule whose window ended at the asOf
        point does not participate."""
        pack = copy.deepcopy(ny_pack)
        for rule in pack["rules"]:
            if rule["id"] == "NY-NR-45":
                rule["effectiveTo"] = "2026-07-25"

        receipt = run(spec_facts, pack)
        assert "NY-NR-45" not in [r["ruleId"] for r in receipt["rulesFired"]]
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}

    def test_fact_outside_effective_window_is_ignored(self, spec_facts, ny_pack):
        """A mailed-date fact whose effective window opens after asOf is not
        live, so NC-NR-01 is inapplicable."""
        facts = []
        for fact in spec_facts:
            if fact["attribute"] == "nc:noticeMailedDate":
                fact = copy.deepcopy(fact)
                fact["effectiveFrom"] = "2026-08-01T00:00:00Z"
                fact = rehash_fact(fact)
            facts.append(fact)

        receipt = run(facts, ny_pack)
        assert "NC-NR-01" not in [r["ruleId"] for r in receipt["rulesFired"]]
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}


class TestConflicts:
    def test_two_live_facts_same_attribute_abstain(self, spec_facts, ny_pack):
        """A second live governingState fact makes the attribute conflicted:
        rules needing it are inapplicable and the receipt records the
        abstention."""
        dupe = copy.deepcopy(next(f for f in spec_facts if f["attribute"] == "nc:governingState"))
        dupe["value"]["value"] = "US-NJ"
        dupe = rehash_fact(dupe)
        facts = spec_facts + [dupe]

        receipt = run(facts, ny_pack)
        fired = [r["ruleId"] for r in receipt["rulesFired"]]
        assert "NY-NR-45" not in fired
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        assert len(receipt["abstentions"]) == 1
        abstention = receipt["abstentions"][0]
        assert abstention["reason"] == "conflict"
        assert abstention["attribute"] == "nc:governingState"
        assert len(abstention["facts"]) == 2
