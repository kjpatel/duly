"""Run every rule pack's expected.yaml through the kernel.

Each pack under rulepacks/ ships an expected.yaml declaring adjudication cases
against committed demo facts. This keeps pack content and kernel behavior
honest against each other on every test run.
"""

import json
from pathlib import Path

import pytest
import yaml

from duly_kernel.api import adjudicate

REPO = Path(__file__).resolve().parents[2]


def _load_cases():
    for expected in sorted(REPO.glob("rulepacks/*/expected.yaml")):
        pack_path = expected.parent / "pack.yaml"
        spec = yaml.safe_load(expected.read_text())
        for case in spec["cases"]:
            yield pytest.param(pack_path, case, id=case["name"])


def _load_facts(facts_dir: Path):
    facts = []
    for p in sorted(facts_dir.glob("*.json")):
        doc = json.loads(p.read_text())
        if "receiptSha256" in doc:
            continue
        facts.append(doc)
    return facts


@pytest.mark.parametrize("pack_path,case", _load_cases())
def test_pack_expectation(pack_path, case):
    pack = yaml.safe_load(pack_path.read_text())
    facts = _load_facts(REPO / case["factsFrom"])
    assert facts, f"no facts found in {case['factsFrom']}"

    receipt = adjudicate(
        facts=facts,
        pack=pack,
        as_of_effective=case["asOfEffective"],
        as_of_knowledge=case["asOfEffective"] + "T23:59:59Z",
        decision_attribute=case["question"],
    )

    expected_value = dict(case["expectDecision"])
    assert receipt["decision"]["value"] == expected_value

    fired = {r["ruleId"] for r in receipt["rulesFired"]}
    assert fired == set(case["expectRulesFired"])

    defeated = {
        r["ruleId"]: sorted(r.get("defeated") or [])
        for r in receipt["rulesFired"]
        if r.get("defeated")
    }
    expect_defeated = {
        k: sorted(v) for k, v in (case.get("expectDefeated") or {}).items()
    }
    assert defeated == expect_defeated
