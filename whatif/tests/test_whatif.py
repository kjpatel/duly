"""Tests for the what-if solver (whatif/duly_whatif).

Everything needing the solver carries `@pytest.mark.z3` and skips when
z3-solver is not importable — the posture `prove`, `docling` and `linkml`
all take. Run them with:

    uv run --with z3-solver pytest whatif/tests -q -m z3

**Two corpora, and the split is deliberate.** The solver's own contract —
flip, the contradiction guard, finite-domain completeness, the named
refusals, determinism — is *toolkit* behaviour, so it runs on `fixtures/`
and keeps failing when the teaching content is deleted. What stays pointed
at `golden/` is the set of tests whose subject genuinely is an example
pack's answer, marked EXAMPLE CONTENT below and moving with `examples/`.

The boundary dates and amounts in that second half are computed BY HAND in
the docstrings and asserted as literals. That is the point of them: a test
that recomputed the answer the way the tool does would pass just as happily
against a broken tool, and these particular numbers become README claims.
"""

from __future__ import annotations

import copy
import datetime as _dt
import subprocess
import sys

import pytest

from whatiftest_helpers import (  # noqa: E402
    FIXTURE_CASES,
    HAVE_Z3,
    REPO_ROOT,
    TRUE,
    fixture_query,
    fixture_registry,
    fixture_solve,
    load_case,
    load_fixture_case,
    money,
    needs_z3,
    perturbed,
    solve_for,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

# The fixture pack's own numbers, in one place. fx-0001 is a *restricted*
# widget scoring 12 against the 2026 threshold of 50, so the exception fires
# and it is decided `false`; fx-0002 is *ordinary* and scoring 80, so the
# default presumption stands and it is decided `true`.
FIXTURE_THRESHOLD = "50"
FIXTURE_BELOW_THRESHOLD = "49"

# Parametrizing over a glob is evaluated at collection, so an empty directory
# yields zero test cases and pytest reports only the count that remains —
# which reads exactly like success (CLAUDE.md). The list is built once here and
# guarded by a companion test that runs whether or not it is empty.
FIXTURE_CASE_IDS = sorted(p.name for p in FIXTURE_CASES.glob("fx-*") if p.is_dir())


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


def test_the_fixture_corpus_this_suite_runs_on_is_not_empty():
    """The companion to every parametrize below. Without it, deleting the
    fixture corpus would turn the solver's contract into zero collected tests
    and a green run."""
    assert FIXTURE_CASE_IDS, f"no fixture cases under {FIXTURE_CASES}"
    assert "fx-0001" in FIXTURE_CASE_IDS and "fx-0002" in FIXTURE_CASE_IDS


# ---------------------------------------------------------------------------
# Flip
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_flip_reports_the_nearest_change_not_the_most_extreme_one():
    """fx-0001 is decided `false`: restricted, and scoring 12 against a
    threshold of 50. What would reverse it?

    Every score from 50 upward reverses it, so an extremal question would
    answer with the top of the encoded range. "Nearest" is the interesting
    question for a flip — how little would have had to change — and the
    answer is the boundary itself, 50. One step back toward today's value
    must NOT flip, or it was not the nearest one.
    """
    report = fixture_solve("fx-0001", "fx:score", flip=True)

    assert report.current == "false"
    assert report.verdict == "SATISFIABLE"
    assert report.extremal_direction == "nearest"
    assert report.extremal.value == FIXTURE_THRESHOLD
    assert report.extremal.decision == "true"
    assert report.boundary.value == FIXTURE_BELOW_THRESHOLD
    assert report.boundary.refuted
    assert report.boundary.decision == "false"


@needs_z3
@pytest.mark.z3
def test_a_flip_on_a_non_boolean_decision_is_refused_by_name():
    """`fx:assessedFee` is money, and "anything other than 250.00 USD" is a
    region. An extremal over a region is not a question this tool answers, so
    it refuses and says which decision made it one."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="names a region"):
        fixture_solve("fx-0001", "fx:score", decision="fx:assessedFee", flip=True)


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
    reads the fixture pack with the exception's score test perturbed from
    `score < minimum` to `score <= minimum`, which moves the boundary by
    exactly one step: the solver believes a score of exactly 50 is still
    deficient, so the lowest permitted score it will report is 51.

    The kernel agrees 51 is permitted, so the *answer* check passes — a weaker
    tool would stop there and return a wrong answer that happened to verify.
    The boundary check is what catches it: the solver claims 50 must not be
    permitted, the kernel runs the real pack and says it is, and the
    disagreement surfaces as an error carrying both artifacts instead of as a
    plausible-looking number.
    """
    from duly_whatif.query import SolverKernelContradiction, solve

    _with_broken_encoding(monkeypatch, "score < minimum", "score <= minimum")

    with pytest.raises(SolverKernelContradiction) as excinfo:
        solve(fixture_query("fx-0001", "fx:score", target=TRUE), fixture_registry())

    error = excinfo.value
    assert error.value == FIXTURE_THRESHOLD
    assert error.outcome.decided
    assert error.outcome.value == {"kind": "boolean", "value": True}
    assert any(
        f["attribute"] == "fx:score" and f["value"]["value"] == FIXTURE_THRESHOLD
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

    Retyping the categorisation guard from `"restricted"` to `"ordinary"` —
    the shape spec/pack-verification.md P7 records as failing at both levels —
    makes the solver believe fx-0001's restricted widget is not restricted at
    all, so it concludes that *no* score owes the 250.00 fee. With no boundary
    anywhere, the reported witness is today's own score, and the kernel refutes
    it on the first run: the real pack knows the widget is restricted and 12 is
    below the threshold.

    Without the unbounded region falling back to a checkable witness, this
    query would have returned "unbounded, no extremal to verify" — an
    unverified claim, which is the one thing this package must not return.
    """
    from duly_whatif.query import SolverKernelContradiction, solve

    _with_broken_encoding(monkeypatch, 'category == "restricted"',
                          'category == "ordinary"')

    with pytest.raises(SolverKernelContradiction) as excinfo:
        solve(
            fixture_query(
                "fx-0001", "fx:score",
                decision="fx:assessedFee", target=money("0.00"),
            ),
            fixture_registry(),
        )

    error = excinfo.value
    assert error.value == "12"
    assert error.outcome.value == {
        "kind": "money", "amount": "250.00", "currency": "USD"
    }
    assert "kernel decided   250.00 USD" in str(error)


# ---------------------------------------------------------------------------
# UNSAT, and its asymmetry
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_an_unsatisfiable_answer_reports_the_weaker_claim():
    """No score makes fx-0002 impermissible: the exception needs a *restricted*
    category, and fx-0002's is ordinary, so the default presumption survives
    every value of the freed input.

    True — but not kernel-verified, because an ordered domain has no single
    point to hand the kernel, and the report has to say so.
    """
    from duly_whatif.render import UNSAT_CAVEAT, render

    report = fixture_solve(
        "fx-0002", "fx:score", target={"kind": "boolean", "value": False}
    )

    assert report.verdict == "UNSATISFIABLE"
    assert report.complete is False
    assert report.extremal is None
    assert report.exit_code == 1
    text = render(report)
    assert UNSAT_CAVEAT.splitlines()[0] in text


@needs_z3
@pytest.mark.z3
def test_every_member_of_a_finite_domain_is_run_through_the_kernel():
    """The one place the UNSAT asymmetry does not bite.

    `fx:category` is a code with a *closed* enum, so the domain is finite and
    every member — satisfying or not — is adjudicated rather than inferred.
    On fx-0001 (score 12, threshold 50) only `ordinary` escapes the exception,
    so the answer set is exactly one value and the report says `complete`:
    nothing here rests on the encoding.
    """
    report = fixture_solve("fx-0001", "fx:category", target=TRUE)

    assert report.free_kind == "code"
    assert report.verdict == "SATISFIABLE"
    assert report.complete is True
    assert [a.value for a in report.answers] == ["ordinary"]
    assert report.answers[0].decision == "true"
    # The value handed to the kernel is the case's own fact with one field
    # changed — the code system travels, because inventing one would be a guess.
    assert report.answers[0].fact_value["codeSystem"] == "duly-fixture/widget-categories"
    assert any("run through the kernel" in n for n in report.notes)


@needs_z3
@pytest.mark.z3
def test_a_finite_domain_that_satisfies_nothing_is_still_complete():
    """The negative half of the same claim, and the reason `complete` is a
    field rather than a phrasing choice.

    The fixture pack concludes exactly two fees, 0.00 and 250.00, so a target
    of 999.00 is reachable from no category at all. The verdict is
    UNSATISFIABLE with `complete` still true, because the kernel refused each
    member individually rather than the encoding refusing them collectively —
    which is the difference between a checked answer and an inferred one.
    """
    report = fixture_solve(
        "fx-0001", "fx:category",
        decision="fx:assessedFee", target=money("999.00"),
    )

    assert report.verdict == "UNSATISFIABLE"
    assert report.complete is True
    assert report.answers == []
    assert "verified rather than inferred" in report.reason


# ---------------------------------------------------------------------------
# Named refusals — never a guess
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_freeing_an_input_the_pack_never_reads_names_the_reason():
    """`fx:inspector` is in the fixture ontology and in no rule of the fixture
    pack, so the encoding has no symbol for it — which is itself the answer."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="never reads fx:inspector"):
        fixture_solve("fx-0001", "fx:inspector", target=TRUE)


@needs_z3
@pytest.mark.z3
def test_freeing_an_attribute_the_case_does_not_assert_is_refused_not_invented():
    """duly's premise is that a fact is grounded. A value a solver proposed for
    a fact no document produced is grounded in nothing, so this refuses rather
    than minting the fact, the entity and the attestation it would need."""
    from duly_whatif.query import Query, Unsupported, solve

    case, facts, pack = load_fixture_case("fx-0002")
    without_category = [f for f in facts if f["attribute"] != "fx:category"]
    assert len(without_category) == len(facts) - 1, "the case did assert one"

    query = Query(
        facts=without_category, pack=pack,
        as_of_effective=str(case["asOfEffective"]),
        as_of_knowledge=str(case["asOfKnowledge"]),
        decision=str(case["question"]), free="fx:category", target=TRUE,
    )
    with pytest.raises(Unsupported, match="does not mint"):
        solve(query, fixture_registry())


@needs_z3
@pytest.mark.z3
def test_a_code_target_the_pack_cannot_conclude_is_refused_by_name():
    """A code target no rule concludes is a question with no answer, and the
    refusal names the values that *are* concluded.

    The decision is added to a deep copy of the fixture pack in code rather
    than to the committed one: the fixture corpus is a test dependency, not a
    second demonstration, and its pack version is inside every committed
    receipt (fixtures/README.md) — so a rule added to reach one refusal path
    would cost a full corpus rebuild.
    """
    from duly_whatif.query import Query, Unsupported, solve

    case, facts, pack = load_fixture_case("fx-0001")
    synthetic = copy.deepcopy(pack)
    synthetic["decisions"].append({
        "attribute": "fx:reviewTier",
        "entityType": "fx:Widget",
        "question": "Which review tier applies?",
    })
    synthetic["rules"].append({
        "id": "FX-TIER-01",
        "version": "1.0.0",
        "priority": 100,
        "citation": {"text": "Fixture review tier (fictional, test-local)"},
        "effectiveFrom": "1900-01-01",
        "given": {
            "widget": {"entityType": "fx:Widget"},
            "category": {"attribute": "fx:category"},
        },
        "when": ['category == "restricted"'],
        "then": {
            "entity": "widget", "attribute": "fx:reviewTier",
            "value": {"kind": "code", "value": "standard"},
        },
    })

    query = Query(
        facts=facts, pack=synthetic,
        as_of_effective=str(case["asOfEffective"]),
        as_of_knowledge=str(case["asOfKnowledge"]),
        decision="fx:reviewTier", free="fx:category",
        target={"kind": "code", "value": "Nonsense"},
    )
    with pytest.raises(Unsupported, match="no rule in this pack concludes") as excinfo:
        solve(query, fixture_registry())
    assert "standard" in str(excinfo.value), "the refusal names what IS concluded"


@needs_z3
@pytest.mark.z3
def test_a_target_of_the_wrong_value_kind_is_refused_by_name():
    """A decimal decision cannot conclude a code, so the question has no answer
    even in principle. Say which kinds, rather than letting the term builder
    fail somewhere in the solver."""
    from duly_whatif.query import Unsupported

    with pytest.raises(Unsupported, match="is a decimal decision"):
        fixture_solve(
            "fx-0001", "fx:category",
            decision="fx:requiredMinimumScore",
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
    query = fixture_query("fx-0001", "fx:score", target=TRUE)
    before = copy.deepcopy(query.facts)

    from duly_whatif.query import solve

    solve(query, fixture_registry())
    assert query.facts == before


@needs_z3
@pytest.mark.z3
def test_a_substituted_fact_is_re_addressed_not_edited():
    from duly_whatif.casefacts import content_hash, substitute

    _, facts, _ = load_fixture_case("fx-0001")
    changed = substitute(facts, "fx:score", {"kind": "decimal", "value": "99"})
    fact = next(f for f in changed if f["attribute"] == "fx:score")
    original = next(f for f in facts if f["attribute"] == "fx:score")

    assert fact["value"]["value"] == "99"
    assert fact["contentHash"] != original["contentHash"]
    assert fact["contentHash"] == content_hash(fact)
    assert fact["id"] == f"urn:duly:fact:sha256:{fact['contentHash']}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


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
@pytest.mark.parametrize("case_id", FIXTURE_CASE_IDS)
def test_the_answer_is_byte_identical_across_hash_seeds(case_id):
    """A report is an artifact somebody diffs, and the repo forbids unseeded
    nondeterminism. The extremal is a property of the constraint set rather
    than of the solver's search, so it must not move with PYTHONHASHSEED.

    Freeing the *code* input is what makes this run on every fixture case:
    fx-0003's score sits below the pack's confidence floor and is therefore not
    live, which is a refusal rather than an answer. `test_the_ordered_path_is_
    byte_identical_across_hash_seeds` covers the decimal grid separately.

    (`FIXTURE_CASE_IDS` is guarded by
    `test_the_fixture_corpus_this_suite_runs_on_is_not_empty` — a parametrize
    over an empty glob collects nothing and reads as success.)
    """
    args = [
        "--ontologies", "fixtures/ontology",
        "--case", f"fixtures/cases/{case_id}",
        "--free", "fx:category", "--target", "true", "--json",
    ]
    outputs = [_cli_output(args, seed) for seed in ("0", "1", "12345")]
    assert outputs[0] == outputs[1] == outputs[2]


@needs_z3
@pytest.mark.z3
@pytest.mark.parametrize(
    "case_id,free,target,extra",
    [
        ("fx-0001", "fx:score", "true", []),                      # ordered, open upward
        ("fx-0001", "fx:score", "true", ["--extremal", "min"]),   # the other end
        ("fx-0006", "fx:score", "true", []),                      # between the thresholds
        ("fx-0001", "fx:score", None, ["--flip"]),                # nearest, not extremal
    ],
)
def test_the_ordered_path_is_byte_identical_across_hash_seeds(
    case_id, free, target, extra
):
    """The decimal-grid half of the same claim: an extremal found by
    `Optimize` and a nearest-value search both have to be properties of the
    constraint set, not of the search."""
    args = [
        "--ontologies", "fixtures/ontology",
        "--case", f"fixtures/cases/{case_id}", "--free", free, "--json", *extra,
    ]
    if target is not None:
        args += ["--target", target]
    outputs = [_cli_output(args, seed) for seed in ("0", "12345")]
    assert outputs[0] == outputs[1]


@needs_z3
@pytest.mark.z3
def test_repeated_runs_in_one_process_agree():
    first = fixture_solve("fx-0001", "fx:score", target=TRUE)
    second = fixture_solve("fx-0001", "fx:score", target=TRUE)
    assert first.extremal.value == second.extremal.value == FIXTURE_THRESHOLD
    assert first.boundary.value == second.boundary.value == FIXTURE_BELOW_THRESHOLD


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


# ===========================================================================
# EXAMPLE CONTENT (moves with examples/)
# ===========================================================================
#
# Everything below has an example pack for its subject, not the solver. The
# dates and amounts are the teaching packs' own answers — README claims about
# `rulepacks/` and `golden/` — so these tests belong with the content that
# makes them true and move when it moves. Deleting the example content should
# delete them; it must not quietly leave them green.


@needs_z3
@pytest.mark.z3
def test_the_notice_packs_45_day_boundary():
    """EXAMPLE CONTENT (moves with examples/). The latest mailing date that
    keeps notice-ny-0001 compliant.

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
    """EXAMPLE CONTENT (moves with examples/). The largest closing amount on
    trid-0001 that owes no tolerance cure.

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
    """EXAMPLE CONTENT (moves with examples/). The flagship TILA answer, and
    the reason the calendar had to be exact.

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
    """EXAMPLE CONTENT (moves with examples/). The same TILA arithmetic run
    backwards through the calendar.

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
    """EXAMPLE CONTENT (moves with examples/). notice-ny-0001 is decided
    non-compliant. What would reverse it?

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
    """EXAMPLE CONTENT (moves with examples/). No consummation date lets
    resc-0001 fund on the day it consummates.

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
    """EXAMPLE CONTENT (moves with examples/). The boolean-input half of the
    finite-domain claim, which the fixture pack cannot carry: it has no
    boolean *input*, only a boolean decision.

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
    """EXAMPLE CONTENT (moves with examples/). The dwelling flag is what makes
    rescission apply at all, so exactly one of its two values reaches the
    pack's computed deadline."""
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
    """EXAMPLE CONTENT (moves with examples/). Freeing the governing state
    finds the notice pack's coverage hole.

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
    """EXAMPLE CONTENT (moves with examples/). The same determinism claim the
    fixture cases carry, over the four example queries the README quotes — a
    named list rather than a glob, so deleting `golden/` errors here rather
    than collecting nothing."""
    args = [
        "--ontologies", "ontologies", "--case", f"golden/cases/{case_id}",
        "--free", free, "--target", target, "--json", *extra,
    ]
    outputs = [_cli_output(args, seed) for seed in ("0", "1", "12345")]
    assert outputs[0] == outputs[1] == outputs[2]


@needs_z3
@pytest.mark.z3
def test_the_demo_runs_and_its_output_is_byte_identical_across_runs():
    """EXAMPLE CONTENT (moves with examples/). spec/whatif_demo.py is executed,
    not merely present: it reads the golden cases, and its boundary answers
    become README claims, so they have to be produced rather than transcribed —
    and reproduced identically, like every other example here."""
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
