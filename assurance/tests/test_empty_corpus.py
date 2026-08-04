"""What `verify` and `impact` do with a corpus that has no cases.

Three states, and they are not the same thing:

- **missing directory** — a configuration mistake. Fails.
- **empty corpus** — a legitimate state. An adopter's corpus is empty on day
  one, so this must not fail, or the second command they ever run breaks
  their first CI job.
- **cases present** — the ordinary path.

`verify` already drew that line; `impact` raised on an empty corpus, so the
two disagreed about identical input. They now agree, and both say in words
that nothing was measured — because "0 of 0 decisions flip" and "verified 0
cases" are true sentences that read as passes, which is the trap
rulepacks/README.md already documents one level down for an uncovered pack.
"""

from __future__ import annotations

import pytest

from duly_assurance.impact import (
    EMPTY_CORPUS_SUMMARY,
    ImpactOperationalError,
    analyze,
    render_markdown,
    render_text,
)
from duly_assurance.verify import main as verify_main


@pytest.fixture()
def empty_corpus(tmp_path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "receipts").mkdir()
    return tmp_path


def test_impact_succeeds_on_an_empty_corpus(empty_corpus):
    report = analyze(empty_corpus)
    assert report["corpusEmpty"] is True
    assert report["totalCases"] == 0
    assert report["flipCount"] == 0


def test_impact_still_fails_on_a_missing_corpus(tmp_path):
    """Absent is a mistake; empty is a state. Collapsing them would make a
    typo'd --golden path look like a clean run."""
    with pytest.raises(ImpactOperationalError):
        analyze(tmp_path / "does-not-exist")


def test_the_empty_summary_cannot_be_read_as_a_pass(empty_corpus):
    summary = analyze(empty_corpus)["summary"]
    assert summary == EMPTY_CORPUS_SUMMARY
    assert "0 of 0" not in summary
    assert "nothing was measured" in summary


def test_both_renderers_say_nothing_was_measured(empty_corpus):
    report = analyze(empty_corpus)
    for rendered in (render_text(report), render_markdown(report)):
        assert "NO CASES IN CORPUS" in rendered
    assert "not evidence" in render_markdown(report)


def test_a_populated_corpus_keeps_the_ordinary_summary():
    """The empty-corpus wording must not leak into a real run."""
    from pathlib import Path

    report = analyze(Path("golden"))
    assert report["corpusEmpty"] is False
    assert "decisions flip" in report["summary"]


def test_verify_succeeds_but_announces_an_empty_corpus(empty_corpus, capsys):
    assert verify_main(["--golden", str(empty_corpus)]) == 0
    assert "NO CASES IN CORPUS" in capsys.readouterr().out


def test_verify_still_fails_on_a_missing_cases_directory(tmp_path, capsys):
    assert verify_main(["--golden", str(tmp_path / "nope")]) == 1
