"""API tests for the demo's Rule Studio (demo/rules_api.py).

These run against the *committed* rule packs rather than fixtures: the studio's
whole job is to browse and edit what is actually in `rulepacks/`, and a
projection that only works on a hand-made pack would tell us nothing. Every
test that drafts resets the session store afterwards, because drafts are
process-global by design.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest demo/tests -q
"""

from __future__ import annotations

import copy
import io
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from demo import rules_api  # noqa: E402
from demo.app import app  # noqa: E402

NOTICE = "termination-notice-us-states"
TRID = "trid-fee-tolerance-us-federal"


@pytest.fixture
def client():
    rules_api.reset_drafts()
    with TestClient(app) as c:
        yield c
    rules_api.reset_drafts()


def _detail(client, slug=NOTICE):
    res = client.get(f"/api/rules/packs/{slug}")
    assert res.status_code == 200, res.text
    return res.json()


def _draft(client, pack, slug=NOTICE):
    res = client.put(f"/api/rules/packs/{slug}/draft", json={"pack": pack})
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Discovery


def test_every_committed_pack_is_discovered(client):
    body = client.get("/api/rules/packs").json()
    slugs = {p["slug"] for p in body["packs"]}
    on_disk = {p.parent.name for p in (REPO_ROOT / "rulepacks").glob("*/pack.yaml")}
    assert slugs == on_disk
    assert body["sessionNote"]


def test_a_pack_summary_carries_what_the_rail_shows(client):
    [pack] = [p for p in client.get("/api/rules/packs").json()["packs"] if p["slug"] == NOTICE]
    assert pack["idPrefix"] == "NC"
    assert pack["ruleCount"] > 0
    assert pack["expectedCases"] > 0
    assert pack["hasAbstentionPolicy"] is True
    assert pack["committed"] is True
    assert pack["dirty"] is False


def test_golden_receipt_counts_are_reported_per_rule(client):
    detail = _detail(client)
    by_id = {r["id"]: r["goldenReceipts"] for r in detail["rules"]}
    # Rule ids are permanent precisely because receipts already cite them;
    # the studio shows the count so deleting one is an informed act.
    assert by_id["NY-NR-45"] > 0
    assert sum(by_id.values()) > 0


# ---------------------------------------------------------------------------
# The decision-table projection


def test_rules_are_grouped_into_one_table_per_concluded_attribute(client):
    detail = _detail(client)
    attributes = {t["attribute"] for t in detail["tables"]}
    concluded = {r["then"]["attribute"] for r in detail["rules"]}
    assert attributes == concluded


def test_a_single_input_guard_lands_in_that_input_s_cell(client):
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "nc:requiredMinimumNoticeDays"]
    [row] = [r for r in table["rows"] if r["ruleId"] == "NY-NR-45"]
    cells = {c["column"]: c for c in row["cells"]}
    assert cells["state"]["conditions"] == ['state == "US-NY"']
    assert cells["noticeType"]["conditions"] == ['noticeType == "Nonrenewal"']
    assert row["cross"] == []


def test_a_multi_input_guard_is_named_as_one_the_grid_cannot_hold(client):
    """`days_between(mailed, expiration) < minDays` relates three bindings, so
    no column owns it. The projection says so rather than picking one."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "nc:noticeCompliant"]
    [row] = [r for r in table["rows"] if r["ruleId"] == "NC-NR-01"]
    assert row["cross"] == ["days_between(mailed, expiration) < minDays"]
    assert all(not c["conditions"] for c in row["cells"])


def test_unbound_is_distinguished_from_bound_and_unconstrained(client):
    """The DMN `-` cell removes the *binding*, not just the condition. A rule
    that never binds an input does not require the fact; one that binds it
    without constraining it does. Conflating them changes which cases a rule
    reaches."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "nc:noticeCompliant"]
    rows = {r["ruleId"]: r for r in table["rows"]}
    default_cells = {c["column"]: c for c in rows["NC-DEF-00"]["cells"]}
    deficiency_cells = {c["column"]: c for c in rows["NC-NR-01"]["cells"]}
    assert default_cells["mailed"]["bound"] is False       # not required at all
    assert deficiency_cells["mailed"]["bound"] is True     # required, unconstrained
    assert deficiency_cells["mailed"]["conditions"] == []


def test_entity_type_bindings_are_the_subject_not_a_column(client):
    detail = _detail(client)
    for table in detail["tables"]:
        assert all(c["kind"] != "entityType" for c in table["columns"])
    [table] = [t for t in detail["tables"] if t["attribute"] == "nc:noticeCompliant"]
    assert table["entityTypes"] == ["nc:TerminationNotice"]


def test_hit_policy_reflects_the_priority_structure(client):
    trid = _detail(client, TRID)
    by_attr = {t["attribute"]: t for t in trid["tables"]}
    assert by_attr["trid:toleranceCategory"]["hitPolicy"] == "UNIQUE"
    assert by_attr["trid:toleranceCureAmount"]["hitPolicy"] == "PRIORITY"


def test_cell_indices_point_back_into_the_rule_s_when_list(client):
    """Cells carry their `when` positions so a grid edit rewrites exactly
    those entries — the reason a one-cell change is a two-line diff."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "nc:requiredMinimumNoticeDays"]
    [row] = [r for r in table["rows"] if r["ruleId"] == "NY-NR-45"]
    rule = next(r for r in detail["pack"]["rules"] if r["id"] == "NY-NR-45")
    for cell in row["cells"]:
        for position, text in zip(cell["indices"], cell["conditions"]):
            assert rule["when"][position] == text


# ---------------------------------------------------------------------------
# Drafting


def test_a_draft_never_touches_the_file_on_disk(client):
    path = REPO_ROOT / "rulepacks" / NOTICE / "pack.yaml"
    before = path.read_bytes()
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    body = _draft(client, pack)
    assert body["dirty"] is True
    assert path.read_bytes() == before


def test_the_committed_pack_comes_back_after_discarding(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    _draft(client, pack)
    client.delete(f"/api/rules/packs/{NOTICE}/draft")
    detail = _detail(client)
    assert detail["dirty"] is False
    assert detail["yaml"] == (REPO_ROOT / "rulepacks" / NOTICE / "pack.yaml").read_text()


def test_a_structured_edit_does_not_lose_a_top_level_key(client):
    """The failure this guards against is silent: an `abstentionPolicy` lost on
    re-emission produces a draft that validates, adjudicates, and answers
    differently."""
    detail = _detail(client)
    body = _draft(client, copy.deepcopy(detail["pack"]))
    assert body["pack"]["abstentionPolicy"] == detail["pack"]["abstentionPolicy"]
    assert body["abstentionPolicy"]["attributes"]["nc:noticeMailedDate"] == 0.9


def test_an_invalid_draft_is_kept_and_reported_not_rejected(client):
    """An author mid-edit has an invalid pack most of the time. Discarding the
    text at every intermediate state would make the studio unusable."""
    pack = copy.deepcopy(_detail(client)["pack"])
    pack["rules"][1]["id"] = pack["rules"][0]["id"]  # duplicate id
    body = _draft(client, pack)
    assert body["dirty"] is True
    assert body["validation"]["ok"] is False
    assert body["validation"]["error"]


def test_unparseable_yaml_source_is_refused_before_it_is_stored(client):
    res = client.put(f"/api/rules/packs/{NOTICE}/draft", json={"yaml": "pack: [unclosed"})
    assert res.status_code == 422
    assert _detail(client)["dirty"] is False


def test_the_semantic_diff_isolates_the_change_the_file_diff_buries(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    diff = _draft(client, pack)["diff"]
    semantic = "".join(diff["semantic"])
    assert '-      value: { kind: decimal, expr: "45" }' in semantic
    assert '+      value: { kind: decimal, expr: "60" }' in semantic
    # The file diff is larger because a structured edit re-emits the pack and
    # drops its YAML comments — a real cost the studio shows rather than hides.
    assert len(diff["file"]) > len(diff["semantic"])


def test_a_source_edit_preserves_comments_and_produces_a_small_diff(client):
    """The source editor is the lossless path, and its diff proves it."""
    text = _detail(client)["yaml"]
    edited = text.replace('version: "2026.3.0"', 'version: "2026.4.0"', 1)
    res = client.put(f"/api/rules/packs/{NOTICE}/draft", json={"yaml": edited})
    body = res.json()
    assert "# the family every new rule id joins" in body["yaml"]
    assert len(body["diff"]["file"]) < 15


# ---------------------------------------------------------------------------
# Testing a pack


def test_declared_cases_run_green_against_every_committed_pack(client):
    for path in sorted((REPO_ROOT / "rulepacks").glob("*/pack.yaml")):
        slug = path.parent.name
        body = client.post(f"/api/rules/packs/{slug}/test/expected").json()
        assert body["failed"] == 0, (slug, body["cases"])
        assert body["passed"] == len(body["cases"])


def test_a_broken_rule_surfaces_as_a_failing_declared_case(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "1"
    _draft(client, pack)
    body = client.post(f"/api/rules/packs/{NOTICE}/test/expected").json()
    assert body["failed"] > 0
    failing = [c for c in body["cases"] if not c["ok"]]
    assert any("decision:" in f for c in failing for f in c["failures"])


def test_an_ad_hoc_case_adjudicates_and_an_override_flips_it(client):
    detail = _detail(client)
    factset = next(f for f in detail["factSets"] if f["factsPath"] == "starters/notice-ny/facts")
    request = {
        "factsPath": factset["factsPath"],
        "asOfEffective": "2026-07-25",
        "attribute": "nc:noticeCompliant",
        "overrides": {},
    }
    before = client.post(f"/api/rules/packs/{NOTICE}/test/case", json=request).json()
    assert before["decision"]["value"] == {"kind": "boolean", "value": False}
    assert {r["ruleId"] for r in before["rulesFired"]} == {"NC-NR-01", "NY-NR-45"}

    request["overrides"] = {"nc:noticeMailedDate": "2026-01-01"}
    after = client.post(f"/api/rules/packs/{NOTICE}/test/case", json=request).json()
    assert after["decision"]["value"] == {"kind": "boolean", "value": True}
    assert after["applied"] == [
        {"attribute": "nc:noticeMailedDate", "value": {"kind": "date", "value": "2026-01-01"}}
    ]


def test_an_ad_hoc_case_compares_the_draft_against_the_committed_pack(client):
    # 38 days of notice were given. Dropping the NY minimum to 1 makes the
    # same case compliant, so the draft and the committed pack disagree.
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "1"
    _draft(client, pack)
    body = client.post(
        f"/api/rules/packs/{NOTICE}/test/case",
        json={
            "factsPath": "starters/notice-ny/facts",
            "asOfEffective": "2026-07-25",
            "attribute": "nc:noticeCompliant",
            "overrides": {},
        },
    ).json()
    assert body["baseline"] is not None
    assert body["changed"] is True
    assert body["baseline"]["value"] == {"kind": "boolean", "value": False}
    assert body["decision"]["value"] == {"kind": "boolean", "value": True}


def test_an_override_of_an_attribute_with_no_live_fact_is_refused(client):
    res = client.post(
        f"/api/rules/packs/{NOTICE}/test/case",
        json={
            "factsPath": "starters/notice-ny/facts",
            "asOfEffective": "2026-07-25",
            "attribute": "nc:noticeCompliant",
            "overrides": {"nc:notAThing": "7"},
        },
    )
    assert res.status_code == 422
    assert "no live fact" in res.json()["detail"]


def test_a_facts_path_cannot_escape_the_repository(client):
    res = client.post(
        f"/api/rules/packs/{NOTICE}/test/case",
        json={
            "factsPath": "../../../etc",
            "asOfEffective": "2026-07-25",
            "attribute": "nc:noticeCompliant",
            "overrides": {},
        },
    )
    assert res.status_code == 422


def test_impact_reports_the_flip_a_declared_case_suite_misses(client):
    """The point of running both: the notice pack's declared cases still pass
    under a 45→60 change, and the corpus finds a decision that moves. Declared
    outcomes catch a pack that breaks; only the corpus catches one whose
    meaning moved."""
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    _draft(client, pack)

    declared = client.post(f"/api/rules/packs/{NOTICE}/test/expected").json()
    assert declared["failed"] == 0

    impact = client.post(f"/api/rules/packs/{NOTICE}/impact").json()
    assert impact["flipCount"] == 1
    assert impact["flips"][0]["caseId"] == "notice-ny-0048"
    assert impact["packCases"] > 0


def test_impact_on_an_unedited_pack_flips_nothing(client):
    body = client.post(f"/api/rules/packs/{NOTICE}/impact").json()
    assert body["flipCount"] == 0
    assert body["reasoningChangeCount"] == 0


def test_impact_refuses_a_pack_with_no_committed_side(client):
    client.post(
        "/api/rules/packs",
        json={"slug": "studio-scratch", "name": "studio scratch", "idPrefix": "SCR"},
    )
    res = client.post("/api/rules/packs/studio-scratch/impact")
    assert res.status_code == 409


def test_impact_refuses_a_draft_the_kernel_will_not_load(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    pack["rules"][1]["id"] = pack["rules"][0]["id"]
    _draft(client, pack)
    res = client.post(f"/api/rules/packs/{NOTICE}/impact")
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# DMN


def test_the_committed_dmn_example_compiles_and_compiling_examples_come_first(client):
    examples = client.get("/api/rules/dmn/examples").json()["examples"]
    assert examples[0]["refusal"] is False
    assert any(e["refusal"] for e in examples)

    body = client.post(
        "/api/rules/dmn/compile", json={"path": "dmn/examples/trid-fee-tolerance.dmn"}
    ).json()
    assert body["ok"] is True
    assert body["ruleCount"] == 3
    assert yaml.safe_load(body["yaml"]) == body["pack"]
    assert body["tables"]


@pytest.mark.parametrize(
    "name", sorted(p.stem for p in (REPO_ROOT / "dmn" / "examples" / "refusals").glob("*.dmn"))
)
def test_every_refusal_example_is_reported_not_raised(client, name):
    """A refusal is a result, not a 500: it names the decision, the row and
    the cell, and it is what the import panel exists to show."""
    body = client.post(
        "/api/rules/dmn/compile", json={"path": f"dmn/examples/refusals/{name}.dmn"}
    ).json()
    assert body["ok"] is False
    assert body["error"]


def test_only_committed_dmn_examples_load_by_path(client):
    res = client.post("/api/rules/dmn/compile", json={"path": "rulepacks/../../etc/passwd"})
    assert res.status_code == 422


def test_an_adopted_dmn_pack_is_a_pack_like_any_other(client):
    body = client.post(
        "/api/rules/dmn/adopt",
        json={"slug": "studio-dmn", "path": "dmn/examples/trid-fee-tolerance.dmn"},
    ).json()
    assert body["validation"]["ok"] is True
    assert body["committed"] is False
    assert body["dirty"] is True
    assert len(body["tables"]) == 2


def test_adopting_a_refused_dmn_creates_nothing(client):
    res = client.post(
        "/api/rules/dmn/adopt",
        json={"slug": "studio-bad", "path": "dmn/examples/refusals/uncited-row.dmn"},
    )
    assert res.status_code == 422
    assert client.get("/api/rules/packs/studio-bad").status_code == 404


# ---------------------------------------------------------------------------
# Creating and exporting


def test_a_new_pack_skeleton_validates_out_of_the_box(client):
    body = client.post(
        "/api/rules/packs",
        json={"slug": "studio-new", "name": "studio new", "idPrefix": "SNW"},
    ).json()
    assert body["validation"]["ok"] is True
    assert body["idPrefix"] == "SNW"
    assert body["committed"] is False
    assert "TODO(verify)" in body["yaml"]


def test_a_new_pack_cannot_shadow_a_committed_one(client):
    res = client.post(
        "/api/rules/packs", json={"slug": NOTICE, "name": "shadow", "idPrefix": "SHD"}
    )
    assert res.status_code == 409


def test_the_bundle_carries_the_steps_that_are_not_automatic(client):
    client.post(
        "/api/rules/packs",
        json={"slug": "studio-bundle", "name": "studio bundle", "idPrefix": "SBN"},
    )
    res = client.get("/api/rules/packs/studio-bundle/bundle")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as bundle:
        names = set(bundle.namelist())
        assert names == {
            "studio-bundle/pack.yaml",
            "studio-bundle/expected.yaml",
            "studio-bundle/NEXT-STEPS.md",
        }
        steps = bundle.read("studio-bundle/NEXT-STEPS.md").decode()
    assert "generator template" in steps
    assert "expected.yaml" in steps


def test_the_bundle_bytes_depend_only_on_the_pack(client):
    client.post(
        "/api/rules/packs",
        json={"slug": "studio-stable", "name": "studio stable", "idPrefix": "SST"},
    )
    first = client.get("/api/rules/packs/studio-stable/bundle").content
    second = client.get("/api/rules/packs/studio-stable/bundle").content
    assert first == second


def test_pack_yaml_downloads_the_effective_text(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    _draft(client, pack)
    res = client.get(f"/api/rules/packs/{NOTICE}/pack.yaml")
    assert res.status_code == 200
    assert 'expr: "60"' in res.text
    assert "attachment" in res.headers["content-disposition"]


def test_prove_degrades_honestly_without_the_solver(client):
    """Without z3 the panel must say so, not disappear and not 500."""
    body = client.post(f"/api/rules/packs/{NOTICE}/prove").json()
    if body["available"]:
        pytest.skip("z3 is installed; the solver-backed path is covered below")
    assert "z3" in body["note"]


@pytest.mark.z3
def test_prove_reports_disjointness_and_an_equivalence_witness(client):
    """Equivalence is the question editing actually raises, and the one a
    fixture list cannot answer. It must come back with the input where the two
    packs part, not merely with 'they differ'."""
    pytest.importorskip("z3")
    clean = client.post(f"/api/rules/packs/{NOTICE}/prove").json()
    assert clean["available"] is True
    assert clean["fatal"] is False
    assert clean["equivalence"] is None  # nothing to compare against yet
    assert all(p["verdict"] == "PROVED-DISJOINT" for p in clean["report"]["pairs"])

    pack = copy.deepcopy(_detail(client)["pack"])
    next(r for r in pack["rules"] if r["id"] == "NY-NR-45")["then"]["value"]["expr"] = "60"
    _draft(client, pack)

    body = client.post(f"/api/rules/packs/{NOTICE}/prove").json()
    equivalence = body["equivalence"]
    assert equivalence["onlyDraft"] == [] and equivalence["onlyCommitted"] == []
    [days] = [
        d for d in equivalence["decisions"]
        if d["attribute"] == "nc:requiredMinimumNoticeDays"
    ]
    assert days["verdict"] == "NOT-PROVED"
    assert (days["committedValue"], days["draftValue"]) == ("45", "60")
    witness = dict(tuple(pair) for pair in days["witness"])
    assert witness["nc:governingState"] == '"US-NY"'


def test_an_unknown_pack_is_a_404(client):
    assert client.get("/api/rules/packs/no-such-pack").status_code == 404


def test_the_studio_page_is_served(client):
    res = client.get("/rules")
    assert res.status_code == 200
    assert "rules.js" in res.text
