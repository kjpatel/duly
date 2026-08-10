"""The golden-corpus generator, exercised through the content it generates.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

`duly_assurance.generate` is toolkit code, but every one of its templates names
a teaching pack (`examples/rulepacks/...`) and draws facts in that pack's
vocabulary, so there is no run of this generator that does not read the example
content. Byte-identical regeneration, schema validity, the 45-day and
California-operative-date flips, the committed corpus's pack coverage — every
claim below is a claim about the six packs and the 351 cases, and `git rm -r
examples/` deletes the subject of all of them.

What survives the deletion is the *seam*: that templates and kinds are a
registry rather than a dispatch chain, that registering one twice is refused,
and that the corpus commands stand up against nothing. Those stay in
`assurance/tests/test_corpus_seam.py` and `assurance/tests/test_empty_corpus.py`
respectively, which is where a test about the generator's contract — as opposed
to its output — belongs.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from exampletest_helpers import GOLDEN, GOLDEN_CASES, REPO_ROOT, RULEPACKS

from duly_assurance import generate
from duly_kernel.api import adjudicate
from duly_core import schema_path


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


def test_regeneration_preserves_review_series_cases(tmp_path):
    """review-* entries are human-review golden cases (duly_review), not
    generator output; resetting the synthetic corpus must not delete them."""
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "3", "--templates", "ny"]) == 0
    review_case = out / "cases" / "review-0001"
    (review_case / "facts").mkdir(parents=True)
    (review_case / "case.yaml").write_text("id: review-0001\n")
    review_receipt = out / "receipts" / "review-0001.json"
    review_receipt.write_text("{}\n")
    assert generate.main(["--out", str(out), "--count", "4", "--seed", "3", "--templates", "ny"]) == 0
    assert (review_case / "case.yaml").read_text() == "id: review-0001\n"
    assert review_receipt.read_text() == "{}\n"
    # The synthetic series was still reset (same seed -> same ids, no strays).
    ids = sorted(p.name for p in (out / "cases").iterdir())
    assert ids == ["notice-ny-0001", "notice-ny-0002", "notice-ny-0003", "notice-ny-0004", "review-0001"]


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
        assert (REPO_ROOT / case["pack"]).is_file()
        assert list((out / "cases" / case_id / "facts").glob("*.json"))


def test_generated_facts_validate_against_schema(tmp_path):
    out = tmp_path / "g"
    assert generate.main(["--out", str(out), "--count", "8", "--seed", "11"]) == 0
    schema = json.loads(
        schema_path("grounded-fact").read_text()
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
    pack = yaml.safe_load((REPO_ROOT / template["pack"]).read_text())
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


def test_low_confidence_draws_exercise_abstention_policy(tmp_path):
    """The notice templates draw sub-floor confidences, so a generated corpus
    contains cases that abstain under the pack's abstentionPolicy (falling to
    the NC-DEF-00 presumption) and cases exactly at a floor that bind."""
    out = tmp_path / "g"
    assert generate.main(
        ["--out", str(out), "--count", "60", "--seed", "7", "--templates", "ny"]
    ) == 0
    abstained, at_floor_bound = [], []
    for path in sorted((out / "receipts").glob("*.json")):
        receipt = json.loads(path.read_text())
        entries = [a for a in receipt["abstentions"] if a["reason"] == "low_confidence"]
        if entries:
            abstained.append(receipt)
            for entry in entries:
                assert entry["confidence"]["score"] < entry["threshold"]["minConfidence"]
                assert entry["threshold"]["pack"] == "termination-notice-us-states"
        case_dir = out / "cases" / path.stem / "facts"
        scores = {
            f["attribute"]: f["confidence"]["score"]
            for f in (json.loads(p.read_text()) for p in case_dir.glob("*.json"))
        }
        if not entries and (
            scores.get("nc:noticeMailedDate") == 0.9
            or scores.get("nc:policyExpirationDate") == 0.75
        ):
            at_floor_bound.append(receipt)
    assert abstained, "corpus contains no low-confidence abstention case"
    assert at_floor_bound, "corpus contains no at-floor case that binds"
    for receipt in abstained:
        # With a needed fact excluded, the deficiency rule cannot fire and
        # the presumption of compliance decides.
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        assert "NC-DEF-00" in {r["ruleId"] for r in receipt["rulesFired"]}


def test_unknown_template_is_rejected(tmp_path, capsys):
    assert generate.main(
        ["--out", str(tmp_path / "g"), "--count", "4", "--seed", "1", "--templates", "zz"]
    ) == 2
    assert "unknown template" in capsys.readouterr().err


def test_stratified_templates_regenerate_byte_identical(tmp_path):
    """Each stratified template (ron, esign, resc, rec) is its own seeded
    draw stream: regenerating with the same seed reproduces every byte."""
    for name in ("ron", "esign", "resc", "rec"):
        a = tmp_path / name / "a"
        b = tmp_path / name / "b"
        args = ["--count", "8", "--seed", "3", "--templates", name]
        assert generate.main(["--out", str(a), *args]) == 0
        assert generate.main(["--out", str(b), *args]) == 0
        tree_a = _tree_bytes(a)
        tree_b = _tree_bytes(b)
        assert tree_a.keys() == tree_b.keys()
        for rel in tree_a:
            assert tree_a[rel] == tree_b[rel], f"{name}: {rel} differs between regenerations"


def test_strata_tables_fit_their_corpus_quota():
    """Strata cells cycle with the case counter, so a table longer than the
    template's corpus quota (25 at the default --count and weights) would
    leave its tail boundaries permanently undrawn."""
    quotas = generate.allocate(350, list(generate.STATE_TEMPLATES))
    for name, template in generate.STATE_TEMPLATES.items():
        if "strata" in template:
            assert len(template["strata"]) <= quotas[name], (
                f"{name}: {len(template['strata'])} strata exceed quota {quotas[name]}"
            )


def test_committed_corpus_covers_all_six_packs():
    """The committed golden corpus carries cases for every rule pack in the
    repo, so `impact` can see a change to any of them."""
    cases = GOLDEN_CASES
    by_prefix: dict[str, int] = {}
    packs: set[str] = set()
    questions: set[str] = set()
    for case_dir in cases.iterdir():
        prefix = case_dir.name.rsplit("-", 1)[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
        case = yaml.safe_load((case_dir / "case.yaml").read_text())
        packs.add(case["pack"])
        questions.add(case["question"])
    for prefix in ("ron", "esign", "resc", "rec"):
        assert by_prefix.get(prefix) == 25, f"{prefix}: {by_prefix.get(prefix)} cases"
    assert packs == {
        "rulepacks/termination-notice-us-states/pack.yaml",
        "rulepacks/trid-fee-tolerance-us-federal/pack.yaml",
        "rulepacks/notarization-ron-us-states/pack.yaml",
        "rulepacks/esign-closing-package/pack.yaml",
        "rulepacks/tila-rescission-us-federal/pack.yaml",
        "rulepacks/county-recording-us/pack.yaml",
    }
    # Strata pick among each pack's declared decisions, so every decision
    # attribute the four packs declare appears as a corpus question.
    assert {
        "ron:ronPermitted", "ron:notarizationCompliant",
        "pkg:signingMethod", "pkg:eSignEligible",
        "resc:rescissionApplies", "resc:rescissionDeadline", "resc:fundingPermitted",
        "rec:recordable", "rec:requiredFirstPageTopSpaceInches", "rec:sb2FeeDueUSD",
    } <= questions


def test_committed_recording_receipts_carry_low_confidence_abstentions():
    """Both sides of the pack's 0.85 floor on the measured top space: below
    it the committed receipt abstains (routed to recording-review) and the
    recordability presumption survives; at it the measurement binds and the
    deficiency stands."""
    abstained, at_floor_bound = [], []
    for path in sorted((GOLDEN / "receipts").glob("rec-*.json")):
        receipt = json.loads(path.read_text())
        entries = [a for a in receipt["abstentions"] if a["reason"] == "low_confidence"]
        for entry in entries:
            assert entry["routedTo"] == "recording-review"
            assert entry["confidence"]["score"] < entry["threshold"]["minConfidence"]
            assert entry["threshold"]["pack"] == "county-recording-us"
        if any(e["attribute"] == "rec:firstPageTopSpaceInches" for e in entries):
            abstained.append(receipt)
        case_dir = GOLDEN_CASES / path.stem / "facts"
        scores = {
            f["attribute"]: f["confidence"]["score"]
            for f in (json.loads(p.read_text()) for p in case_dir.glob("*.json"))
        }
        if not entries and scores.get("rec:firstPageTopSpaceInches") == 0.85:
            at_floor_bound.append(receipt)
    assert abstained, "no committed rec receipt abstains on the measured top space"
    for receipt in abstained:
        # The measurement is excluded, so the deficiency rule cannot fire.
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
    assert at_floor_bound, "no committed rec case binds exactly at the 0.85 floor"
    for receipt in at_floor_bound:
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
        assert "REC-TOPSPACE-01" in {r["ruleId"] for r in receipt["rulesFired"]}


def test_resc_calendar_table_matches_business_day_arithmetic():
    """Every RESC_CALENDARS date must start on a business weekday and put the
    promised Sunday/holiday shape inside its three-business-day window; a
    wrong entry would quietly weaken the corpus's coverage claims."""
    holidays = generate.federal_holidays(2026)
    expected_span = {"both": 5, "sunday": 4, "holiday": 4, "neither": 3}
    for label, dates in generate.RESC_CALENDARS.items():
        for iso in dates:
            start = dt.date.fromisoformat(iso)
            assert start.weekday() < 5 and start not in holidays, iso
            deadline = generate.add_business_days(start, 3)
            span = (deadline - start).days
            assert span == expected_span[label], f"{label} {iso}: span {span}"
            window = [start + dt.timedelta(days=i) for i in range(1, span + 1)]
            has_sunday = any(d.weekday() == 6 for d in window)
            has_holiday = any(d in holidays for d in window)
            assert has_sunday == (label in ("both", "sunday")), f"{label} {iso}"
            assert has_holiday == (label in ("both", "holiday")), f"{label} {iso}"


def test_pack_calendar_reconciles_with_generator_business_day_table():
    """The TILA pack embeds the 12 CFR 1026.2(a)(6) calendar as data; this
    module derives the same holidays from the 5 U.S.C. 6103(a) formulas. The
    two must never drift: the embedded dates must equal the statutory
    computation for every covered year, and the kernel's add_business_days
    walk must land on the same deadline as the generator's arithmetic for
    every consummation date the corpus draws."""
    from duly_kernel import expr as kexpr

    pack = yaml.safe_load(
        (RULEPACKS / "tila-rescission-us-federal" / "pack.yaml").read_text()
    )
    calendars = kexpr.parse_calendars(pack["calendars"])
    cal = calendars["tila-precise"]

    assert cal.excluded_weekdays == frozenset({6})  # Sundays only; Saturdays count
    assert cal.coverage_from == dt.date(2026, 1, 1)
    assert cal.coverage_to == dt.date(2028, 1, 1)
    for year in (2026, 2027):
        embedded = {d for d in cal.holidays if d.year == year}
        assert embedded == generate.federal_holidays(year), year
    assert {d.year for d in cal.holidays} == {2026, 2027}

    for dates in generate.RESC_CALENDARS.values():
        for iso in dates:
            start = dt.date.fromisoformat(iso)
            walked = kexpr.evaluate_str(
                f'add_business_days(date("{iso}"), 3, "tila-precise")', {}, calendars
            )
            assert isinstance(walked, kexpr.DateV)
            assert walked.value == generate.add_business_days(start, 3), iso


def test_ron_decision_flips_at_california_operative_date():
    template = generate.STATE_TEMPLATES["ron"]
    pack = yaml.safe_load((REPO_ROOT / template["pack"]).read_text())
    decisions = {}
    for as_of in (dt.date(2029, 12, 31), dt.date(2030, 1, 1)):
        facts, eff, kn = generate.build_ron_facts(
            template,
            f"ron-threshold-{as_of.isoformat()}",
            state="US-CA",
            method="RemoteOnline",
            as_of=as_of,
        )
        receipt = adjudicate(facts, pack, eff, kn, "ron:ronPermitted")
        decisions[as_of] = receipt["decision"]["value"]["value"]
    assert decisions[dt.date(2029, 12, 31)] is False  # signed law, not yet operative
    assert decisions[dt.date(2030, 1, 1)] is True  # statutory outside operative date
