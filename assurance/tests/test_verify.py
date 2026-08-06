"""Tests for the replay verifier (duly_assurance.verify).

Every corpus here is a copy of `fixtures/` — the toolkit's own, which survives
`git rm -r examples/` — rather than one built by `generate`. That is not only
about the deletion: the generator's templates are *example content* (Phase 1
made them a registry example content populates), so a verifier test that builds
its corpus with the generator is asserting the verifier through a dependency it
does not have.

The one test whose subject genuinely is the committed teaching corpus says so
in its name, and moves with `golden/`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from duly_assurance import verify

REPO = Path(__file__).resolve().parents[2]
FIXTURE_CORPUS = REPO / "fixtures"


@pytest.fixture()
def corpus(tmp_path) -> Path:
    """A writable copy of the fixture corpus, for tests that tamper with it."""
    out = tmp_path / "corpus"
    (out / "cases").mkdir(parents=True)
    (out / "receipts").mkdir(parents=True)
    shutil.copytree(FIXTURE_CORPUS / "cases", out / "cases", dirs_exist_ok=True)
    shutil.copytree(FIXTURE_CORPUS / "receipts", out / "receipts", dirs_exist_ok=True)
    return out


def test_verify_passes_on_the_fixture_corpus(capsys):
    assert verify.main(["--golden", str(FIXTURE_CORPUS)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("verified ")
    assert out.rstrip().endswith("cases")


def test_verify_passes_on_the_committed_golden_corpus(capsys):
    """Example content: the subject is the teaching corpus itself, so this
    moves with it rather than onto a fixture."""
    golden = REPO / "golden"
    assert (golden / "cases").is_dir(), "golden corpus has not been generated"
    assert verify.main(["--golden", str(golden)]) == 0
    assert "verified 351 cases" in capsys.readouterr().out


def test_verify_passes_on_a_copied_corpus(corpus, capsys):
    """Replay does not depend on where the corpus lives."""
    assert verify.main(["--golden", str(corpus)]) == 0
    assert "verified 5 cases" in capsys.readouterr().out


def test_verify_fails_on_tampered_receipt_body(corpus, capsys):
    receipt_path = sorted((corpus / "receipts").glob("*.json"))[0]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["decision"] = {"tampered": True}  # body edit, hash field left alone
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(corpus)]) == 1
    printed = capsys.readouterr().out
    assert case_id in printed
    assert "decision" in printed


def test_verify_fails_on_tampered_receipt_hash(corpus, capsys):
    receipt_path = sorted((corpus / "receipts").glob("*.json"))[-1]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["receiptSha256"] = "0" * 64
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(corpus)]) == 1
    printed = capsys.readouterr().out
    assert case_id in printed
    assert "receiptSha256" in printed


def test_verify_refuses_a_receipt_at_unimplemented_semantics(corpus, capsys):
    """spec/compatibility.md C3: replay is scoped to a semantics version.

    Reported as UNSUPPORTED rather than MISMATCH because nothing was compared —
    and because the byte diff this would otherwise produce ("differing fields:
    engine, id, receiptSha256") describes a symptom and hides the cause.
    """
    receipt_path = sorted((corpus / "receipts").glob("*.json"))[0]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["engine"]["version"] = "0.0.2"
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(corpus)]) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("UNSUPPORTED ")
    assert case_id in printed
    assert "0.0.2" in printed


def test_verify_fails_on_missing_receipt(corpus, capsys):
    sorted((corpus / "receipts").glob("*.json"))[0].unlink()
    capsys.readouterr()
    assert verify.main(["--golden", str(corpus)]) == 1
    assert "missing golden receipt" in capsys.readouterr().out


def test_verify_fails_on_a_receipt_without_a_case(corpus, capsys):
    """The orphan check: a receipt whose case was removed is a corpus that no
    longer describes itself."""
    case_dir = sorted(p for p in (corpus / "cases").iterdir() if p.is_dir())[0]
    shutil.rmtree(case_dir)
    capsys.readouterr()
    assert verify.main(["--golden", str(corpus)]) == 1
    printed = capsys.readouterr().out
    assert "receipts without cases" in printed
    assert case_dir.name in printed
