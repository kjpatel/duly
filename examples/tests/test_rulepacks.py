"""Run every rule pack's expected.yaml through the kernel.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Each pack under `examples/rulepacks/` ships an `expected.yaml` declaring
adjudication cases against committed demo facts. This keeps pack content and
kernel behaviour honest against each other on every test run — and it is a
claim about *those packs*, which is why the whole file moved here from
`kernel/tests/` rather than being converted onto `fixtures/`. (The fixture
corpus makes the same declaration in its own `expected.yaml`; the toolkit-side
runner for it lives with the assurance suite.)

`factsFrom` is content-root relative (`starters/...`,
`rulepacks/<name>/fixtures/...`), so it resolves against `EXAMPLES` rather
than against the repository root — the same contract a deployment's own
content root honours.
"""

import pytest
import yaml

from duly_kernel.api import adjudicate

from exampletest_helpers import EXAMPLES, RULEPACKS, load_facts


def _load_cases():
    """Every declared case in every committed pack.

    Built as a list and asserted non-empty before it is parametrized over:
    parametrize is evaluated at *collection*, so an empty glob yields zero
    test cases and pytest reports only the count that remains, which reads
    exactly like success (CLAUDE.md).
    """
    params = []
    for expected in sorted(RULEPACKS.glob("*/expected.yaml")):
        pack_path = expected.parent / "pack.yaml"
        spec = yaml.safe_load(expected.read_text())
        for case in spec["cases"]:
            params.append(pytest.param(pack_path, case, id=case["name"]))
    assert params, f"no pack declared any expected case under {RULEPACKS}"
    return params


@pytest.mark.parametrize("pack_path,case", _load_cases())
def test_pack_expectation(pack_path, case):
    pack = yaml.safe_load(pack_path.read_text())
    facts = load_facts(EXAMPLES / case["factsFrom"])
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
