"""Tests for `python -m duly_assurance impact` (assurance/duly_assurance/impact.py).

These tests use their own fixture mini-corpus (assurance/tests/fixtures/
mini-golden) laid out exactly like golden/ (cases/<id>/case.yaml,
cases/<id>/facts/*.json, receipts/<id>.json). Baseline receipts are generated
in-test with duly_kernel.api so they always match the current kernel; pack
changes are simulated by copying kernel/tests/fixtures/ny-pack.yaml to a temp
dir, mutating it, and pointing a copied case.yaml at the mutated copy.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import yaml

from duly_assurance.impact import main
from duly_kernel.api import adjudicate
from duly_kernel.ir import load_pack

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mini-golden"
NY_PACK = REPO_ROOT / "kernel" / "tests" / "fixtures" / "ny-pack.yaml"
DECISION_ATTRIBUTE = "nc:noticeCompliant"

ALL_CASES = [
    "notice-001-ny-late",      # 38 days: noncompliant under the 45-day rule
    "notice-002-ny-margin",    # 53 days: compliant under 45, flips under 60
    "notice-003-ny-early",     # 92 days: compliant under 45 and 60
    "notice-004-tx-default",   # non-NY: default rule only
]


# ---------------------------------------------------------------------------
# Corpus construction helpers


def build_corpus(tmp_path: Path, pack_for: dict[str, Path] | None = None) -> Path:
    """Copy the fixture cases into a temp golden corpus.

    Each copied case.yaml gets an absolute pack path (`pack_for[case_id]` if
    given, else the pristine ny-pack). Baseline receipts are adjudicated under
    the PRISTINE pack, so the committed-golden baseline always reflects the
    original rules.
    """
    pack_for = pack_for or {}
    corpus = tmp_path / "golden"
    receipts_dir = corpus / "receipts"
    receipts_dir.mkdir(parents=True)
    baseline_pack = load_pack(NY_PACK)

    for case_id in ALL_CASES:
        src = FIXTURES / "cases" / case_id
        dst = corpus / "cases" / case_id
        shutil.copytree(src, dst)

        case = yaml.safe_load((dst / "case.yaml").read_text())
        case["pack"] = str(pack_for.get(case_id, NY_PACK))
        (dst / "case.yaml").write_text(yaml.safe_dump(case, sort_keys=False))

        facts = [
            json.loads(p.read_text()) for p in sorted((dst / "facts").glob("*.json"))
        ]
        receipt = adjudicate(
            facts,
            baseline_pack,
            case["asOfEffective"],
            case["asOfKnowledge"],
            DECISION_ATTRIBUTE,
        )
        (receipts_dir / f"{case_id}.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
        )
    return corpus


def _load_ny_pack_dict() -> dict:
    with open(NY_PACK, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_pack(tmp_path: Path, pack: dict, name: str) -> Path:
    pack_dir = tmp_path / "packs" / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    path = pack_dir / "pack.yaml"
    path.write_text(yaml.safe_dump(pack, sort_keys=False))
    return path


def make_pack_60_days(tmp_path: Path) -> Path:
    """The 45-day minimum-notice expr changed to 60."""
    pack = copy.deepcopy(_load_ny_pack_dict())
    rule = next(r for r in pack["rules"] if r["id"] == "NY-NR-45")
    assert rule["then"]["value"]["expr"] == "45"
    rule["then"]["value"]["expr"] = "60"
    return _write_pack(tmp_path, pack, "ny-60")


def make_pack_renamed_rule(tmp_path: Path) -> Path:
    """NY-NR-45 renamed: identical conclusions, different rulesFired ids."""
    pack = copy.deepcopy(_load_ny_pack_dict())
    rule = next(r for r in pack["rules"] if r["id"] == "NY-NR-45")
    rule["id"] = "NY-NR-45-RENAMED"
    return _write_pack(tmp_path, pack, "ny-renamed")


def make_pack_without_default(tmp_path: Path) -> Path:
    """NC-DEF-00 removed: compliant cases have no surviving conclusion."""
    pack = copy.deepcopy(_load_ny_pack_dict())
    pack["rules"] = [r for r in pack["rules"] if r["id"] != "NC-DEF-00"]
    for r in pack["rules"]:
        if "overrides" in r:
            r["overrides"] = [o for o in r["overrides"] if o != "NC-DEF-00"]
            if not r["overrides"]:
                del r["overrides"]
    return _write_pack(tmp_path, pack, "ny-no-default")


def run_impact(corpus: Path, *extra: str) -> int:
    return main(["--golden", str(corpus), *extra])


# ---------------------------------------------------------------------------
# Tests


def test_zero_flip_run(tmp_path, capsys):
    corpus = build_corpus(tmp_path)
    out_json = tmp_path / "impact.json"
    rc = run_impact(corpus, "--json", str(out_json))
    assert rc == 0

    stdout = capsys.readouterr().out
    assert "0 of 4 decisions flip; 0 reasoning-only changes" in stdout

    report = json.loads(out_json.read_text())
    assert report["totalCases"] == 4
    assert report["flips"] == []
    assert report["reasoningChanges"] == []
    assert report["unchanged"] == ALL_CASES


def test_flip_detected_under_modified_pack(tmp_path, capsys):
    pack60 = make_pack_60_days(tmp_path)
    corpus = build_corpus(tmp_path, pack_for={"notice-002-ny-margin": pack60})
    out_json = tmp_path / "impact.json"
    rc = run_impact(corpus, "--json", str(out_json))
    assert rc == 0

    stdout = capsys.readouterr().out
    assert "1 of 4 decisions flip; 0 reasoning-only changes" in stdout

    report = json.loads(out_json.read_text())
    assert report["flipCount"] == 1
    [flip] = report["flips"]
    assert flip["caseId"] == "notice-002-ny-margin"
    assert flip["question"] == "Was this termination notice compliant?"
    assert flip["before"]["value"] == {"kind": "boolean", "value": True}
    assert flip["after"]["value"] == {"kind": "boolean", "value": False}
    assert flip["before"]["valueDisplay"] == "true"
    assert flip["after"]["valueDisplay"] == "false"
    # after side shows the fired rules including the noncompliance rule
    after_ids = [r["ruleId"] for r in flip["after"]["rulesFired"]]
    assert "NC-NR-01" in after_ids
    # cases still pointing at the pristine pack are untouched
    assert report["unchanged"] == [
        "notice-001-ny-late",
        "notice-003-ny-early",
        "notice-004-tx-default",
    ]


def test_reasoning_only_change_detected(tmp_path, capsys):
    renamed = make_pack_renamed_rule(tmp_path)
    corpus = build_corpus(
        tmp_path, pack_for={case_id: renamed for case_id in ALL_CASES}
    )
    out_json = tmp_path / "impact.json"
    rc = run_impact(corpus, "--json", str(out_json))
    assert rc == 0

    stdout = capsys.readouterr().out
    assert "0 of 4 decisions flip; 3 reasoning-only changes" in stdout

    report = json.loads(out_json.read_text())
    assert report["flips"] == []
    changed_ids = [c["caseId"] for c in report["reasoningChanges"]]
    # every NY case fires the (renamed) minimum-days rule; the TX case only
    # ever fires the default rule so its reasoning is untouched
    assert changed_ids == [
        "notice-001-ny-late",
        "notice-002-ny-margin",
        "notice-003-ny-early",
    ]
    assert report["unchanged"] == ["notice-004-tx-default"]

    change = report["reasoningChanges"][0]
    assert change["before"]["value"] == change["after"]["value"]
    before_ids = {r["ruleId"] for r in change["before"]["rulesFired"]}
    after_ids = {r["ruleId"] for r in change["after"]["rulesFired"]}
    assert "NY-NR-45" in before_ids
    assert "NY-NR-45-RENAMED" in after_ids


def test_adjudication_error_reported_as_no_decision_flip(tmp_path, capsys):
    no_default = make_pack_without_default(tmp_path)
    corpus = build_corpus(
        tmp_path, pack_for={"notice-003-ny-early": no_default}
    )
    out_json = tmp_path / "impact.json"
    out_md = tmp_path / "impact.md"
    rc = run_impact(corpus, "--json", str(out_json), "--markdown", str(out_md))
    assert rc == 0  # analysis completed; impact reports, it does not gate

    stdout = capsys.readouterr().out
    assert "1 of 4 decisions flip" in stdout
    assert "no decision" in stdout

    report = json.loads(out_json.read_text())
    [flip] = report["flips"]
    assert flip["caseId"] == "notice-003-ny-early"
    assert flip["before"]["value"] == {"kind": "boolean", "value": True}
    assert flip["after"]["value"] is None
    assert flip["after"]["valueDisplay"] == "no decision"
    assert flip["after"]["error"].startswith("AdjudicationError:")

    md = out_md.read_text()
    assert "no decision" in md


def test_markdown_output_summary_and_table(tmp_path, capsys):
    pack60 = make_pack_60_days(tmp_path)
    corpus = build_corpus(tmp_path, pack_for={"notice-002-ny-margin": pack60})
    out_md = tmp_path / "impact.md"
    rc = run_impact(corpus, "--markdown", str(out_md))
    assert rc == 0
    capsys.readouterr()

    md = out_md.read_text()
    # sticky-comment marker for CI comment upsert
    assert md.startswith("<!-- duly-impact -->")
    # summary line
    assert "1 of 4 decisions flip; 0 reasoning-only changes" in md
    # flipped-cases table: header + the flipped row with before -> after values
    assert "| Case | Question | Before | After |" in md
    assert (
        "| `notice-002-ny-margin` | Was this termination notice compliant? "
        "| `true` | `false` |" in md
    )
    # detailed excerpt shows fired rules and defeated sets for each side
    assert "#### `notice-002-ny-margin`" in md
    assert "**Before**" in md and "**After**" in md
    assert "`NC-NR-01` (defeated: NC-DEF-00)" in md
    # reasoning-changes count is always present
    assert "**Reasoning-only changes**: 0" in md


def test_output_is_deterministic(tmp_path, capsys):
    pack60 = make_pack_60_days(tmp_path)
    corpus = build_corpus(tmp_path, pack_for={"notice-002-ny-margin": pack60})
    outputs = []
    for i in range(2):
        out_json = tmp_path / f"impact-{i}.json"
        out_md = tmp_path / f"impact-{i}.md"
        assert run_impact(corpus, "--json", str(out_json), "--markdown", str(out_md)) == 0
        outputs.append((out_json.read_bytes(), out_md.read_bytes()))
    capsys.readouterr()
    assert outputs[0] == outputs[1]


def test_missing_corpus_is_operational_error(tmp_path, capsys):
    rc = main(["--golden", str(tmp_path / "does-not-exist")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "error" in captured.err


def test_unloadable_pack_is_operational_error(tmp_path, capsys):
    corpus = build_corpus(tmp_path)
    case_yaml = corpus / "cases" / "notice-001-ny-late" / "case.yaml"
    case = yaml.safe_load(case_yaml.read_text())
    case["pack"] = str(tmp_path / "nope" / "pack.yaml")
    case_yaml.write_text(yaml.safe_dump(case, sort_keys=False))

    rc = main(["--golden", str(corpus)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "pack not found" in captured.err
