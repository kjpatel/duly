"""The what-if CLI contract: exit codes, argument refusals, and JSON shape.

The unmarked tests here hold the parts that must work *without* z3, because
the core suite runs them: argument parsing, the missing-dependency message,
and the guarantee that importing the CLI does not drag an optional dependency
into a kernel-only install.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from whatiftest_helpers import REPO_ROOT, needs_z3  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def run_cli(*args, expect=None):
    result = subprocess.run(
        [sys.executable, "-m", "duly_whatif", *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
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
        "--case", "golden/cases/trid-0001", "--free", "trid:actualAmountAtClosing",
        "--target", "0.00", "--flip", expect=2,
    )
    assert "exactly one of --target and --flip" in result.stderr


def test_a_query_needs_a_case_or_facts_and_a_pack():
    result = run_cli("--free", "x:y", "--target", "true", expect=2)
    assert "--case" in result.stderr


def test_importing_the_cli_does_not_require_z3():
    from duly_whatif.__main__ import build_parser

    assert build_parser().prog == "python -m duly_whatif"


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_a_satisfiable_query_exits_zero():
    result = run_cli(
        "--case", "golden/cases/trid-0001",
        "--free", "trid:actualAmountAtClosing", "--target", "0.00", expect=0,
    )
    assert "SATISFIABLE" in result.stdout
    assert "2984.02" in result.stdout


@needs_z3
@pytest.mark.z3
def test_an_unsatisfiable_query_exits_one_and_prints_the_caveat():
    result = run_cli(
        "--case", "golden/cases/resc-0001",
        "--free", "resc:consummationDate", "--target", "true", expect=1,
    )
    assert "UNSATISFIABLE" in result.stdout
    assert "WEAKER" in result.stdout


@needs_z3
@pytest.mark.z3
def test_an_unsupported_query_exits_two_and_names_the_construct():
    result = run_cli(
        "--case", "golden/cases/resc-0001",
        "--free", "resc:statedRescissionDeadline", "--target", "true", expect=2,
    )
    assert "UNSUPPORTED" in result.stderr
    assert "resc:statedRescissionDeadline" in result.stderr


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


@needs_z3
@pytest.mark.z3
def test_the_json_output_marks_every_answer_as_kernel_verified():
    result = run_cli(
        "--case", "golden/cases/notice-ny-0001",
        "--free", "nc:noticeMailedDate", "--target", "true", "--json", expect=0,
    )
    payload = json.loads(result.stdout)

    assert payload["verdict"] == "SATISFIABLE"
    assert payload["extremal"]["value"] == "2026-04-24"
    assert payload["extremal"]["verifiedByKernel"] is True
    assert payload["extremal"]["factValue"] == {"kind": "date", "value": "2026-04-24"}
    assert payload["boundary"] == {
        "value": "2026-04-25",
        "decision": "false",
        "refutedByKernel": True,
        "note": None,
    }


@needs_z3
@pytest.mark.z3
def test_the_json_output_flags_an_unsat_verdict_as_the_weaker_one():
    result = run_cli(
        "--case", "golden/cases/resc-0001",
        "--free", "resc:consummationDate", "--target", "true", "--json", expect=1,
    )
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "UNSATISFIABLE"
    assert payload["unsatIsWeaker"] is True
    assert payload["complete"] is False
