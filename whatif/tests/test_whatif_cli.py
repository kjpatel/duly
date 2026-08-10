"""The what-if CLI contract: exit codes, argument refusals, and JSON shape.

The unmarked tests here hold the parts that must work *without* z3, because
the core suite runs them: argument parsing, the missing-dependency message,
and the guarantee that importing the CLI does not drag an optional dependency
into a kernel-only install.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from whatiftest_helpers import FIXTURE_CASES, REPO_ROOT, needs_z3  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def run_cli(*args, expect=None, cwd=None, env=None):
    environ = None
    if env is not None:
        environ = {**os.environ, **env}
    result = subprocess.run(
        [sys.executable, "-m", "duly_whatif", *args],
        capture_output=True, text=True, cwd=cwd or REPO_ROOT, env=environ,
    )
    if expect is not None:
        assert result.returncode == expect, result.stderr or result.stdout
    return result


# ---------------------------------------------------------------------------
# Wiring that must not need the solver
# ---------------------------------------------------------------------------


def test_the_help_text_describes_the_verification_contract():
    result = run_cli("--help", expect=0)
    assert "verified by running the kernel" in result.stdout
    assert "reaches a receipt" in result.stdout


def test_target_and_flip_are_mutually_exclusive():
    result = run_cli(
        "--case", "fixtures/cases/fx-0001", "--free", "fx:score",
        "--target", "true", "--flip", expect=2,
    )
    assert "exactly one of --target and --flip" in result.stderr


def test_a_query_needs_a_case_or_facts_and_a_pack():
    result = run_cli("--free", "x:y", "--target", "true", expect=2)
    assert "--case" in result.stderr


def test_importing_the_cli_does_not_require_z3():
    from duly_whatif.__main__ import build_parser

    # The console-script name, since M5 packaging: `duly-whatif` is what an
    # installed user runs, and --help must introduce the command by the name
    # that invoked it. `python -m duly_whatif` still works and argparse shows
    # the same prog either way — one name in the usage line, chosen for the
    # audience that sees it most.
    assert build_parser().prog == "duly-whatif"


# ---------------------------------------------------------------------------
# Roots: what this CLI is allowed to assume about where things live
# ---------------------------------------------------------------------------
#
# Both defects here were one assumption — that duly's own checkout is the
# content — and both were invisible from inside it (M5 plan, A9). Only the
# pack-resolution half is asserted here now; the registry half needs a pack
# whose kinds are all inferable from use, which the fixture pack is not, so
# `test_without_a_registry_the_report_says_so` moved to
# `examples/tests/test_example_whatif_boundaries.py` with the notice pack it
# has to pose the question with.


@needs_z3
@pytest.mark.z3
def test_a_case_resolves_its_pack_without_this_package_knowing_where_it_lives(tmp_path):
    """`_repo_root()` used to be `parents[2]` of the *installed package*: the
    repository from a checkout, a site-packages directory from a wheel. It now
    shares `corpus.resolve_pack_path` with verify/impact/generate, so an
    absolute case path resolves from any working directory at all."""
    result = run_cli(
        "--ontologies", str(REPO_ROOT / "fixtures" / "ontology"),
        "--case", str(REPO_ROOT / "fixtures" / "cases" / "fx-0001"),
        "--free", "fx:score", "--target", "true",
        cwd=tmp_path, expect=0,
    )
    assert "SATISFIABLE" in result.stdout


@needs_z3
@pytest.mark.z3
def test_with_a_registry_it_does_not():
    """A supplied registry means no "no ontology registry" note — the positive
    half of the pair whose negative half now lives with the example content
    (see the block comment above)."""
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", "--json", expect=0,
    )
    notes = json.loads(result.stdout)["notes"]
    assert not any("no ontology registry" in n for n in notes)


@needs_z3
@pytest.mark.z3
def test_the_registry_may_come_from_the_environment():
    result = run_cli(
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", "--json",
        env={"DULY_ONTOLOGIES": str(REPO_ROOT / "fixtures" / "ontology")}, expect=0,
    )
    assert not any(
        "no ontology registry" in n for n in json.loads(result.stdout)["notes"]
    )


def test_an_ontologies_path_that_is_not_there_is_refused():
    """Omitting the flag is a choice; typing a wrong path is not. Proceeding
    without the registry the caller asked for would be the silent degradation
    this whole task is about, one level up."""
    result = run_cli(
        "--ontologies", "no/such/place",
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", expect=2,
    )
    assert "no ontology registry at" in result.stderr


@needs_z3
@pytest.mark.z3
def test_a_pack_needing_a_registry_says_which_attribute_and_why():
    """Some packs cannot be encoded without one: an attribute whose kind no
    guard reveals has nothing to infer from. This escaped as an uncaught
    `OutOfFragment` traceback until the repo-relative default stopped hiding
    it — a diagnostic's job, done by a stack trace, which is A3's second half
    in a second CLI."""
    result = run_cli(
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", expect=2,
    )
    assert "UNSUPPORTED" in result.stderr
    assert "fx:score" in result.stderr
    assert "--ontologies" in result.stderr


# ---------------------------------------------------------------------------
# Reading a case: the asOf point, in either form the toolchain writes
# ---------------------------------------------------------------------------
#
# The unit is in `test_whatif.py`; these two run the whole CLI over a case file
# carrying each form, because the defect was end-to-end — `duly-whatif` against
# a committed, review-exported golden case, tracebacking on the timestamp that
# case.yaml legally carries.
#
# The case is built here rather than added to `fixtures/`: a fixture case's
# `asOfEffective` is inside no hash, but the corpus is a committed dependency
# of several suites, and one more case in it to exercise a string form is a
# corpus change to make a test convenient. Copying the facts and writing the
# case.yaml inline costs four lines and leaves both forms visible in the test.

CASE_YAML = (
    "id: fx-0001\n"
    "pack: fixtures/pack.yaml\n"
    "question: fx:permitted\n"
    'asOfEffective: "{effective}"\n'
    'asOfKnowledge: "2026-03-02T12:00:00Z"\n'
)


def _case_with_effective(tmp_path, effective: str):
    """A copy of fx-0001 whose `asOfEffective` reads `effective`."""
    case_dir = tmp_path / "cases" / "fx-0001"
    shutil.copytree(FIXTURE_CASES / "fx-0001" / "facts", case_dir / "facts")
    (case_dir / "case.yaml").write_text(CASE_YAML.format(effective=effective))
    return case_dir


@needs_z3
@pytest.mark.z3
def test_a_case_whose_as_of_is_a_timestamp_answers_like_the_bare_date(tmp_path):
    """`2026-06-01` and `2026-06-01T00:00:00Z` are one evaluation point.

    The kernel has always read them that way (`normalize_point`), and both
    forms are committed in `golden/`: the generator writes the first, the
    review exporter writes the second because it copies the receipt's
    `asOf.effective`, which the receipt schema types `date-time`. Only the
    echoed point differs between the two reports; every answer is identical.
    """
    reports = [
        json.loads(
            run_cli(
                "--ontologies", "fixtures/ontology",
                "--case", str(_case_with_effective(tmp_path / form, effective)),
                "--free", "fx:score", "--target", "true", "--json", expect=0,
            ).stdout
        )
        for form, effective in (
            ("bare", "2026-06-01"), ("stamped", "2026-06-01T00:00:00Z")
        )
    ]

    assert reports[0].pop("asOfEffective") == "2026-06-01"
    assert reports[1].pop("asOfEffective") == "2026-06-01T00:00:00Z"
    assert reports[0] == reports[1]
    assert reports[0]["extremal"]["value"] == "50"


@needs_z3
@pytest.mark.z3
def test_a_case_whose_as_of_is_not_a_date_is_refused_naming_field_and_file(tmp_path):
    """A genuinely bad point is a diagnostic, like `--ontologies no/such/place`
    — not the traceback the legal timestamp used to get."""
    case_dir = _case_with_effective(tmp_path, "yesterday")
    result = run_cli(
        "--ontologies", "fixtures/ontology", "--case", str(case_dir),
        "--free", "fx:score", "--target", "true", expect=2,
    )
    assert "asOfEffective" in result.stderr
    assert str(case_dir / "case.yaml") in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_satisfiable_query_exits_zero():
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", expect=0,
    )
    assert "SATISFIABLE" in result.stdout
    assert "50" in result.stdout


@needs_z3
@pytest.mark.z3
def test_an_unsatisfiable_query_exits_one_and_prints_the_caveat():
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0002",
        "--free", "fx:score", "--target", "false", expect=1,
    )
    assert "UNSATISFIABLE" in result.stdout
    assert "WEAKER" in result.stdout


@needs_z3
@pytest.mark.z3
def test_an_unsupported_query_exits_two_and_names_the_construct():
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:requiredMinimumScore", "--target", "true", expect=2,
    )
    assert "UNSUPPORTED" in result.stderr
    assert "fx:requiredMinimumScore" in result.stderr


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_json_output_marks_every_answer_as_kernel_verified():
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0001",
        "--free", "fx:score", "--target", "true", "--json", expect=0,
    )
    payload = json.loads(result.stdout)

    assert payload["verdict"] == "SATISFIABLE"
    assert payload["extremal"]["value"] == "50"
    assert payload["extremal"]["verifiedByKernel"] is True
    assert payload["extremal"]["factValue"] == {"kind": "decimal", "value": "50"}
    assert payload["boundary"] == {
        "value": "49",
        "decision": "false",
        "refutedByKernel": True,
        "note": None,
    }


@needs_z3
@pytest.mark.z3
def test_the_json_output_flags_an_unsat_verdict_as_the_weaker_one():
    result = run_cli(
        "--ontologies", "fixtures/ontology",
        "--case", "fixtures/cases/fx-0002",
        "--free", "fx:score", "--target", "false", "--json", expect=1,
    )
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "UNSATISFIABLE"
    assert payload["unsatIsWeaker"] is True
    assert payload["complete"] is False
