"""The claims this example makes, checked.

Run with:

    uv run --with ortools pytest examples/closing-scheduler -q -m ortools

Every test here carries the `ortools` marker, including the handful that do
not strictly need a solver: the suite as a whole is an optional-dependency
suite (CLAUDE.md, "New packages"), so it runs in
`.github/workflows/optional-deps.yml` rather than in the main matrix, and
splitting it by marker would leave half of it running nowhere.

The load-bearing tests are `test_moving_the_rule_moves_the_plan` and
`test_moving_an_operational_input_moves_the_plan_the_other_way`. Between them
they are the mechanical version of this example's claim: the compliance
constraint lives in the pack and only in the pack, and the operational
constraint lives in the closing file and only there. A reviewer who believes
nothing else should read those two.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.ortools

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def _load_module():
    """Import `schedule.py` by path, under a name that cannot collide.

    The example is a script, not a package — an adopter copies the directory —
    so there is nothing to `import schedule` from, and `schedule` is a taken
    name on PyPI besides. Registering in `sys.modules` before executing is
    required: `@dataclass` resolves annotations through the module entry.
    """
    spec = importlib.util.spec_from_file_location("closing_scheduler", HERE / "schedule.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


S = _load_module()

pytest.importorskip("ortools", reason="the scheduler half of this example needs ortools")


# The committed demo output. A deliberate rule-pack change moves these dates;
# when it does, update them in the same commit and say so, exactly as a golden
# corpus regeneration is handled (golden/README.md).
EXPECTED_PLAN = {"sign": "2026-02-17", "fund": "2026-02-23", "record": "2026-02-24"}


@pytest.fixture(scope="module")
def planned():
    closing = S.load_closing(HERE / "closing-file.json")
    plan, windows, probe = S.plan_closing(closing)
    return closing, plan, windows, probe


def _dates(plan: dict) -> dict[str, str]:
    return {step["step"]: step["date"] for step in plan["plan"]}


# ---------------------------------------------------------------------------
# The plan itself
# ---------------------------------------------------------------------------

def test_the_plan_is_the_committed_demo_output(planned):
    _closing, plan, _windows, _probe = planned
    assert plan["status"] == "PLANNED"
    assert _dates(plan) == EXPECTED_PLAN
    assert plan["solver"]["status"] == "OPTIMAL"


def test_every_scheduled_date_was_independently_permitted_by_the_kernel(planned):
    """Re-adjudicate each chosen date from scratch and require the same verdict.

    This is the audit an auditor would do: take the plan, ignore the tables it
    was built from, and ask the kernel directly.
    """
    closing, plan, _windows, _probe = planned
    dates = _dates(plan)
    fresh = S.Probe(closing, S.REPO_ROOT)

    for gate in S.GATES:
        signing = dates["sign"] if gate.step == "fund" else None
        answer = fresh.ask(gate, dates[gate.step], signing_date=signing)
        if gate.question == "ron:ronPermitted":
            # Reported, not required: California has not authorized RON, and
            # the closing is in person, so the answer is false and harmless.
            assert not answer.permitted
            continue
        assert answer.permitted, f"{gate.question} refused {dates[gate.step]}"


def test_every_cited_receipt_resolves_and_hashes_to_its_own_id(planned):
    """A citation an auditor cannot resolve is decoration."""
    _closing, plan, _windows, probe = planned
    cited = []
    for step in plan["plan"]:
        cited.extend(c["receipt"] for c in step["compliance"]["permittedBy"])
        boundary = step["compliance"].get("boundary") or {}
        for key in ("permittedBy", "refusedTheDayBefore"):
            if boundary.get(key):
                cited.append(boundary[key]["receipt"])

    assert cited, "a plan with no receipt citations is the thing this example is against"
    for receipt_id in cited:
        assert receipt_id in probe.receipts
        receipt = probe.receipts[receipt_id]
        digest = S.content_hash(
            {k: v for k, v in receipt.items() if k != "receiptSha256"},
        )
        # `content_hash` drops `id` itself; drop the receipt's own hash field
        # the same way the kernel does, then check the id it claims.
        assert receipt["id"] == f"urn:duly:receipt:sha256:{receipt['receiptSha256']}"
        assert digest == receipt["receiptSha256"]


def test_the_funding_boundary_is_refuted_the_day_before(planned):
    """The plan's strongest claim: this day yes, the previous day no.

    Same shape as a what-if boundary verification (spec/whatif.md, W3), and
    for the same reason — an edge is worth what its refutation is worth.
    """
    _closing, plan, _windows, _probe = planned
    fund = next(s for s in plan["plan"] if s["step"] == "fund")
    boundary = fund["compliance"]["boundary"]
    assert boundary["earliestPermitted"] == "2026-02-21"
    assert boundary["permittedBy"]["answer"] == "true"
    assert boundary["refusedTheDayBefore"]["answer"] == "false"
    assert boundary["refusedTheDayBefore"]["asOfEffective"] == "2026-02-20"
    # The refusal names the rule that holds the money, which is the part an
    # auditor reads.
    assert "RESC-FUND-STAY" in boundary["refusedTheDayBefore"]["rulesFired"]


def test_the_saturday_is_the_whole_point(planned):
    """Compliance opens on a Saturday; the wire desk does not work Saturdays.

    Two different constraints, two different owners, and the plan says which
    is which. If these ever collapsed into one number the example would still
    produce a date and would have stopped demonstrating anything.
    """
    _closing, plan, _windows, _probe = planned
    fund = next(s for s in plan["plan"] if s["step"] == "fund")
    assert fund["floor"]["earliestAllowed"] == "2026-02-21"
    assert fund["floor"]["setBy"] == "compliance"
    assert fund["boundBy"] == "operational"
    assert any("Sat" in reason for reason in fund["operational"]["whyNotEarlier"])


# ---------------------------------------------------------------------------
# The separation, checked by moving each side and watching only it move
# ---------------------------------------------------------------------------

def test_moving_the_rule_moves_the_plan(planned):
    """Edit the TILA pack — three business days becomes five — and the plan moves.

    If `schedule.py` carried its own copy of the rescission wait, the plan
    would be unchanged here, and that is exactly the defect this example
    exists to prevent. The scheduler is not edited; only the pack is.
    """
    closing, _plan, _windows, _probe = planned
    pack_path = "rulepacks/tila-rescission-us-federal/pack.yaml"
    pack = yaml.safe_load((REPO_ROOT / pack_path).read_text(encoding="utf-8"))
    perturbed = copy.deepcopy(pack)
    rule = next(r for r in perturbed["rules"] if r["id"] == "RESC-DL-01")
    rule["then"]["value"]["expr"] = rule["then"]["value"]["expr"].replace(", 3, ", ", 5, ")

    probe = S.Probe(closing, S.REPO_ROOT)
    probe.packs[pack_path] = perturbed  # the pack the kernel sees; nothing else changes
    windows = S.probe_windows(probe)
    solution = S.solve(closing, windows)
    moved = S.build_plan(closing, windows, solution, probe)

    assert _dates(moved)["sign"] == EXPECTED_PLAN["sign"]
    assert _dates(moved)["fund"] > EXPECTED_PLAN["fund"]


def test_moving_an_operational_input_moves_the_plan_the_other_way(planned):
    """Open the wire desk on Saturdays and funding lands on the day compliance opens.

    The mirror image: the compliance floor is untouched (2026-02-21) and the
    plan snaps to it, because the only thing that was holding it was staffing.
    """
    closing, _plan, _windows, _probe = planned
    weekend_desk = copy.deepcopy(closing)
    weekend_desk["operational"]["funding"]["weekdays"] = list(S.WEEKDAY_NAMES)
    weekend_desk["operational"]["recording"]["weekdays"] = list(S.WEEKDAY_NAMES)

    plan, _windows, _probe2 = S.plan_closing(weekend_desk)
    dates = _dates(plan)
    assert dates["fund"] == "2026-02-21"
    fund = next(s for s in plan["plan"] if s["step"] == "fund")
    assert fund["boundBy"] == "compliance"
    assert fund["operational"]["whyNotEarlier"] == []


def test_the_solver_only_ever_sees_adjudicated_days(planned):
    """The chosen dates are members of the tables the probe built, not near them."""
    _closing, plan, windows, _probe = planned
    dates = _dates(plan)
    sign_index = windows.days.index(dates["sign"])
    fund_index = windows.days.index(dates["fund"])
    record_index = windows.days.index(dates["record"])
    assert sign_index in windows.sign_days
    assert record_index in windows.record_days
    assert (sign_index, fund_index) in windows.fund_pairs


# ---------------------------------------------------------------------------
# The facts the example mints
# ---------------------------------------------------------------------------

def test_every_minted_fact_passes_the_ontology_conformance_gate(planned):
    """The example does not get to invent vocabulary."""
    from duly_conformance.gate import check_fact
    from duly_conformance.registry import load_repo_registry

    closing, _plan, _windows, _probe = planned
    registry = load_repo_registry(REPO_ROOT / "ontologies")
    facts = S.facts_for(closing, "2026-02-17")
    assert len(facts) == len(closing["known"]) + 3
    for fact in facts:
        assert check_fact(fact, registry) == []


def test_a_minted_fact_is_content_addressed_and_a_new_date_is_a_new_fact(planned):
    closing, _plan, _windows, _probe = planned
    monday = S.facts_for(closing, "2026-02-16")
    tuesday = S.facts_for(closing, "2026-02-17")
    for fact in monday:
        assert fact["id"] == f"urn:duly:fact:sha256:{fact['contentHash']}"
        assert fact["contentHash"] == S.content_hash(fact)
    changed = {f["attribute"] for a, f in zip(monday, tuesday) if a["contentHash"] != f["contentHash"]}
    assert changed == set(closing["signingDateAttributes"]["attributes"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hash_seed", ["0", "1", "42"])
def test_the_plan_is_byte_identical_across_runs_and_hash_seeds(hash_seed):
    """CP-SAT randomises and parallelises by default; this is the pin.

    Separate subprocesses, because `PYTHONHASHSEED` is read at interpreter
    start — the same technique `whatif/tests/test_whatif.py` uses.
    """
    def run(seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, str(HERE / "schedule.py"), "--json"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            check=True,
        )
        return result.stdout

    baseline = run("0")
    assert run(hash_seed) == baseline
    assert json.loads(baseline)["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# The variant, and the honest degradation
# ---------------------------------------------------------------------------

def test_the_remote_notarization_variant_has_no_plan_and_cites_the_refusal():
    closing = S.load_closing(HERE / "closing-file-ron.json")
    plan, windows, _probe = S.plan_closing(closing)
    assert plan["status"] == "NO-FEASIBLE-PLAN"
    assert windows.sign_days == []
    blocker = next(b for b in plan["blocked"] if b["step"] == "sign")
    refusals = {a["question"]: a for a in blocker["adjudications"]}
    assert refusals["ron:notarizationCompliant"]["answer"] == "false"
    assert refusals["ron:notarizationCompliant"]["receipt"].startswith("urn:duly:receipt:sha256:")
    assert "RON-COMP-01" in refusals["ron:notarizationCompliant"]["rulesFired"]


def test_it_degrades_honestly_without_ortools(monkeypatch, capsys):
    monkeypatch.setattr(S, "cp_model", None)
    code = S.main(["--closing-file", str(HERE / "closing-file.json")])
    assert code == 2
    err = capsys.readouterr().err
    assert "uv run --with ortools" in err
    assert "Traceback" not in err


def test_the_windows_are_available_without_a_solver(monkeypatch, capsys):
    """The duly half of this example has no optional dependency at all."""
    monkeypatch.setattr(S, "cp_model", None)
    code = S.main(["--closing-file", str(HERE / "closing-file.json"), "--no-solve"])
    assert code == 0
    out = capsys.readouterr().out
    assert "adjudicated windows (no solver involved)" in out
    assert "sign 2026-02-10 -> funding opens 2026-02-14" in out


# ---------------------------------------------------------------------------
# Cross-check: two tools, one boundary
# ---------------------------------------------------------------------------

def test_the_funding_boundary_agrees_with_what_if(planned):
    """The probe swept for the boundary; `whatif` solves for it. They must agree.

    Two independent routes to the same date — a forward sweep of kernel runs,
    and a backward SMT solve whose every answer is kernel-verified — is worth
    one test and no dependency: `z3` is not installed by this example, and the
    test skips without it.
    """
    pytest.importorskip("z3", reason="what-if is behind the `prove` extra")
    from duly_conformance.registry import load_repo_registry
    from duly_whatif.query import AS_OF, SATISFIABLE, Query, solve

    closing, _plan, _windows, _probe = planned
    pack = yaml.safe_load(
        (REPO_ROOT / "rulepacks/tila-rescission-us-federal/pack.yaml").read_text(encoding="utf-8")
    )
    report = solve(
        Query(
            facts=S.facts_for(closing, EXPECTED_PLAN["sign"]),
            pack=pack,
            as_of_effective=EXPECTED_PLAN["sign"],
            as_of_knowledge=closing["plan"]["asOfKnowledge"],
            decision="resc:fundingPermitted",
            free=AS_OF,
            target={"kind": "boolean", "value": True},
            extremal="min",
        ),
        load_repo_registry(REPO_ROOT / "ontologies"),
    )
    assert report.verdict == SATISFIABLE
    assert report.extremal is not None
    assert report.extremal.value == "2026-02-21"
    assert report.boundary is not None and report.boundary.refuted
