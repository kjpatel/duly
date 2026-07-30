"""`python -m duly_dmn` — compile, verify, describe."""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from duly_dmn.__main__ import EXIT_COMPILE_ERROR, EXIT_DRIFT, EXIT_OK, main
from dmntest_helpers import REFUSALS, REPO, TRID_COMPILED, TRID_DMN


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "duly_dmn", *args],
        capture_output=True, text=True, cwd=REPO,
    )


def test_compile_writes_the_pack_to_stdout():
    proc = run("compile", str(TRID_DMN))
    assert proc.returncode == EXIT_OK
    assert yaml.safe_load(proc.stdout)["pack"]["name"] == "trid-fee-tolerance-dmn"


def test_compile_to_a_file(tmp_path):
    out = tmp_path / "pack.yaml"
    assert main(["compile", str(TRID_DMN), "-o", str(out)]) == EXIT_OK
    assert yaml.safe_load(out.read_text())["rules"][0]["id"] == "TRID-CAT-02"


def test_verify_passes_on_the_committed_compilation():
    proc = run("verify", str(TRID_DMN), str(TRID_COMPILED))
    assert proc.returncode == EXIT_OK, proc.stdout
    assert "ok" in proc.stdout


def test_verify_reports_drift_with_a_diff(tmp_path):
    stale = tmp_path / "stale.yaml"
    stale.write_text(TRID_COMPILED.read_text().replace("TRID-DEF-00", "TRID-DEF-99"))
    proc = run("verify", str(TRID_DMN), str(stale))
    assert proc.returncode == EXIT_DRIFT
    assert "TRID-DEF-99" in proc.stdout and "TRID-DEF-00" in proc.stdout


def test_verify_on_a_missing_file_is_drift_not_a_crash(tmp_path):
    proc = run("verify", str(TRID_DMN), str(tmp_path / "nope.yaml"))
    assert proc.returncode == EXIT_DRIFT
    assert "does not exist" in proc.stdout


def test_describe_shows_columns_bindings_and_citations():
    proc = run("describe", str(TRID_DMN))
    assert proc.returncode == EXIT_OK
    for fragment in (
        "hitPolicy=UNIQUE",
        "hitPolicy=FIRST",
        "trid:actualAmountAtClosing",
        "TRID-ZT-01",
        "12 CFR 1026.19(e)(3)(i)",
        "Default presumption",
    ):
        assert fragment in proc.stdout


def test_describe_works_on_a_document_that_will_not_compile():
    """`describe` reads; it does not compile. It has to keep working on the
    broken table you are trying to understand."""
    proc = run("describe", str(REFUSALS / "uncited-row.dmn"))
    assert proc.returncode == EXIT_OK
    assert "<no duly:citation>" in proc.stdout


@pytest.mark.parametrize("filename", ["uncited-row.dmn", "unsupported-hit-policy.dmn"])
def test_compile_errors_exit_2_and_print_to_stderr(filename):
    proc = run("compile", str(REFUSALS / filename))
    assert proc.returncode == EXIT_COMPILE_ERROR
    assert proc.stdout == ""
    assert proc.stderr.startswith("[")
