"""The what-if CLI contract: exit codes, argument refusals, and JSON shape.

The unmarked tests here hold the parts that must work *without* z3, because
the core suite runs them: argument parsing, the missing-dependency message,
and the guarantee that importing the CLI does not drag an optional dependency
into a kernel-only install.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from whatiftest_helpers import REPO_ROOT, needs_z3  # noqa: E402

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

    assert build_parser().prog == "python -m duly_whatif"


# ---------------------------------------------------------------------------
# Roots: what this CLI is allowed to assume about where things live
# ---------------------------------------------------------------------------
#
# Both defects here are one assumption — that duly's own checkout is the
# content — and both were invisible from inside it (M5 plan, A9).


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
def test_without_a_registry_the_report_says_so():
    """The A9 defect proper. Absence is legal — kinds are inferred from use —
    but the answer is weaker in a way nothing else in the output reveals, so
    silence would hand back the weaker answer looking like the stronger.

    Still on example content, and deliberately: reaching this note requires a
    pack whose kinds are *all* inferable from use, and the fixture pack is not
    one (its widest guard compares two bound variables, so `fx:score` has no
    inferable kind — which is what the next test exercises). Phase 3 part 3
    gives the fixtures an inferable pack; until then this moves with `golden/`.
    """
    result = run_cli(
        "--case", "golden/cases/notice-ny-0001",
        "--free", "nc:noticeMailedDate", "--target", "true", "--json", expect=0,
    )
    notes = json.loads(result.stdout)["notes"]
    assert any("no ontology registry supplied" in n for n in notes)


@needs_z3
@pytest.mark.z3
def test_with_a_registry_it_does_not():
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
