"""The conformance CLI, pointed at this repository's committed registry.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `conformance/tests/test_conformance_cli.py`, which asserts the
CLI's *contract* — that the registry has no path default, that a wrong
directory is diagnosed rather than raised, that exit 1 and exit 2 mean
different things — and now does so on the toolkit's own fixture registry. What
it can no longer say from there is the thing this file says: that the command
in `CLAUDE.md`'s Verify block,

    python -m duly_conformance --ontologies examples/ontologies check ...

actually runs against what this repository ships. That is an executable-docs
claim about the example content, and it goes when the content does.
"""

from __future__ import annotations

import json

from exampletest_helpers import ONTOLOGIES, REPO_ROOT, STARTERS

from duly_conformance.__main__ import main

_ONTOLOGIES = str(ONTOLOGIES)


def test_list_shows_both_committed_ontologies(capsys, monkeypatch):
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    assert main(["--ontologies", _ONTOLOGIES, "list"]) == 0
    out = capsys.readouterr().out
    assert "duly-starter-notice@0.1.0" in out
    assert "duly-mortgage-closing@0.1.0" in out


def test_check_passes_on_the_specs_committed_example_fact(capsys, monkeypatch, tmp_path):
    """The spec's worked example cites a teaching ontology, so it is checkable
    only while that ontology is here — which is why this leg lives with the
    content rather than beside the spec."""
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    fact = json.loads(
        (REPO_ROOT / "spec" / "examples" / "fact-notice-mailed.json").read_text(
            encoding="utf-8"
        )
    )
    assert fact["schemaRef"]["ontology"] == "duly-starter-notice"
    path = tmp_path / "fact.json"
    path.write_text(json.dumps(fact))
    assert main(["--ontologies", _ONTOLOGIES, "check", str(path)]) == 0
    assert "conform" in capsys.readouterr().out


def test_check_passes_on_a_committed_starter_fact(capsys, monkeypatch):
    """The starters are the facts an adopter actually reads first."""
    monkeypatch.delenv("DULY_ONTOLOGIES", raising=False)
    paths = sorted(STARTERS.glob("*/facts/*.json"))
    assert paths, f"no committed starter facts under {STARTERS}"
    assert main(["--ontologies", _ONTOLOGIES, "check", *map(str, paths)]) == 0
    assert "conform" in capsys.readouterr().out
