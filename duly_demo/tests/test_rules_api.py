"""API tests for the demo's Rule Studio (duly_demo/rules_api.py).

The studio is **toolkit** (M5 plan, D2): it browses and edits whatever packs a
deployment has, not any particular ones. So these run against a content root
assembled from [`fixtures/`](../../fixtures/README.md) rather than against the
teaching packs in `rulepacks/`.

That is a correction, and the reason is worth stating. This module used to say
that a projection which only works on a hand-made pack "would tell us nothing"
— which is true of a pack invented to make one assertion pass, and false of a
corpus built to exercise the projection's actual range. The real cost of
pointing here at `rulepacks/` was invisible: delete the teaching content and
`test_declared_cases_run_green_against_every_committed_pack` did not fail, it
passed *vacuously* over an empty glob, and the refusal parametrization
collected zero tests. Both read exactly like success (CLAUDE.md, "a test that
would still pass with its subject deleted").

What the fixture pack has to carry for this suite, and why each is here rather
than convenient:

* one rule carrying *both* guard shapes at once — a quoted-string equality
  that owns a cell (`category == "restricted"`) and a comparison relating two
  bindings (`score < minimum`) that no column can hold. Sharper than two rules
  with one shape each: it proves the projection separates them *within* a row;
* a *derived* input, so a table can depend on a value another rule concludes;
* two hit policies, because UNIQUE and PRIORITY compile from different priority
  structures and a suite that sees one of them proves half the mapping;
* a nested `abstentionPolicy.attributes`, because re-emission dropping a
  top-level key is silent and two scalars cannot catch a flattening;
* declared cases (`fixtures/expected.yaml`) and DMN inputs (`fixtures/dmn/`),
  neither of which existed before this suite needed them.

Every test that drafts resets the session store afterwards, because drafts are
process-global by design. The `client` fixture restores the demo modules on
teardown: roots are bound at import, so pointing them at a temp root leaks into
every later file in the directory run unless it is put back.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest duly_demo/tests -q
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

from demotest_helpers import build_content_root, reload_demo  # noqa: E402

#: The fixture pack's slug in an assembled content root — its `pack.name`,
#: because that is what a receipt's `rulePack.name` resolves to.
PACK = "duly-fixture-pack"

#: The rule whose two guards are single-input equalities, and whose third
#: relates two bindings.
EXCEPTION = "FX-EXCEPTION-01"

#: The presumption `EXCEPTION` defeats: lowest priority, binds only the entity.
DEFAULT = "FX-DEFAULT-00"

#: The effective-dated threshold in force from 2026-01-01, concluded by a rule
#: and read by another as a `derived` binding.
THRESHOLD = "FX-THRESHOLD-02"


@pytest.fixture
def content_root(tmp_path_factory) -> Path:
    """A fresh content root per test.

    Not session-scoped, unlike the receipt viewer's: the studio *writes* —
    drafts, new packs, adopted DMN — and although those live in a session store
    rather than on disk, a test that ever gains a filesystem side effect would
    otherwise leak into every later test in the file.
    """
    return build_content_root(tmp_path_factory.mktemp("content"))


@pytest.fixture
def client(content_root, monkeypatch):
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    reload_demo()

    import duly_demo.app
    import duly_demo.rules_api

    duly_demo.rules_api.reset_drafts()
    with TestClient(duly_demo.app.app) as c:
        yield c
    duly_demo.rules_api.reset_drafts()

    monkeypatch.undo()
    reload_demo()


def _detail(client, slug=PACK):
    res = client.get(f"/api/rules/packs/{slug}")
    assert res.status_code == 200, res.text
    return res.json()


def _draft(client, pack, slug=PACK):
    res = client.put(f"/api/rules/packs/{slug}/draft", json={"pack": pack})
    assert res.status_code == 200, res.text
    return res.json()


def _threshold(pack):
    """The rule the editing tests move: the 2026 minimum score.

    Editing a *derived* value is the interesting choice. It is read by two other
    rules as a `derived` binding, so a change here reaches the decision without
    appearing anywhere in the decision's own table — which is the case where
    reading the diff is not enough and running the corpus is the point.
    """
    return next(r for r in pack["rules"] if r["id"] == THRESHOLD)


#: The corpus case whose score (60) sits between the committed threshold and
#: the raised one, so exactly one decision moves. Every other fixture case
#: scores 12 or 80 and is untouched by the edit.
BOUNDARY_CASE = "fx-0006"

#: A fact set every deployment of this content root has: the declared cases and
#: the corpus both point at it.
FACTS = "golden/cases/fx-0001/facts"


# ---------------------------------------------------------------------------
# Discovery


def test_every_committed_pack_is_discovered(client, content_root):
    body = client.get("/api/rules/packs").json()
    slugs = {p["slug"] for p in body["packs"]}
    on_disk = {p.parent.name for p in (content_root / "rulepacks").glob("*/pack.yaml")}
    assert slugs == on_disk == {PACK}
    assert body["sessionNote"]


def test_a_pack_summary_carries_what_the_rail_shows(client):
    [pack] = [p for p in client.get("/api/rules/packs").json()["packs"] if p["slug"] == PACK]
    assert pack["idPrefix"] == "FX"
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
    assert by_id[THRESHOLD] > 0
    assert sum(by_id.values()) > 0
    # FX-THRESHOLD-01's window closed before every committed case, so it fires
    # in none of them. Zero is a real answer and must be reported as one — a
    # rule the corpus does not reach is exactly the rule an author is most
    # likely to delete carelessly.
    assert by_id["FX-THRESHOLD-01"] == 0


# ---------------------------------------------------------------------------
# The decision-table projection


def test_rules_are_grouped_into_one_table_per_concluded_attribute(client):
    detail = _detail(client)
    attributes = {t["attribute"] for t in detail["tables"]}
    concluded = {r["then"]["attribute"] for r in detail["rules"]}
    assert attributes == concluded


def test_a_single_input_guard_lands_in_that_input_s_cell(client):
    """One guard, one column, and the indices point back at the `when` entry."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "fx:permitted"]
    [row] = [r for r in table["rows"] if r["ruleId"] == EXCEPTION]
    cells = {c["column"]: c for c in row["cells"]}
    assert cells["category"]["conditions"] == ['category == "restricted"']
    assert cells["category"]["indices"] == [1]


def test_a_multi_input_guard_is_named_as_one_the_grid_cannot_hold(client):
    """`score < minimum` relates two bindings, so no column owns it. The
    projection says so rather than picking one.

    Same rule as the test above, on purpose: a row can hold both shapes, and
    flattening the cross guard into either column would misstate what fires.
    """
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "fx:permitted"]
    [row] = [r for r in table["rows"] if r["ruleId"] == EXCEPTION]
    assert row["cross"] == ["score < minimum"]
    # The cross guard names `score` and `minimum`; neither cell claims it.
    cells = {c["column"]: c for c in row["cells"]}
    assert cells["score"]["conditions"] == []
    assert cells["minimum"]["conditions"] == []


def test_unbound_is_distinguished_from_bound_and_unconstrained(client):
    """The DMN `-` cell removes the *binding*, not just the condition. A rule
    that never binds an input does not require the fact; one that binds it
    without constraining it does. Conflating them changes which cases a rule
    reaches."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "fx:permitted"]
    rows = {r["ruleId"]: r for r in table["rows"]}
    default_cells = {c["column"]: c for c in rows[DEFAULT]["cells"]}
    exception_cells = {c["column"]: c for c in rows[EXCEPTION]["cells"]}
    assert default_cells["score"]["bound"] is False      # not required at all
    assert exception_cells["score"]["bound"] is True     # required, unconstrained
    assert exception_cells["score"]["conditions"] == []


def test_entity_type_bindings_are_the_subject_not_a_column(client):
    detail = _detail(client)
    for table in detail["tables"]:
        assert all(c["kind"] != "entityType" for c in table["columns"])
    [table] = [t for t in detail["tables"] if t["attribute"] == "fx:permitted"]
    assert table["entityTypes"] == ["fx:Widget"]
    # A `derived` column is a column — it is an input to this table, concluded
    # by another. Collapsing it into the subject would hide the dependency the
    # studio exists to show.
    assert {c["name"]: c["kind"] for c in table["columns"]}["minimum"] == "derived"


def test_hit_policy_reflects_the_priority_structure(client):
    """Both policies from one pack: UNIQUE where the rows sit at equal priority
    and nothing depends on order, PRIORITY where an exception outranks a
    presumption. A suite that only ever saw one of them proved half the map."""
    by_attr = {t["attribute"]: t for t in _detail(client)["tables"]}
    assert by_attr["fx:requiredMinimumScore"]["hitPolicy"] == "UNIQUE"
    assert by_attr["fx:permitted"]["hitPolicy"] == "PRIORITY"


def test_cell_indices_point_back_into_the_rule_s_when_list(client):
    """Cells carry their `when` positions so a grid edit rewrites exactly
    those entries — the reason a one-cell change is a two-line diff."""
    detail = _detail(client)
    [table] = [t for t in detail["tables"] if t["attribute"] == "fx:permitted"]
    [row] = [r for r in table["rows"] if r["ruleId"] == EXCEPTION]
    rule = next(r for r in detail["pack"]["rules"] if r["id"] == EXCEPTION)
    for cell in row["cells"]:
        for position, text in zip(cell["indices"], cell["conditions"]):
            assert rule["when"][position] == text


# ---------------------------------------------------------------------------
# Drafting


def test_a_draft_never_touches_the_file_on_disk(client, content_root):
    path = content_root / "rulepacks" / PACK / "pack.yaml"
    before = path.read_bytes()
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "70"
    body = _draft(client, pack)
    assert body["dirty"] is True
    assert path.read_bytes() == before


def test_the_committed_pack_comes_back_after_discarding(client, content_root):
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "70"
    _draft(client, pack)
    client.delete(f"/api/rules/packs/{PACK}/draft")
    detail = _detail(client)
    assert detail["dirty"] is False
    assert detail["yaml"] == (content_root / "rulepacks" / PACK / "pack.yaml").read_text()


def test_a_structured_edit_does_not_lose_a_top_level_key(client):
    """The failure this guards against is silent: an `abstentionPolicy` lost on
    re-emission produces a draft that validates, adjudicates, and answers
    differently."""
    detail = _detail(client)
    body = _draft(client, copy.deepcopy(detail["pack"]))
    assert body["pack"]["abstentionPolicy"] == detail["pack"]["abstentionPolicy"]
    # The *nested* value specifically. A re-emitter that dropped or flattened
    # `attributes` would still round-trip `minConfidence` and `routeTo`, so
    # asserting only those would pass through the bug this test is named for.
    assert body["abstentionPolicy"]["attributes"]["fx:category"] == 0.95


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
    res = client.put(f"/api/rules/packs/{PACK}/draft", json={"yaml": "pack: [unclosed"})
    assert res.status_code == 422
    assert _detail(client)["dirty"] is False


def test_the_semantic_diff_isolates_the_change_the_file_diff_buries(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "70"
    diff = _draft(client, pack)["diff"]
    semantic = "".join(diff["semantic"])
    assert '-      value: { kind: decimal, value: "50" }' in semantic
    assert '+      value: { kind: decimal, value: "70" }' in semantic
    # The file diff is larger because a structured edit re-emits the pack and
    # drops its YAML comments — a real cost the studio shows rather than hides.
    assert len(diff["file"]) > len(diff["semantic"])


def test_a_source_edit_preserves_comments_and_produces_a_small_diff(client):
    """The source editor is the lossless path, and its diff proves it."""
    text = _detail(client)["yaml"]
    edited = text.replace('version: "2026.3.0"', 'version: "2026.4.0"', 1)
    assert edited != text, "the pack version moved; update this edit"
    res = client.put(f"/api/rules/packs/{PACK}/draft", json={"yaml": edited})
    body = res.json()
    # A comment from the committed file. The structured path re-emits and
    # loses every one of these; the source path is the lossless one, and this
    # is what proves the difference is real rather than claimed.
    assert "# The default presumption." in body["yaml"]
    assert len(body["diff"]["file"]) < 15


# ---------------------------------------------------------------------------
# Testing a pack


def test_declared_cases_run_green_against_every_committed_pack(client, content_root):
    """Note the `assert packs` — without it this test passed *vacuously* under
    a content root with no packs, which is the state an adopter starts in and
    the state `git rm -r examples/` produces. A green empty loop is the failure
    mode this whole conversion exists to remove."""
    packs = sorted((content_root / "rulepacks").glob("*/pack.yaml"))
    assert packs, "no packs discovered; this test would otherwise pass on nothing"
    for path in packs:
        slug = path.parent.name
        body = client.post(f"/api/rules/packs/{slug}/test/expected").json()
        assert body["failed"] == 0, (slug, body["cases"])
        assert body["passed"] == len(body["cases"])
        assert body["cases"], slug


def test_a_broken_rule_surfaces_as_a_failing_declared_case(client):
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "1"
    _draft(client, pack)
    body = client.post(f"/api/rules/packs/{PACK}/test/expected").json()
    assert body["failed"] > 0
    failing = [c for c in body["cases"] if not c["ok"]]
    assert any("decision:" in f for c in failing for f in c["failures"])


def test_an_ad_hoc_case_adjudicates_and_an_override_flips_it(client):
    detail = _detail(client)
    factset = next(f for f in detail["factSets"] if f["factsPath"] == FACTS)
    request = {
        "factsPath": factset["factsPath"],
        "asOfEffective": "2026-06-01",
        "attribute": "fx:permitted",
        "overrides": {},
    }
    before = client.post(f"/api/rules/packs/{PACK}/test/case", json=request).json()
    assert before["decision"]["value"] == {"kind": "boolean", "value": False}
    # Both chains: the kernel fires every rule whose guards hold, not only the
    # ones concluding the attribute asked about.
    assert {r["ruleId"] for r in before["rulesFired"]} == {EXCEPTION, THRESHOLD, "FX-FEE-01"}

    # Raise the score above the threshold and the exception stops firing.
    request["overrides"] = {"fx:score": "99"}
    after = client.post(f"/api/rules/packs/{PACK}/test/case", json=request).json()
    assert after["decision"]["value"] == {"kind": "boolean", "value": True}
    assert after["applied"] == [
        {"attribute": "fx:score", "value": {"kind": "decimal", "value": "99"}}
    ]


def test_an_ad_hoc_case_compares_the_draft_against_the_committed_pack(client):
    # fx-0001 scores 12. Dropping the minimum to 1 clears it, so the exception
    # stops firing and the draft and the committed pack disagree.
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "1"
    _draft(client, pack)
    body = client.post(
        f"/api/rules/packs/{PACK}/test/case",
        json={
            "factsPath": FACTS,
            "asOfEffective": "2026-06-01",
            "attribute": "fx:permitted",
            "overrides": {},
        },
    ).json()
    assert body["baseline"] is not None
    assert body["changed"] is True
    assert body["baseline"]["value"] == {"kind": "boolean", "value": False}
    assert body["decision"]["value"] == {"kind": "boolean", "value": True}


def test_an_override_of_an_attribute_with_no_live_fact_is_refused(client):
    res = client.post(
        f"/api/rules/packs/{PACK}/test/case",
        json={
            "factsPath": FACTS,
            "asOfEffective": "2026-06-01",
            "attribute": "fx:permitted",
            "overrides": {"fx:notAThing": "7"},
        },
    )
    assert res.status_code == 422
    assert "no live fact" in res.json()["detail"]


def test_a_facts_path_cannot_escape_the_repository(client):
    res = client.post(
        f"/api/rules/packs/{PACK}/test/case",
        json={
            "factsPath": "../../../etc",
            "asOfEffective": "2026-06-01",
            "attribute": "fx:permitted",
            "overrides": {},
        },
    )
    assert res.status_code == 422


def test_impact_reports_the_flip_a_declared_case_suite_misses(client):
    """The point of running both, and the reason the fixture corpus carries a
    case no declared case covers.

    Raising the threshold 50 → 70 leaves every declared outcome green: they
    score 12 (below both) and 80 (above both). One corpus case scores 60, and
    it moves. Declared outcomes catch a pack that *breaks*; only the corpus
    catches one whose *meaning* moved.
    """
    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "70"
    _draft(client, pack)

    declared = client.post(f"/api/rules/packs/{PACK}/test/expected").json()
    assert declared["failed"] == 0
    assert declared["passed"] > 0

    impact = client.post(f"/api/rules/packs/{PACK}/impact").json()
    assert impact["flipCount"] == 1
    assert impact["flips"][0]["caseId"] == BOUNDARY_CASE
    assert impact["packCases"] > 0


def test_impact_on_an_unedited_pack_flips_nothing(client):
    body = client.post(f"/api/rules/packs/{PACK}/impact").json()
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
    res = client.post(f"/api/rules/packs/{PACK}/impact")
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# DMN


def test_the_committed_dmn_example_compiles_and_compiling_examples_come_first(client):
    examples = client.get("/api/rules/dmn/examples").json()["examples"]
    assert examples[0]["refusal"] is False
    assert any(e["refusal"] for e in examples)

    body = client.post(
        "/api/rules/dmn/compile", json={"path": "dmn/widget-fee.dmn"}
    ).json()
    assert body["ok"] is True
    assert body["ruleCount"] == 4
    assert yaml.safe_load(body["yaml"]) == body["pack"]
    assert body["tables"]


def test_every_refusal_example_is_reported_not_raised(client, content_root):
    """A refusal is a result, not a 500: it names the decision, the row and
    the cell, and it is what the import panel exists to show.

    Not parametrized over the glob any more. `pytest.mark.parametrize` is
    evaluated at *collection*, so an empty directory yielded zero test cases —
    the suite reported success by having nothing to say. Looping inside the
    test, with the count asserted, makes an empty directory a failure.
    """
    names = sorted(p.stem for p in (content_root / "dmn" / "refusals").glob("*.dmn"))
    assert names, "no refusal examples found; this test would otherwise be empty"
    for name in names:
        body = client.post(
            "/api/rules/dmn/compile", json={"path": f"dmn/refusals/{name}.dmn"}
        ).json()
        assert body["ok"] is False, name
        assert body["error"], name


def test_only_committed_dmn_examples_load_by_path(client):
    res = client.post("/api/rules/dmn/compile", json={"path": "rulepacks/../../etc/passwd"})
    assert res.status_code == 422


def test_an_adopted_dmn_pack_is_a_pack_like_any_other(client):
    body = client.post(
        "/api/rules/dmn/adopt",
        json={"slug": "studio-dmn", "path": "dmn/widget-fee.dmn"},
    ).json()
    assert body["validation"]["ok"] is True
    assert body["committed"] is False
    assert body["dirty"] is True
    assert len(body["tables"]) == 2


def test_adopting_a_refused_dmn_creates_nothing(client):
    res = client.post(
        "/api/rules/dmn/adopt",
        json={"slug": "studio-bad", "path": "dmn/refusals/uncited-row.dmn"},
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
        "/api/rules/packs", json={"slug": PACK, "name": "shadow", "idPrefix": "SHD"}
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
    _threshold(pack)["then"]["value"]["value"] = "70"
    _draft(client, pack)
    res = client.get(f"/api/rules/packs/{PACK}/pack.yaml")
    assert res.status_code == 200
    assert 'value: "70"' in res.text
    assert "attachment" in res.headers["content-disposition"]


def test_prove_degrades_honestly_without_the_solver(client):
    """Without z3 the panel must say so, not disappear and not 500."""
    body = client.post(f"/api/rules/packs/{PACK}/prove").json()
    if body["available"]:
        pytest.skip("z3 is installed; the solver-backed path is covered below")
    assert "z3" in body["note"]


@pytest.mark.z3
def test_prove_reports_disjointness_and_an_equivalence_witness(client):
    """Equivalence is the question editing actually raises, and the one a
    fixture list cannot answer. It must come back with the input where the two
    packs part, not merely with 'they differ'."""
    pytest.importorskip("z3")
    clean = client.post(f"/api/rules/packs/{PACK}/prove").json()
    assert clean["available"] is True
    assert clean["fatal"] is False
    assert clean["equivalence"] is None  # nothing to compare against yet

    # The pack has one same-priority pair — the two effective-dated thresholds —
    # and the solver separates them by their windows. Asserted non-empty first,
    # because `all()` over no pairs is a green test that checked nothing.
    assert clean["report"]["pairs"]
    assert all(p["verdict"] == "PROVED-DISJOINT" for p in clean["report"]["pairs"])

    pack = copy.deepcopy(_detail(client)["pack"])
    _threshold(pack)["then"]["value"]["value"] = "70"
    _draft(client, pack)

    body = client.post(f"/api/rules/packs/{PACK}/prove").json()
    equivalence = body["equivalence"]
    assert equivalence["onlyDraft"] == [] and equivalence["onlyCommitted"] == []
    by_attr = {d["attribute"]: d for d in equivalence["decisions"]}

    minimum = by_attr["fx:requiredMinimumScore"]
    assert minimum["verdict"] == "NOT-PROVED"
    assert (minimum["committedValue"], minimum["draftValue"]) == ("50", "70")

    # The edit reaches two decisions it never mentions. `fx:requiredMinimumScore`
    # is read by the other two rules as a `derived` binding, so moving it moves
    # what they conclude — and nothing in either rule's own text changed. This
    # is the case the equivalence panel exists for: a diff a careful reader can
    # inspect in full and still misjudge.
    assert by_attr["fx:permitted"]["verdict"] == "NOT-PROVED"
    assert by_attr["fx:assessedFee"]["verdict"] == "NOT-PROVED"

    # And the witness is a real input, not a shrug: a restricted widget scoring
    # exactly the committed threshold is precisely where the two packs part.
    witness = dict(tuple(pair) for pair in by_attr["fx:permitted"]["witness"])
    assert witness["fx:score"] == "50"
    assert witness["fx:category"] == '"restricted"'


def test_an_unknown_pack_is_a_404(client):
    assert client.get("/api/rules/packs/no-such-pack").status_code == 404


def test_the_studio_page_is_served(client):
    res = client.get("/rules")
    assert res.status_code == 200
    assert "rules.js" in res.text
