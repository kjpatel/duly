"""Tests for the golden-corpus generator (duly_assurance.generate)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from duly_assurance import generate
from duly_kernel.api import adjudicate

REPO = Path(__file__).resolve().parents[2]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_same_seed_regeneration_is_byte_identical(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert generate.main(["--out", str(a), "--count", "12", "--seed", "3"]) == 0
    assert generate.main(["--out", str(b), "--count", "12", "--seed", "3"]) == 0
    tree_a = _tree_bytes(a)
    tree_b = _tree_bytes(b)
    assert tree_a.keys() == tree_b.keys()
    for rel in tree_a:
        assert tree_a[rel] == tree_b[rel], f"{rel} differs between regenerations"


def test_case_ids_allocation_and_layout(tmp_path):
    out = tmp_path / "g"
    assert generate.main(
        ["--out", str(out), "--count", "8", "--seed", "5", "--templates", "ny,trid"]
    ) == 0
    ids = sorted(p.name for p in (out / "cases").iterdir())
    ny = [i for i in ids if i.startswith("notice-ny-")]
    trid = [i for i in ids if i.startswith("trid-")]
    # weights 3:1 -> 6 notice-ny cases, 2 trid cases
    assert len(ny) == 6 and len(trid) == 2
    assert ny[0] == "notice-ny-0001"
    assert trid == ["trid-0001", "trid-0002"]
    # one receipt per case, and each case dir carries case.yaml + facts
    receipts = sorted(p.stem for p in (out / "receipts").glob("*.json"))
    assert receipts == ids
    for case_id in ids:
        case = yaml.safe_load((out / "cases" / case_id / "case.yaml").read_text())
        assert case["id"] == case_id
        assert (REPO / case["pack"]).is_file()
        assert list((out / "cases" / case_id / "facts").glob("*.json"))


def test_generated_facts_validate_against_schema(tmp_path):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "8", "--seed", "11"]) == 0
    schema = json.loads(
        (REPO / "spec" / "schemas" / "grounded-fact.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    fact_files = sorted((out / "cases").rglob("facts/*.json"))
    assert fact_files
    for path in fact_files:
        fact = json.loads(path.read_text())
        errors = list(validator.iter_errors(fact))
        assert not errors, f"{path}: {[e.message for e in errors]}"
        # content addressing per spec/validate.py
        assert fact["contentHash"] == generate.content_hash(fact)
        assert fact["id"] == f"urn:duly:fact:sha256:{fact['contentHash']}"
        # honest synthetic grounding, machine assertion by the generator
        assert fact["grounding"]["kind"] == "attestation"
        assert fact["assertion"]["extractor"]["name"] == "duly-golden-generator"


def test_notice_decision_flips_across_45_day_threshold():
    template = generate.STATE_TEMPLATES["ny"]
    pack = yaml.safe_load((REPO / template["pack"]).read_text())
    expiration = dt.date(2026, 9, 1)  # mailed dates fall after 2026-01-01, so NY-NR-45 governs
    decisions = {}
    for margin in (44, 45):
        facts, eff, kn = generate.build_notice_facts(
            template,
            f"notice-ny-threshold-{margin}",
            expiration=expiration,
            margin=margin,
            nonpayment=False,
        )
        receipt = adjudicate(facts, pack, eff, kn, template["question"])
        decisions[margin] = receipt["decision"]["value"]["value"]
    assert decisions[44] is False  # 44 < 45 -> NC-NR-01 fires, non-compliant
    assert decisions[45] is True  # 45 >= 45 -> presumption of compliance survives


def test_unknown_template_is_rejected(tmp_path, capsys):
    assert generate.main(
        ["--out", str(tmp_path / "g"), "--count", "4", "--seed", "1", "--templates", "zz"]
    ) == 2
    assert "unknown template" in capsys.readouterr().err
