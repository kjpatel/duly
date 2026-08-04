"""Tests for the replay verifier (duly_assurance.verify)."""

from __future__ import annotations

import json
from pathlib import Path

from duly_assurance import generate, verify

REPO = Path(__file__).resolve().parents[2]


def test_verify_passes_on_committed_golden_corpus(capsys):
    golden = REPO / "golden"
    assert (golden / "cases").is_dir(), "golden corpus has not been generated"
    assert verify.main(["--golden", str(golden)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("verified ")
    assert out.rstrip().endswith("cases")


def test_verify_passes_on_freshly_generated_corpus(tmp_path, capsys):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "9"]) == 0
    capsys.readouterr()
    assert verify.main(["--golden", str(out)]) == 0
    assert "verified 4 cases" in capsys.readouterr().out


def test_verify_fails_on_tampered_receipt_body(tmp_path, capsys):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "9"]) == 0
    receipt_path = sorted((out / "receipts").glob("*.json"))[0]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["decision"] = {"tampered": True}  # body edit, hash field left alone
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(out)]) == 1
    printed = capsys.readouterr().out
    assert case_id in printed
    assert "decision" in printed


def test_verify_fails_on_tampered_receipt_hash(tmp_path, capsys):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "9"]) == 0
    receipt_path = sorted((out / "receipts").glob("*.json"))[-1]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["receiptSha256"] = "0" * 64
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(out)]) == 1
    printed = capsys.readouterr().out
    assert case_id in printed
    assert "receiptSha256" in printed


def test_verify_refuses_a_receipt_at_unimplemented_semantics(tmp_path, capsys):
    """spec/compatibility.md C3: replay is scoped to a semantics version.

    Reported as UNSUPPORTED rather than MISMATCH because nothing was compared —
    and because the byte diff this would otherwise produce ("differing fields:
    engine, id, receiptSha256") describes a symptom and hides the cause.
    """
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "9"]) == 0
    receipt_path = sorted((out / "receipts").glob("*.json"))[0]
    case_id = receipt_path.stem
    doc = json.loads(receipt_path.read_text())
    doc["engine"]["version"] = "0.0.2"
    receipt_path.write_text(json.dumps(doc, indent=2) + "\n")
    capsys.readouterr()
    assert verify.main(["--golden", str(out)]) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("UNSUPPORTED ")
    assert case_id in printed
    assert "0.0.2" in printed


def test_verify_fails_on_missing_receipt(tmp_path, capsys):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "9"]) == 0
    receipt_path = sorted((out / "receipts").glob("*.json"))[0]
    receipt_path.unlink()
    capsys.readouterr()
    assert verify.main(["--golden", str(out)]) == 1
    assert "missing golden receipt" in capsys.readouterr().out
