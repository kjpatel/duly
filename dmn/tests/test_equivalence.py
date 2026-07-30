"""The acceptance evidence: a DMN-compiled pack adjudicates identically to the
hand-written pack it recreates.

`dmn/examples/trid-fee-tolerance.dmn` is the three rules of
`rulepacks/trid-fee-tolerance-us-federal/pack.yaml` re-authored as two DMN
decision tables. These tests adjudicate the committed starter facts with both
packs and assert the receipts agree on everything that is a *decision*: the
value, which rules fired, in what order, what each defeated, and which facts
were consumed.

What deliberately does NOT match, and why it is not weakened here:

- `rulesFired[].priority`. Rule priorities are derived from the hit policy and
  row order (spec/dmn.md M2), not authored, so the compiled pack's integers
  are the compiler's and the hand-written pack's are its author's. Priorities
  are a tiebreak mechanism; the *outcome* of the tiebreak is asserted below.
- `rulePack.name` / `rulePack.version`. Two packs, two identities. Making them
  collide would be a lie about provenance, and the whole point of a compiled
  pack is that a receipt can say it came from one.

Byte-identical receipts are therefore impossible by construction, and saying
so is the finding. Everything short of those two fields is asserted exactly.
"""

from __future__ import annotations

import pytest
import yaml

from duly_dmn import compile_file
from duly_kernel.api import adjudicate
from dmntest_helpers import (
    TRID_COMPILED,
    TRID_DMN,
    TRID_EXPECTED,
    TRID_FACTS,
    TRID_HAND_WRITTEN,
    load_facts,
    load_yaml,
)

AS_OF = "2026-03-15"
QUESTIONS = ("trid:toleranceCureAmount", "trid:toleranceCategory")


@pytest.fixture(scope="module")
def facts():
    facts = load_facts(TRID_FACTS)
    assert facts, "no committed facts in starters/trid/facts"
    return facts


@pytest.fixture(scope="module")
def hand_pack():
    return load_yaml(TRID_HAND_WRITTEN)


@pytest.fixture(scope="module")
def dmn_pack():
    return compile_file(TRID_DMN)


def receipt(facts, pack, question, as_of=AS_OF):
    return adjudicate(
        facts=facts,
        pack=pack,
        as_of_effective=as_of,
        as_of_knowledge=f"{as_of}T23:59:59Z",
        decision_attribute=question,
    )


def fired(r):
    return [
        {
            "ruleId": entry["ruleId"],
            "defeated": sorted(entry.get("defeated") or []),
            "citation": entry.get("citation"),
            "effectiveFrom": entry.get("effectiveFrom"),
        }
        for entry in r["rulesFired"]
    ]


@pytest.mark.parametrize("question", QUESTIONS)
def test_same_decision_value(facts, hand_pack, dmn_pack, question):
    assert receipt(facts, dmn_pack, question)["decision"]["value"] == (
        receipt(facts, hand_pack, question)["decision"]["value"]
    )


@pytest.mark.parametrize("question", QUESTIONS)
def test_same_rules_fired_in_the_same_order_with_the_same_defeats(
    facts, hand_pack, dmn_pack, question
):
    """Not a set comparison: the ids, their order on the receipt, the citation
    each carries, and the defeat chains all have to line up."""
    assert fired(receipt(facts, dmn_pack, question)) == fired(
        receipt(facts, hand_pack, question)
    )


@pytest.mark.parametrize("question", QUESTIONS)
def test_same_input_facts_consumed(facts, hand_pack, dmn_pack, question):
    def consumed(r):
        return sorted((f["id"], f["contentHash"]) for f in r["inputFacts"])

    assert consumed(receipt(facts, dmn_pack, question)) == consumed(
        receipt(facts, hand_pack, question)
    )


@pytest.mark.parametrize("question", QUESTIONS)
def test_receipts_differ_only_in_pack_identity_and_priorities(
    facts, hand_pack, dmn_pack, question
):
    """State the inequality as precisely as the equality. If a future change
    makes the two receipts differ somewhere else, this fails."""
    hand = receipt(facts, hand_pack, question)
    dmn = receipt(facts, dmn_pack, question)

    def normalize(r):
        out = {k: v for k, v in r.items() if k not in ("id", "receiptSha256", "rulePack")}
        out["rulesFired"] = [
            {k: v for k, v in entry.items() if k != "priority"} for entry in r["rulesFired"]
        ]
        return out

    assert normalize(dmn) == normalize(hand)
    # The fields that must NOT match, asserted rather than merely described:
    # a different pack identity is a different receipt, by construction.
    assert hand["rulePack"] != dmn["rulePack"]
    assert hand["receiptSha256"] != dmn["receiptSha256"]


def test_the_packs_expected_yaml_cases_hold_for_the_compiled_pack(facts, dmn_pack):
    """The pack's own declared outcomes — the same cases CI runs against the
    hand-written pack in kernel/tests/test_rulepacks.py — run here against the
    compiled one."""
    spec = yaml.safe_load(TRID_EXPECTED.read_text(encoding="utf-8"))
    assert spec["cases"], "expected.yaml declares no cases"
    for case in spec["cases"]:
        r = receipt(facts, dmn_pack, case["question"], case["asOfEffective"])
        assert r["decision"]["value"] == dict(case["expectDecision"]), case["name"]
        assert {e["ruleId"] for e in r["rulesFired"]} == set(case["expectRulesFired"]), (
            case["name"]
        )
        defeated = {
            e["ruleId"]: sorted(e.get("defeated") or [])
            for e in r["rulesFired"]
            if e.get("defeated")
        }
        assert defeated == {
            k: sorted(v) for k, v in (case.get("expectDefeated") or {}).items()
        }, case["name"]


def test_before_the_effective_date_both_packs_refuse_identically(
    facts, hand_pack, dmn_pack
):
    """Equivalence has to hold off the happy path too. TRID took effect
    2015-10-03; on 2015-10-02 no rule is in force, and the kernel refuses to
    answer rather than falling back to a default. Both packs must refuse, with
    the same message — the compiled pack's effective dates are the authored
    ones, not the compiler's."""
    from duly_kernel.engine import AdjudicationError

    messages = []
    for pack in (hand_pack, dmn_pack):
        with pytest.raises(AdjudicationError) as excinfo:
            receipt(facts, pack, "trid:toleranceCureAmount", "2015-10-02")
        messages.append(str(excinfo.value))
    assert messages[0] == messages[1]


def test_the_committed_compilation_is_what_the_dmn_compiles_to(dmn_pack):
    """The .pack.yaml in dmn/examples/ is a build artifact under version
    control; this is what stops it drifting from its source."""
    assert load_yaml(TRID_COMPILED) == dmn_pack


def test_the_spec_demo_runs_and_reports_equivalence():
    """A feature is not shipped until it is demoable, so the demo is a test.
    spec/dmn_demo.py exits non-zero if the two packs disagree or if any
    refusal example stops refusing."""
    import subprocess
    import sys

    from dmntest_helpers import REPO

    proc = subprocess.run(
        [sys.executable, str(REPO / "spec" / "dmn_demo.py")],
        capture_output=True, text=True, cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.rstrip().endswith("EQUIVALENT")
    assert "NOT EQUIVALENT" not in proc.stdout
