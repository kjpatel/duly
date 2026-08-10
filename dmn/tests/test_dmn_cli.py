"""`python -m duly_dmn` — compile, verify, describe."""

from __future__ import annotations

import subprocess
import sys

import yaml

from duly_dmn.__main__ import EXIT_COMPILE_ERROR, EXIT_DRIFT, EXIT_OK, main
from dmntest_helpers import FIXTURE_COMPILED, FIXTURE_DMN, FIXTURE_REFUSALS, REPO

# The CLI's subject is the CLI, so it is exercised on the toolkit's own DMN
# corpus rather than on the teaching table under `dmn/examples/` — that content
# moves under `examples/` and an adopter deletes it, taking with it any test
# that was only ever reaching through it (CLAUDE.md).
UNCITED = FIXTURE_REFUSALS / "uncited-row.dmn"


def run(*args):
    return subprocess.run(
        [sys.executable, "-m", "duly_dmn", *args],
        capture_output=True, text=True, cwd=REPO,
    )


def test_compile_writes_the_pack_to_stdout():
    proc = run("compile", str(FIXTURE_DMN))
    assert proc.returncode == EXIT_OK
    assert yaml.safe_load(proc.stdout)["pack"]["name"] == "duly-fixture-dmn"


def test_compile_to_a_file(tmp_path):
    out = tmp_path / "pack.yaml"
    assert main(["compile", str(FIXTURE_DMN), "-o", str(out)]) == EXIT_OK
    assert yaml.safe_load(out.read_text())["rules"][0]["id"] == "FXD-MINIMUM-01"


def test_verify_passes_on_the_committed_compilation():
    """`fixtures/dmn/widget-fee.pack.yaml` is committed compiler output. This
    is what keeps it honest without a build step: recompile, compare bytes."""
    proc = run("verify", str(FIXTURE_DMN), str(FIXTURE_COMPILED))
    assert proc.returncode == EXIT_OK, proc.stdout
    assert "ok" in proc.stdout


def test_verify_reports_drift_with_a_diff(tmp_path):
    stale = tmp_path / "stale.yaml"
    stale.write_text(FIXTURE_COMPILED.read_text().replace("FXD-FEE-00", "FXD-FEE-99"))
    proc = run("verify", str(FIXTURE_DMN), str(stale))
    assert proc.returncode == EXIT_DRIFT
    assert "FXD-FEE-99" in proc.stdout and "FXD-FEE-00" in proc.stdout


def test_verify_on_a_missing_file_is_drift_not_a_crash(tmp_path):
    proc = run("verify", str(FIXTURE_DMN), str(tmp_path / "nope.yaml"))
    assert proc.returncode == EXIT_DRIFT
    assert "does not exist" in proc.stdout


def test_describe_shows_columns_bindings_and_citations():
    proc = run("describe", str(FIXTURE_DMN))
    assert proc.returncode == EXIT_OK
    for fragment in (
        "hitPolicy=UNIQUE",
        "hitPolicy=FIRST",
        "fx:score",
        "fx:requiredMinimumScore",
        "FXD-FEE-01",
        "Fixture fee schedule, default (fictional)",
        "2026-01-01",
    ):
        assert fragment in proc.stdout, f"describe does not mention {fragment!r}"


def test_describe_works_on_a_document_that_will_not_compile():
    """`describe` reads; it does not compile. It has to keep working on the
    broken table you are trying to understand."""
    proc = run("describe", str(UNCITED))
    assert proc.returncode == EXIT_OK
    assert "<no duly:citation>" in proc.stdout


def test_compile_errors_exit_2_and_print_to_stderr():
    proc = run("compile", str(UNCITED))
    assert proc.returncode == EXIT_COMPILE_ERROR
    assert proc.stdout == ""
    assert proc.stderr.startswith("[missing-citation]")


def test_compile_with_ontologies_still_produces_the_committed_bytes():
    """`--ontologies` only ever adds refusals. On a document whose cells agree
    with the vocabulary it pins, the compiled bytes must not move — otherwise
    a committed compilation would depend on how it was invoked."""
    proc = run(
        "compile", str(FIXTURE_DMN), "--ontologies", str(REPO / "fixtures" / "ontology")
    )
    assert proc.returncode == EXIT_OK, proc.stderr
    assert proc.stdout == FIXTURE_COMPILED.read_text(encoding="utf-8")
