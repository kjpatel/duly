"""The teaching packs' boundary answers, found backwards by the what-if solver.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as

    uv run --with z3-solver pytest examples/tests -q -m z3

Extracted from `whatif/tests/test_whatif.py` and `test_whatif_cli.py`, which
keep the *solver's* contract — flip, the contradiction guard, finite-domain
completeness, the named refusals, determinism — asserted on `fixtures/`. What
moved here has an example pack for its subject rather than the solver: the
45-day notice date, the TRID cure boundary, the TILA business-day arithmetic.
Those numbers are README claims about the shipped packs, so they belong with
the packs that make them true.

The boundary dates and amounts below are computed BY HAND in the docstrings
and asserted as literals. That is the point of them: a test that recomputed
the answer the way the tool does would pass just as happily against a broken
tool.

Everything needing the solver carries `@pytest.mark.z3` and skips when
z3-solver is not importable — the posture `prove`, `docling` and `linkml` all
take, and the markers resolve from the repository's `pyproject.toml` exactly
as they did before the move.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys

import pytest

from exampletest_helpers import (
    EXAMPLES,
    GOLDEN_CASES,
    ONTOLOGIES,
    REPO_ROOT,
    load_yaml,
    needs_z3,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TRUE = {"kind": "boolean", "value": True}


def money(amount: str, currency: str = "USD") -> dict:
    return {"kind": "money", "amount": amount, "currency": currency}


def repo_registry():
    """The example content's ontology registry (`examples/ontologies`)."""
    from duly_conformance.registry import load_repo_registry

    return load_repo_registry(ONTOLOGIES)


def load_case(case_id: str):
    """(case dict, facts, pack) for a committed golden case.

    Cases come from the committed corpus rather than from hand-built dicts,
    deliberately: a boundary asserted here is pinned against a case nothing may
    silently change. A case's `pack:` is content-root relative, so it resolves
    against `examples/` — the same contract a deployment's own root honours.
    """
    directory = GOLDEN_CASES / case_id
    case = load_yaml(directory / "case.yaml")
    facts = [
        json.loads(p.read_text()) for p in sorted((directory / "facts").glob("*.json"))
    ]
    pack = load_yaml(EXAMPLES / str(case["pack"]))
    return case, facts, pack


def query_for(case_id: str, free: str, **overrides):
    """A `Query` over a golden case, with the case supplying every default."""
    from duly_whatif.query import Query

    case, facts, pack = load_case(case_id)
    kwargs = dict(
        facts=facts,
        pack=pack,
        as_of_effective=str(case["asOfEffective"]),
        as_of_knowledge=str(case["asOfKnowledge"]),
        decision=str(case["question"]),
        free=free,
    )
    kwargs.update(overrides)
    return Query(**kwargs)


def solve_for(case_id: str, free: str, **overrides):
    from duly_whatif.query import solve

    return solve(query_for(case_id, free, **overrides), repo_registry())


def _cli_output(args: list[str], seed: str) -> str:
    run = subprocess.run(
        [sys.executable, "-m", "duly_whatif", *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "a satisfiable query prints its report to stdout"
    return run.stdout


@needs_z3
@pytest.mark.z3
def test_the_notice_packs_45_day_boundary():
    """The latest mailing date that keeps notice-ny-0001 compliant.

    By hand, from the committed case and pack:

      * the policy expires 2026-06-08 and the notice is a NY Nonrenewal;
      * evaluated at 2026-05-27, NY-NR-45 is in force (effectiveFrom
        2026-01-01), so the minimum is 45 days — not the 30 of the
        superseded NY-NR-45-LEGACY;
      * NC-NR-01 finds the notice deficient when
        `days_between(mailed, expiration) < 45`, so compliance needs
        `expiration - mailed >= 45`;
      * 2026-06-08 minus 45 days: 8 days back to 2026-05-31, 31 more to
        2026-04-30, 6 more to **2026-04-24**.

    One day later is 44 days and fails. Both halves are the kernel's own
    verdict, not the solver's.
    """
    report = solve_for("notice-ny-0001", "nc:noticeMailedDate", target=TRUE)

    assert report.verdict == "SATISFIABLE"
    assert report.extremal.value == "2026-04-24"
    assert report.extremal.decision == "true"
    assert report.extremal_direction == "max"
    assert report.boundary.value == "2026-04-25"
    assert report.boundary.refuted
    assert report.boundary.decision == "false"

    # And the arithmetic itself, so the constant is not merely self-consistent.
    expiration = _dt.date(2026, 6, 8)
    assert _dt.date.fromisoformat(report.extremal.value) == expiration - _dt.timedelta(days=45)


@needs_z3
@pytest.mark.z3
def test_the_trid_maximum_fee_that_owes_no_cure():
    """The largest closing amount on trid-0001 that owes no tolerance cure.

    A transfer tax is a zero-tolerance charge (TRID-CAT-02), and TRID-ZT-01
    computes a cure only when `actual > disclosed`. The case discloses
    2984.02 at baseline, so the largest actual amount owing nothing is
    **2984.02** exactly — the disclosed figure itself — and one cent more
    owes exactly that cent.

    This is the case for the decimal grid: over the reals the answer would be
    an unattainable infimum, and no fact could ever carry it.
    """
    report = solve_for(
        "trid-0001", "trid:actualAmountAtClosing", target=money("0.00")
    )

    assert report.verdict == "SATISFIABLE"
    assert report.extremal.value == "2984.02"
    assert report.extremal.decision == "0.00 USD"
    assert report.boundary.value == "2984.03"
    assert report.boundary.refuted
    assert report.boundary.decision == "0.01 USD"

    _, facts, _ = load_case("trid-0001")
    disclosed = next(
        f for f in facts if f["attribute"] == "trid:disclosedAmountAtBaseline"
    )
    assert report.extremal.value == disclosed["value"]["amount"]


@needs_z3
@pytest.mark.z3
def test_the_earliest_date_tila_permits_funding():
    """The flagship TILA answer, and the reason the calendar had to be exact.

    resc-0001 consummates, delivers the notice and delivers the material
    disclosures all on 2026-02-12. RESC-DL-01 puts the deadline three
    *precise* business days later — 12 CFR 1026.2(a)(6), where Saturdays
    count and Sundays and 5 U.S.C. 6103(a) holidays do not:

        Fri 2026-02-13  business day 1
        Sat 2026-02-14  business day 2   <- a weekday-only calendar skips this
        Sun 2026-02-15  not a business day
        Mon 2026-02-16  Washington's Birthday, not a business day
        Tue 2026-02-17  business day 3   -> the deadline

    RESC-FUND-EXP permits disbursement only once `today > deadline`, so the
    earliest permitted date is **2026-02-18**, and the deadline day itself is
    still inside the hold.

    An industry-standard weekday-only calendar would have made Saturday the
    14th a non-day and answered 2026-02-19 instead. The answer is one day
    off in the direction that funds a loan the borrower can still rescind.
    """
    report = solve_for("resc-0001", "asOf", target=TRUE, extremal="min")

    assert report.verdict == "SATISFIABLE"
    assert report.extremal.value == "2026-02-18"
    assert report.extremal.decision == "true"
    assert report.extremal_direction == "min"
    assert report.boundary.value == "2026-02-17"
    assert report.boundary.refuted
    assert report.boundary.decision == "false"


@needs_z3
@pytest.mark.z3
def test_the_latest_consummation_date_that_still_funds_on_schedule():
    """The same TILA arithmetic run backwards through the calendar.

    Funding is scheduled for 2026-02-20. Consummating on 2026-02-16 puts the
    deadline at 2026-02-19 (Tue 17, Wed 18, Thu 19 — no Sunday or holiday in
    the way), which clears. Consummating one day later pushes the deadline to
    2026-02-20 itself, and the deadline day is inside the hold.
    """
    report = solve_for(
        "resc-0001", "resc:consummationDate", target=TRUE,
        as_of_effective="2026-02-20",
    )

    assert report.verdict == "SATISFIABLE"
    assert report.extremal.value == "2026-02-16"
    assert report.boundary.value == "2026-02-17"
    assert report.boundary.refuted


@needs_z3
@pytest.mark.z3
def test_a_flip_finds_the_nearest_change_not_the_most_extreme_one():
    """notice-ny-0001 is decided non-compliant. What would reverse it?

    The notice went out 2026-05-27, twelve days before expiry. The nearest
    mailing date that flips the decision is the boundary itself, 2026-04-24 —
    33 days earlier — and the day after it does not flip. The *behaviour* is
    asserted on the fixtures; what this pins is the notice pack's own number.
    """
    report = solve_for("notice-ny-0001", "nc:noticeMailedDate", flip=True)

    assert report.current == "false"
    assert report.verdict == "SATISFIABLE"
    assert report.extremal_direction == "nearest"
    assert report.extremal.value == "2026-04-24"
    assert report.extremal.decision == "true"
    # The step back toward today's value must NOT flip, or it was not nearest.
    assert report.boundary.value == "2026-04-25"
    assert report.boundary.refuted


@needs_z3
@pytest.mark.z3
def test_an_unsatisfiable_answer_is_reported_as_the_weaker_claim():
    """No consummation date lets resc-0001 fund on the day it consummates.

    The deadline is at least three business days after consummation and
    consummation is one of the triggers, so `today > deadline` is unreachable
    at `today == 2026-02-12` whatever the consummation date. True — but not
    kernel-verified, because there is no single point to hand the kernel, and
    the report has to say so.
    """
    from duly_whatif.render import UNSAT_CAVEAT, render

    report = solve_for("resc-0001", "resc:consummationDate", target=TRUE)

    assert report.verdict == "UNSATISFIABLE"
    assert report.complete is False
    assert report.extremal is None
    assert report.exit_code == 1
    text = render(report)
    assert UNSAT_CAVEAT.splitlines()[0] in text


@needs_z3
@pytest.mark.z3
def test_a_finite_domain_makes_even_the_negative_answer_verified():
    """The boolean-input half of the finite-domain claim, which the fixture
    pack cannot carry: it has no boolean *input*, only a boolean decision.

    A boolean or code input has finitely many values, so "no value works" can
    be checked pointwise by checking every point — and it is. The report says
    `complete`, and the renderer drops the caveat, because here it would be
    false modesty.
    """
    from duly_whatif.render import UNSAT_CAVEAT, render

    # The triggers all fall on 2026-02-12, so the only deadline this case can
    # reach is 2026-02-17 (or none at all, when rescission does not apply).
    # No setting of the dwelling flag produces 2026-02-20.
    report = solve_for(
        "resc-0001", "resc:securedByPrincipalDwelling",
        decision="resc:rescissionDeadline",
        target={"kind": "date", "value": "2026-02-20"},
    )
    assert report.free_kind == "boolean"
    assert report.verdict == "UNSATISFIABLE"
    assert report.complete is True
    assert "verified rather than inferred" in report.reason
    # The caveat would be false modesty here: both values were actually run.
    assert UNSAT_CAVEAT.splitlines()[0] not in render(report)


@needs_z3
@pytest.mark.z3
def test_a_finite_domain_answer_names_the_satisfying_values():
    """The dwelling flag is what makes rescission apply at all, so exactly one
    of its two values reaches the pack's computed deadline."""
    report = solve_for(
        "resc-0001", "resc:securedByPrincipalDwelling",
        decision="resc:rescissionDeadline",
        target={"kind": "date", "value": "2026-02-17"},
    )
    assert report.verdict == "SATISFIABLE"
    assert report.complete is True
    assert [a.value for a in report.answers] == ["true"]
    assert report.answers[0].decision == "2026-02-17"


@needs_z3
@pytest.mark.z3
def test_the_notice_packs_open_code_set_surfaces_a_coverage_hole():
    """Freeing the governing state finds the notice pack's coverage hole.

    NY needs 45 days, FL 120, CA 75; the notice went out 12 days before
    expiry, so no *named* state is compliant. An unnamed one is: nothing
    concludes a minimum, so NC-NR-01 cannot bind its derived input and the
    default presumption stands. That is a real hole in the pack, and freeing
    a code input surfaces it without being told to look.

    It is also, for now, the only exercise of the *open* code domain's
    residual region — `fx:category`'s enum is closed, so the fixture twin
    (`test_every_member_of_a_finite_domain_is_run_through_the_kernel`) covers
    the enumerated members and not `OTHER_REPRESENTATIVE`.
    """
    report = solve_for("notice-ny-0001", "nc:governingState", target=TRUE)

    assert report.verdict == "SATISFIABLE"
    assert report.complete is True
    assert len(report.answers) == 1
    answer = report.answers[0]
    assert answer.representative is not None
    assert "US-NY" in answer.value and "other than" in answer.value
    assert answer.decision == "true"


@needs_z3
@pytest.mark.z3
@pytest.mark.parametrize(
    "case_id,free,target,extra",
    [
        ("notice-ny-0001", "nc:noticeMailedDate", "true", []),
        ("trid-0001", "trid:actualAmountAtClosing", "0.00", []),
        ("resc-0001", "asOf", "true", ["--extremal", "min"]),
        ("notice-ny-0001", "nc:governingState", "true", []),
    ],
)
def test_the_example_answers_are_byte_identical_across_hash_seeds(
    case_id, free, target, extra
):
    """The same determinism claim the fixture cases carry, over the four
    example queries the README quotes — a named list rather than a glob, so
    deleting the corpus errors here rather than collecting nothing."""
    args = [
        "--ontologies", "examples/ontologies",
        "--case", f"examples/golden/cases/{case_id}",
        "--free", free, "--target", target, "--json", *extra,
    ]
    outputs = [_cli_output(args, seed) for seed in ("0", "1", "12345")]
    assert outputs[0] == outputs[1] == outputs[2]


@needs_z3
@pytest.mark.z3
def test_without_a_registry_the_report_says_so():
    """The A9 defect proper (`whatif/tests/test_whatif_cli.py`'s roots block).

    Absence of an ontology registry is legal — kinds are inferred from use —
    but the answer is weaker in a way nothing else in the output reveals, so
    silence would hand back the weaker answer looking like the stronger.

    It is here rather than with the CLI's other root tests because reaching
    this note requires a pack whose kinds are *all* inferable from use, and
    the fixture pack is not one: its widest guard compares two bound
    variables, so `fx:score` has no inferable kind. Until the fixtures grow an
    inferable pack, the notice pack is the only thing that can pose the
    question — which makes this example content.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "duly_whatif",
            "--case", "examples/golden/cases/notice-ny-0001",
            "--free", "nc:noticeMailedDate", "--target", "true", "--json",
        ],
        capture_output=True, text=True, cwd=REPO_ROOT, env=dict(os.environ),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    notes = json.loads(result.stdout)["notes"]
    assert any("no ontology registry supplied" in n for n in notes)


@needs_z3
@pytest.mark.z3
def test_the_demo_runs_and_its_output_is_byte_identical_across_runs():
    """spec/whatif_demo.py is executed, not merely present: it reads the golden
    cases, and its boundary answers become README claims, so they have to be
    produced rather than transcribed — and reproduced identically, like every
    other example here."""
    runs = [
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "spec" / "whatif_demo.py")],
            capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        for seed in ("0", "7")
    ]
    for run in runs:
        assert run.returncode == 0, run.stderr
    assert runs[0].stdout == runs[1].stdout

    out = runs[0].stdout
    # The three flagship boundaries, and the guard firing.
    assert "kernel confirms  2026-04-24 -> true" in out
    assert "kernel refutes   2026-04-25 -> false" in out
    assert "kernel confirms  2984.02 -> 0.00 USD" in out
    assert "kernel confirms  2026-02-18 -> true" in out
    assert "solver/kernel contradiction" in out
    assert "NO CONTRADICTION RAISED" not in out
