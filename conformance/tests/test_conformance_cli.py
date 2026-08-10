"""The CLI's own contract: where the registry comes from, and how it fails.

No test exercised this surface before, which is exactly why it shipped with a
repo-relative default and an uncaught traceback — both invisible from inside
the repository, where the default happened to be correct, and both the first
thing an adopter met (docs/m5-plan.md, Appendix A finding A3).

Every registry below is the toolkit's own — `fixtures/ontology/`, one invented
ontology — or a directory built in `tmp_path`. That is the point of the
surface: the CLI has no opinion about which ontologies it is handed, so a test
that proved it works by handing it duly's *teaching* ontologies would have been
asserting the content rather than the contract, and would have stopped being
collected the day that content was deleted. The claim that the CLI does in fact
read this repository's committed registry is `examples/tests/
test_example_conformance_cli.py`, and it is deleted with the registry.
"""

from __future__ import annotations

import json

import pytest

from duly_conformance.__main__ import main
from conformancetest_helpers import FIXTURE_ONTOLOGIES, REPO

ONTOLOGIES = str(FIXTURE_ONTOLOGIES)

#: A committed fixture fact, conformant by construction: `fixtures/` is built
#: against `duly-fixture@0.1.0` and its facts' hashes pin that `schemaRef`.
FIXTURE_FACT = REPO / "fixtures" / "cases" / "fx-0001" / "facts" / "fx-score.json"


def test_the_registry_directory_has_no_default(capsys, monkeypatch):
    """`ontologies` used to be one: duly's own layout, relative to wherever
    the command was run. Correct in this repo, meaningless anywhere else."""
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        main(["list"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--ontologies" in err
    assert "DULY_ONTOLOGIES" in err
    assert "no default" in err


def test_the_env_var_supplies_it(capsys, monkeypatch):
    monkeypatch.setenv("DULY_ONTOLOGIES", ONTOLOGIES)
    assert main(["list"]) == 0
    assert "duly-fixture@0.1.0" in capsys.readouterr().out


def test_the_flag_wins_over_the_env_var(capsys, monkeypatch):
    monkeypatch.setenv("DULY_ONTOLOGIES", "/nonexistent")
    assert main(["--ontologies", ONTOLOGIES, "list"]) == 0
    assert "duly-fixture@0.1.0" in capsys.readouterr().out


def test_a_missing_registry_is_diagnosed_not_raised(capsys, monkeypatch, tmp_path):
    """A stack trace naming an exception class reads as a duly bug. It is not
    one: the user pointed at the wrong directory, and the message must say so."""
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    assert main(["--ontologies", str(tmp_path), "list"]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "no ontology files found" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_check_reports_conformance_against_a_supplied_registry(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    fact = json.loads(FIXTURE_FACT.read_text(encoding="utf-8"))
    assert fact["attribute"] == "fx:score"  # the pair the mutation below breaks
    path = tmp_path / "fact.json"
    path.write_text(json.dumps(fact))
    assert main(["--ontologies", ONTOLOGIES, "check", str(path)]) == 0
    assert "conform" in capsys.readouterr().out


def test_check_exits_1_on_a_nonconformant_fact(capsys, monkeypatch, tmp_path):
    """Exit 1 is "your facts are wrong"; exit 2 is "I could not look" — the
    two must not collapse, or a CI job cannot tell a broken registry from a
    broken corpus."""
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    fact = json.loads(FIXTURE_FACT.read_text(encoding="utf-8"))
    fact["attribute"] = "fx:scoreTypo"
    path = tmp_path / "fact.json"
    path.write_text(json.dumps(fact))
    assert main(["--ontologies", ONTOLOGIES, "check", str(path)]) == 1
    assert "FAIL" in capsys.readouterr().out
