"""Tests for the what-if solver (whatif/duly_whatif).

Everything needing the solver carries `@pytest.mark.z3` and skips when
z3-solver is not importable — the posture `prove`, `docling` and `linkml`
all take. Run them with:

    uv run --with z3-solver pytest whatif/tests -q -m z3

The boundary dates and amounts below are computed BY HAND in the docstrings
and asserted as literals. That is the point of them: a test that recomputed
the answer the way the tool does would pass just as happily against a broken
tool, and these particular numbers become README claims.
"""

from __future__ import annotations

import datetime as _dt
import subprocess
import sys

import pytest

from whatiftest_helpers import (  # noqa: E402
    HAVE_Z3,
    REPO_ROOT,
    TRUE,
    load_case,
    money,
    needs_z3,
    perturbed,
    query_for,
    repo_registry,
    solve_for,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ---------------------------------------------------------------------------
# Wiring that must not need the solver
# ---------------------------------------------------------------------------


def test_importing_whatif_does_not_require_z3():
    """The core suite imports this package; the optional dependency must stay
    optional. A missing z3 is a *message*, not an ImportError."""
    from duly_whatif import query

    assert "z3-solver is not installed" in query.Z3_MISSING
    assert "uv run --with z3-solver" in query.Z3_MISSING


def test_the_verdict_names_are_the_documented_three():
    from duly_whatif import query

    assert query.SATISFIABLE == "SATISFIABLE"
    assert query.UNSATISFIABLE == "UNSATISFIABLE"
    assert query.UNSUPPORTED == "UNSUPPORTED"


def test_the_unsat_caveat_says_the_verdict_is_weaker():
    """The asymmetry has to reach a user, not only the spec."""
    from duly_whatif.render import UNSAT_CAVEAT

    assert "WEAKER" in UNSAT_CAVEAT
    assert "no point to check" in UNSAT_CAVEAT


# ---------------------------------------------------------------------------
# The flagship boundaries, computed by hand
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Flip
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_flip_finds_the_nearest_change_not_the_most_extreme_one():
    """notice-ny-0001 is decided non-compliant. What would reverse it?

    The notice went out 2026-05-27, twelve days before expiry. The nearest
    mailing date that flips the decision is the boundary itself, 2026-04-24 —
    33 days earlier — and the day after it does not flip. "Nearest" is the
    interesting question for a flip: how little would have had to change.
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
def test_a_flip_on_a_non_boolean_decision_is_refused_by_name():
    """"Anything other than 192.74" is a region, and an extremal over a region
    is not a question this tool answers. Refuse, and say which."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="names a region"):
        solve_for("trid-0001", "trid:actualAmountAtClosing", flip=True)


# ---------------------------------------------------------------------------
# The contradiction guard — the one that proves the contract works
# ---------------------------------------------------------------------------


def _with_broken_encoding(monkeypatch, old: str, new: str):
    """Hand the solver a pack that differs from the one the kernel will run.

    This is what an encoding bug looks like from the outside: the solver
    reasons about one rulebase and the kernel adjudicates another. Injecting
    it through `_encode` — the single seam where the solver's view of the
    rulebase enters — needs no test hook in the production path.
    """
    from duly_whatif import query as query_module

    real_encode = query_module._encode

    def broken(pack, registry):
        return real_encode(perturbed(pack, old, new), registry)

    monkeypatch.setattr(query_module, "_encode", broken)


@needs_z3
@pytest.mark.z3
def test_a_broken_encoding_trips_the_guard_at_the_boundary(monkeypatch):
    """Inject an encoding that disagrees with the kernel, and require a raise.

    A guard that has never fired is a guard nobody can claim. Here the solver
    reads the notice pack with its deficiency test perturbed from
    `days_between(...) < minDays` to `<= minDays`, which moves the compliance
    boundary by exactly one day: the solver believes 45 days is deficient and
    that the latest compliant mailing date is 2026-04-23.

    The kernel agrees 2026-04-23 is compliant, so the *answer* check passes —
    a weaker tool would stop there and return a wrong answer that happened to
    verify. The boundary check is what catches it: the solver claims
    2026-04-24 must be non-compliant, the kernel runs the real pack and says
    it is compliant, and the disagreement surfaces as an error carrying both
    artifacts instead of as a plausible-looking date.
    """
    from duly_whatif.query import SolverKernelContradiction, solve

    _with_broken_encoding(
        monkeypatch,
        "days_between(mailed, expiration) < minDays",
        "days_between(mailed, expiration) <= minDays",
    )

    with pytest.raises(SolverKernelContradiction) as excinfo:
        solve(
            query_for("notice-ny-0001", "nc:noticeMailedDate", target=TRUE),
            repo_registry(),
        )

    error = excinfo.value
    assert error.value == "2026-04-24"
    assert error.outcome.decided
    assert error.outcome.value == {"kind": "boolean", "value": True}
    assert any(
        f["attribute"] == "nc:noticeMailedDate"
        and f["value"]["value"] == "2026-04-24"
        for f in error.facts
    ), "the refuted fact set travels with the error"
    text = str(error)
    assert "solver/kernel contradiction" in text
    assert "kernel decided   true" in text
    assert "encoding that disagrees" in text


@needs_z3
@pytest.mark.z3
def test_a_broken_encoding_trips_the_guard_on_the_answer_itself(monkeypatch):
    """The other leg: an encoding whose *answer*, not its boundary, is wrong.

    Retyping the zero-tolerance categorisation guard from `"TransferTax"` to
    `"RecordingFee"` — the perturbation spec/pack-verification.md P7 records
    as failing at both levels — makes the solver believe trid-0001's fee is
    not a zero-tolerance charge at all, so it concludes that *no* closing
    amount owes a cure. With no boundary anywhere, the reported witness is
    today's own amount, and the kernel refutes it on the first run: the real
    pack knows the fee is a transfer tax and 3176.76 owes 192.74.

    Without the unbounded region falling back to a checkable witness, this
    query would have returned "unbounded, no extremal to verify" — an
    unverified claim, which is the one thing this package must not return.
    """
    from duly_whatif.query import SolverKernelContradiction, solve

    _with_broken_encoding(monkeypatch, 'feeType == "TransferTax"',
                          'feeType == "RecordingFee"')

    with pytest.raises(SolverKernelContradiction) as excinfo:
        solve(
            query_for("trid-0001", "trid:actualAmountAtClosing", target=money("0.00")),
            repo_registry(),
        )

    error = excinfo.value
    assert error.value == "3176.76"
    assert error.outcome.value == {
        "kind": "money", "amount": "192.74", "currency": "USD"
    }
    assert "kernel decided   192.74 USD" in str(error)


# ---------------------------------------------------------------------------
# UNSAT, and its asymmetry
# ---------------------------------------------------------------------------


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
    """The one place the asymmetry does not bite.

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
def test_every_member_of_a_finite_domain_is_run_through_the_kernel():
    """Freeing the governing state finds the notice pack's coverage hole.

    NY needs 45 days, FL 120, CA 75; the notice went out 12 days before
    expiry, so no *named* state is compliant. An unnamed one is: nothing
    concludes a minimum, so NC-NR-01 cannot bind its derived input and the
    default presumption stands. That is a real hole in the pack, and freeing
    a code input surfaces it without being told to look.
    """
    report = solve_for("notice-ny-0001", "nc:governingState", target=TRUE)

    assert report.verdict == "SATISFIABLE"
    assert report.complete is True
    assert len(report.answers) == 1
    answer = report.answers[0]
    assert answer.representative is not None
    assert "US-NY" in answer.value and "other than" in answer.value
    assert answer.decision == "true"


# ---------------------------------------------------------------------------
# Named refusals — never a guess
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_freeing_an_input_the_pack_never_reads_names_the_reason():
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="never reads resc:statedRescissionDeadline"):
        solve_for("resc-0001", "resc:statedRescissionDeadline", target=TRUE)


@needs_z3
@pytest.mark.z3
def test_freeing_an_attribute_the_case_does_not_assert_is_refused_not_invented():
    """duly's premise is that a fact is grounded. A value a solver proposed for
    a fact no document produced is grounded in nothing, so this refuses rather
    than minting the fact, the entity and the attestation it would need."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="does not mint"):
        solve_for("notice-ny-0001", "nc:terminationGround", target=TRUE)


@needs_z3
@pytest.mark.z3
def test_a_code_target_the_pack_cannot_conclude_is_refused_by_name():
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="no rule in this pack concludes"):
        solve_for(
            "trid-0001", "trid:feeType",
            decision="trid:toleranceCategory",
            target={"kind": "code", "value": "Nonsense"},
        )


@needs_z3
@pytest.mark.z3
def test_a_target_of_the_wrong_value_kind_is_refused_by_name():
    """A decimal decision cannot conclude a code, so the question has no answer
    even in principle. Say which kinds, rather than letting the term builder
    fail somewhere in the solver."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="is a decimal decision"):
        solve_for(
            "notice-ny-0001", "nc:governingState",
            decision="nc:requiredMinimumNoticeDays",
            target={"kind": "code", "value": "Nonsense"},
        )


# ---------------------------------------------------------------------------
# Nothing here touches adjudication
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_what_if_leaves_the_case_it_reasoned_about_untouched():
    """Facts are content-addressed and receipts replay byte-for-byte. A tool
    that mutated the fact dicts it was handed would corrupt the caller's case
    silently, so the substitution deep-copies and re-addresses."""
    import copy

    query = query_for("trid-0001", "trid:actualAmountAtClosing", target=money("0.00"))
    before = copy.deepcopy(query.facts)

    from duly_whatif.query import solve

    solve(query, repo_registry())
    assert query.facts == before


@needs_z3
@pytest.mark.z3
def test_a_substituted_fact_is_re_addressed_not_edited():
    from duly_whatif.casefacts import content_hash, substitute

    _, facts, _ = load_case("trid-0001")
    changed = substitute(
        facts, "trid:actualAmountAtClosing", money("1.00")
    )
    fact = next(f for f in changed if f["attribute"] == "trid:actualAmountAtClosing")
    original = next(f for f in facts if f["attribute"] == "trid:actualAmountAtClosing")

    assert fact["contentHash"] != original["contentHash"]
    assert fact["contentHash"] == content_hash(fact)
    assert fact["id"] == f"urn:duly:fact:sha256:{fact['contentHash']}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


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
def test_the_answer_is_byte_identical_across_hash_seeds(case_id, free, target, extra):
    """A report is an artifact somebody diffs, and the repo forbids unseeded
    nondeterminism. The extremal is a property of the constraint set rather
    than of the solver's search, so it must not move with PYTHONHASHSEED."""
    argv = [
        sys.executable, "-m", "duly_whatif", "--ontologies", "ontologies",
        "--case", f"golden/cases/{case_id}", "--free", free,
        "--target", target, "--json", *extra,
    ]
    outputs = []
    for seed in ("0", "1", "12345"):
        run = subprocess.run(
            argv, capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        assert run.returncode == 0, run.stderr
        outputs.append(run.stdout)
    assert outputs[0] == outputs[1] == outputs[2]


@needs_z3
@pytest.mark.z3
def test_the_demo_runs_and_its_output_is_byte_identical_across_runs():
    """spec/whatif_demo.py is executed, not merely present: its boundary
    answers become README claims, so they have to be produced rather than
    transcribed — and reproduced identically, like every other example here."""
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


@needs_z3
@pytest.mark.z3
def test_repeated_runs_in_one_process_agree():
    first = solve_for("notice-ny-0001", "nc:noticeMailedDate", target=TRUE)
    second = solve_for("notice-ny-0001", "nc:noticeMailedDate", target=TRUE)
    assert first.extremal.value == second.extremal.value
    assert first.boundary.value == second.boundary.value


# ---------------------------------------------------------------------------
# The encoding is `prove`'s, unextended
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_encoding_is_the_one_prove_uses():
    """No second encoder. If this import ever stops being the source of the
    symbols and terms, the two tools have started to diverge — which is the
    defect this package was built to avoid."""
    from duly_assurance import smt
    from duly_whatif import query

    assert query.PackEncoding is smt.PackEncoding
    assert query.Universe is smt.Universe
    assert query.OTHER is smt.OTHER
    assert query.DATE_MIN is smt.DATE_MIN
