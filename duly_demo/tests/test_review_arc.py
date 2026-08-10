"""API tests for the demo's store-backed scenarios and the review arc.

The arc under test is the M3 demo moment, and it is **toolkit**: extraction
runs over whatever documents a deployment's starters carry into a per-process
fact store; the scenario that opts into a `reviewArc` gets a second case with
one attribute scripted below the pack's confidence floor, so the decision
abstains and falls to the presumption; a human correction supersedes the
below-floor fact through `duly_review`; the decision re-adjudicates and flips;
and the resolution exports as a golden-case bundle that replays byte-for-byte.

None of that names a scenario, so these run against a content root assembled
from [`fixtures/`](../../fixtures/README.md) rather than against the teaching
starters in `starters/` (CLAUDE.md, "a test that would still pass with its
subject deleted"). The fixture scenario `fx-0005` carries the whole arc as
*content*: three span-grounded facts, one of them (`fx:score`) below the pack's
0.80 floor, and a `reviewArc` block that re-scripts it lower still.

Three things the conversion found, recorded here because each one is a claim
the notice-ny version was quietly making about its example rather than about
the toolkit:

* **The verdict is Yes/No, and that is pack data working.** `notice-ny`'s
  determination read "Compliant" with tone `warn` and the confidence numbers in
  its detail sentence — all of that is the *notice pack's* `phrasing:` block.
  The fixture pack gives its boolean decision no phrasing on purpose, so the
  kernel's Yes/No fallback is what a caller sees, and the confidence numbers
  live where they always did: on the abstention entry.
* **The floor here is the global one.** `fx:score` has no per-attribute floor,
  so `threshold.source` reads `default`. The per-attribute path is what
  `abstentionPolicy.attributes` exists for, and it is asserted where the pack's
  nested structure is the subject (`test_rules_api`), not here.
* **The source scenario abstains too**, which retired
  `test_other_scenarios_carry_no_abstentions` — see that test's replacement.

`test_county_recording_abstains_regardless_of_installed_extractor` has left
this file: its subject was the recording *starter*, so it now lives in
`examples/tests/test_example_review_arc.py` and is deleted with the content it
describes. `test_fixture_mode_lists_the_committed_example_honestly` STAYS, and
the difference is the whole distinction — its subject is the built-in
`spec/examples` scenario, and `spec/` is not relocating, which is why it keeps
passing under the deletion measurement.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest duly_demo/tests -q
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import duly_demo.app as demo_app  # noqa: E402
from demotest_helpers import (  # noqa: E402
    SCENARIO,
    SEEDED_REVIEW_CASE,
    build_content_root,
    reload_demo,
)

# Derived, not imported: the arc's id follows whichever scenario opts into it,
# so a fixture deployment gets its own rather than this repository's.
REVIEW_SCENARIO_ID = f"{SCENARIO}{demo_app.REVIEW_ID_SUFFIX}"

#: The fixture pack's boolean decision, and the fixture scenario's own as-of —
#: after `FX-THRESHOLD-02` takes effect, so the minimum score is 50.
REVIEW_QUESTION = "fx:permitted"
REVIEW_AS_OF = "2026-06-01"

#: The score the document actually states, which is what a reviewer reading the
#: quoted span types in. It is *below* the 2026 threshold, so restoring it as a
#: trusted human fact lets `FX-EXCEPTION-01` fire and the decision flips — the
#: same shape as confirming notice-ny's mailed date. A value above 50 would
#: clear the abstention without moving the decision, which is a weaker test.
CORRECTED_SCORE = "12"


@pytest.fixture
def content_root(tmp_path_factory) -> Path:
    """A fresh content root per test.

    Per test rather than per session: the arc *writes* (corrections, review
    resolutions, exported cases). Those live in a per-process store rather than
    on disk, but the runtime is rebuilt from this root every time, and a test
    that ever gains a filesystem side effect would otherwise leak forward.
    """
    return build_content_root(tmp_path_factory.mktemp("content"))


@pytest.fixture
def client(content_root, monkeypatch):
    """A store-backed runtime over the fixture content root.

    Three environment moves, each load-bearing. `DULY_DEMO_CONTENT` points the
    surfaces at the fixture corpus; `DULY_DEMO_FORCE_FIXTURE` must go because
    `test_api` sets it process-wide at import; and the extractor is pinned to
    the stub so the byte-identity assertions stay meaningful on machines where
    the Docling extra is installed (Docling produces its own rendition and its
    own measured confidence — correct, but not what these tests assert).

    Both sides of the yield matter. The demo binds its roots at *import*, so a
    suite that reloads on setup and not on teardown leaves every later file in
    the directory serving a temp directory that no longer exists.
    """
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    monkeypatch.setenv("DULY_DEMO_EXTRACTOR", "stub")
    reload_demo()
    demo_app._reset_runtime()

    with TestClient(demo_app.app) as c:
        yield c

    demo_app._reset_runtime()
    monkeypatch.undo()
    reload_demo()


def _adjudicate(
    client,
    scenario_id: str,
    attribute: str = REVIEW_QUESTION,
    as_of: str = REVIEW_AS_OF,
):
    res = client.post(
        "/api/adjudicate",
        json={"scenarioId": scenario_id, "attribute": attribute, "asOfEffective": as_of},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _correct(client, item_id: str, value: str = CORRECTED_SCORE, **overrides):
    body = {
        "scenarioId": REVIEW_SCENARIO_ID,
        "itemId": item_id,
        "attribute": REVIEW_QUESTION,
        "asOfEffective": REVIEW_AS_OF,
        "value": value,
        "reviewerName": "R. Queue Demo",
        "reviewerRole": "compliance-review",
    }
    body.update(overrides)
    return client.post("/api/review/correct", json=body)


# ---------------------------------------------------------------------------
# Store-backed scenario facts
# ---------------------------------------------------------------------------


def test_store_backed_scenario_facts_are_byte_identical_to_disk(client):
    """The stub reproduces a starter's committed fact set exactly, so the store
    projection the demo serves must match the disk JSON document for document
    (canonical form — key order is presentation, not content).

    Read through `duly_demo.content.CONTENT`, not through this repository's
    `starters/`: reaching past the content root would compare a store built
    from the fixtures against files the runtime never saw, and the assertion
    would be about which directory the test knows rather than about the
    pipeline.
    """
    import duly_demo.content as demo_content

    runtime = demo_app._active_runtime()
    assert runtime is not None

    scenario_dirs = [
        path
        for path in sorted(demo_content.CONTENT.starters.iterdir())
        if (path / "scenario.json").exists()
    ]
    assert scenario_dirs, "content root has no starters — nothing was compared"

    for scenario_dir in scenario_dirs:
        manifest = json.loads((scenario_dir / "scenario.json").read_text())
        disk_facts = [
            json.loads((scenario_dir / rel).read_text()) for rel in manifest["facts"]
        ]
        assert disk_facts, scenario_dir.name
        store_facts = runtime.store.as_of(
            manifest["caseId"], knowledge=demo_app._now_knowledge()
        )
        canon = lambda facts: sorted(  # noqa: E731
            json.dumps(f, sort_keys=True, separators=(",", ":")) for f in facts
        )
        assert canon(store_facts) == canon(disk_facts), scenario_dir.name


def test_scenarios_report_extraction_provenance(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = {s["id"]: s for s in res.json()}
    assert scenarios, "content root served no scenarios"

    assert REVIEW_SCENARIO_ID in scenarios
    for scenario in scenarios.values():
        extraction = scenario["extraction"]
        assert extraction["source"] == "store", scenario["id"]
        assert extraction["extractor"]["name"]
        assert extraction["extractor"]["version"]
        # The label names the extractor that produced the rendition.
        assert extraction["extractor"]["name"] in extraction["label"]
        assert scenario["review"]["available"] is True

    # The review scenario is always the scripted stub (the arc needs the
    # scripted below-floor confidence, which Docling would not reproduce).
    review = scenarios[REVIEW_SCENARIO_ID]
    assert review["extraction"]["extractor"]["name"] == "duly-demo-extractor"


# ---------------------------------------------------------------------------
# The abstention
# ---------------------------------------------------------------------------


def test_review_scenario_abstains_below_the_confidence_floor(client):
    payload = _adjudicate(client, REVIEW_SCENARIO_ID)
    assert payload["engineMode"] == "live"

    # The presumption stands, because the abstained score is out of the
    # projection and `FX-EXCEPTION-01` needs it. The wording is the kernel's
    # boolean fallback: the fixture pack gives `fx:permitted` no `phrasing:`
    # block, and inventing one in duly_demo/app.py is exactly what the pack-data
    # rule forbids. The confidence numbers live on the abstention below.
    found = payload["determination"]
    assert found["verdict"] == "Yes"
    assert found["tone"] == "pos"
    assert found["detail"] == ""

    assert len(payload["abstentions"]) == 1
    entry = payload["abstentions"][0]
    assert entry["reason"] == "low_confidence"
    assert entry["attribute"] == "fx:score"
    # Scripted by the scenario's `reviewArc` block, not by this test.
    assert entry["confidence"] == {"score": 0.55, "method": "platt"}
    assert entry["threshold"]["minConfidence"] == 0.8
    # `default`, not `attribute`: the fixture pack's per-attribute floor covers
    # fx:category, so this one is decided by the pack-wide minimum.
    assert entry["threshold"]["source"] == "default"
    assert entry["threshold"]["pack"] == "duly-fixture-pack"
    assert entry["threshold"]["packVersion"]
    assert entry["routedTo"] == "fixture-review"
    assert entry["itemId"].startswith("urn:duly:review:sha256:")
    assert entry["itemStatus"] == "open"
    # Presentation hint: FX-EXCEPTION-01 (concluding fx:permitted) binds
    # fx:score, so this question's rules do consult the abstained attribute.
    assert entry["consultedByDecision"] is True

    # The receipt itself stays verbatim — enrichment lives beside it.
    receipt_entry = payload["receipt"]["abstentions"][0]
    assert "itemId" not in receipt_entry and "itemStatus" not in receipt_entry
    assert "consultedByDecision" not in receipt_entry

    # The abstained fact links to its document span like any grounded fact.
    abstained = payload["factIndex"][entry["facts"][0]]
    assert abstained["quote"] == "Measured score: 12"
    assert abstained["documentId"]
    assert abstained["charSpan"]["end"] > abstained["charSpan"]["start"]
    assert abstained["provenance"]["kind"] == "machine"

    review = payload["review"]
    assert review["available"] is True
    assert review["calibrationPairs"] == 0
    assert review["resolved"] == []


def test_the_arc_scripts_a_separate_case_and_leaves_its_source_alone(client):
    """The scripted confidence belongs to the arc's case, not to the world.

    This replaces `test_other_scenarios_carry_no_abstentions`, whose premise
    was a property of `notice-ny` rather than of the toolkit: that starter's
    base scenario happens to be clean, so "the only abstention is the scripted
    one" held. The fixture scenario's committed `fx:score` is *already* below
    the pack floor (that is what gives it a live `low_confidence` abstention to
    browse at all), so the base case abstains too and the old assertion cannot
    be made honestly here.

    What survives is the claim the old test was really probing: `_ingest_review_case`
    re-extracts under a *separate* case id with the confidence overridden, so
    the source scenario keeps its own committed confidence, its own fact, and
    its own review item. A bug that scripted the value into the shared targets
    dict — they are the same object until `copy.deepcopy` — would show up here
    as two identical confidences.
    """
    source = _adjudicate(client, SCENARIO)
    arc = _adjudicate(client, REVIEW_SCENARIO_ID)

    (source_entry,) = source["abstentions"]
    (arc_entry,) = arc["abstentions"]
    assert source_entry["attribute"] == arc_entry["attribute"] == "fx:score"

    # The committed confidence, untouched by the arc's override.
    assert source_entry["confidence"] == {"score": 0.62, "method": "raw"}
    assert arc_entry["confidence"] == {"score": 0.55, "method": "platt"}

    # Different facts, different cases, different review items.
    assert source_entry["facts"] != arc_entry["facts"]
    assert source_entry["itemId"] != arc_entry["itemId"]
    assert source["receipt"]["caseId"] != arc["receipt"]["caseId"]


def test_consulted_attributes_is_scoped_to_the_question_and_follows_derived():
    """The `consultedByDecision` presentation hint's underlying set.

    Receipt abstentions are case-wide — the kernel filters the fact universe
    before any rule runs — so an entry can name an attribute the selected
    question's rules never consult, and the UI labels that rather than letting
    it read as a bug. The set is per-question rule reachability: direct
    `attribute:` bindings, `derived:` bindings followed transitively, and the
    decision attribute itself. The fixture content cannot exercise the
    "not consulted" branch (both fixture decisions consult the same inputs),
    which is why this pack is synthetic.
    """
    pack = {
        "rules": [
            {
                "given": {
                    "w": {"entityType": "fx:Widget"},
                    "s": {"attribute": "fx:score"},
                    "m": {"derived": "fx:minimum"},
                },
                "then": {"attribute": "fx:permitted"},
            },
            {
                "given": {"w": {"entityType": "fx:Widget"}, "b": {"attribute": "fx:baseline"}},
                "then": {"attribute": "fx:minimum"},
            },
            {
                "given": {"w": {"entityType": "fx:Widget"}, "c": {"attribute": "fx:color"}},
                "then": {"attribute": "fx:label"},
            },
        ]
    }
    consulted = demo_app._consulted_attributes(pack, "fx:permitted")
    assert "fx:score" in consulted  # direct binding
    assert "fx:baseline" in consulted  # via the derived fx:minimum
    assert "fx:permitted" in consulted  # the question's own attribute
    assert "fx:color" not in consulted  # the other decision's input

    # No pack or no decision in hand: no hint, rather than a wrong one.
    assert demo_app._consulted_attributes(None, "fx:permitted") is None
    assert demo_app._consulted_attributes(pack, None) is None


# ---------------------------------------------------------------------------
# The correction flow
# ---------------------------------------------------------------------------


def test_correction_round_trip_flips_the_decision(client):
    payload = _adjudicate(client, REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]
    assert payload["receipt"]["decision"]["value"] == {"kind": "boolean", "value": True}

    res = _correct(client, item_id)
    assert res.status_code == 200, res.text
    corrected = res.json()

    # The flip: the restored score is back in the projection, `FX-EXCEPTION-01`
    # fires over the presumption, and the abstention is gone.
    assert corrected["receipt"]["decision"]["value"] == {"kind": "boolean", "value": False}
    assert corrected["determination"]["verdict"] == "No"
    assert corrected["determination"]["tone"] == "neg"
    assert corrected["abstentions"] == []
    assert corrected["receipt"]["abstentions"] == []

    # The human fact is in the derivation with its actor.
    resolution = corrected["resolution"]
    human = corrected["factIndex"][resolution["factId"]]
    assert human["provenance"]["kind"] == "human"
    assert "reviewer:r-queue-demo" in human["provenance"]["label"]
    assert "compliance-review" in human["provenance"]["label"]
    cited = {ref["id"] for ref in corrected["receipt"]["inputFacts"]}
    assert resolution["factId"] in cited

    # The correction superseded the abstained machine fact (spec open
    # question 2 leaves *requiring* this undecided; the demo uses the form).
    assert resolution["supersededFactId"] == payload["abstentions"][0]["facts"][0]

    # Review state: resolved item, one calibration label pair.
    review = corrected["review"]
    assert len(review["resolved"]) == 1
    resolved = review["resolved"][0]
    assert resolved["itemId"] == item_id
    assert resolved["actor"] == {"id": "reviewer:r-queue-demo", "role": "compliance-review"}
    assert resolved["value"] == {"kind": "decimal", "value": CORRECTED_SCORE}
    assert review["calibrationPairs"] == 1
    assert review["calibrationNote"]

    # Re-adjudicating fresh shows the corrected world: no abstention entry.
    again = _adjudicate(client, REVIEW_SCENARIO_ID)
    assert again["abstentions"] == []
    assert again["determination"]["verdict"] == "No"

    # Terminal item: a second correction is refused.
    assert _correct(client, item_id).status_code == 409


def test_correction_rejects_a_malformed_value_and_leaves_the_item_open(client):
    payload = _adjudicate(client, REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    # The abstained attribute is a decimal, so the value is parsed as one; the
    # refusal names the kind rather than echoing the input back as a fact.
    res = _correct(client, item_id, value="not-a-number")
    assert res.status_code == 422
    assert "decimal" in res.json()["detail"]

    res = _correct(client, item_id, reviewerName="   ")
    assert res.status_code == 422

    # Nothing resolved: the abstention is still there and still open.
    again = _adjudicate(client, REVIEW_SCENARIO_ID)
    assert again["abstentions"][0]["itemStatus"] == "open"
    assert again["review"]["calibrationPairs"] == 0


def test_unknown_item_and_wrong_scenario_are_refused(client):
    payload = _adjudicate(client, REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    assert _correct(client, "urn:duly:review:sha256:" + "0" * 64).status_code == 404
    # The item belongs to the arc's case, not to the scenario it was scripted
    # from — which has an open item of its own, on the same attribute.
    assert _correct(client, item_id, scenarioId=SCENARIO).status_code == 409


# ---------------------------------------------------------------------------
# Fixture mode degrades honestly
# ---------------------------------------------------------------------------


def test_fixture_mode_disables_the_review_flow_honestly(content_root, monkeypatch):
    """Without the session store there is no arc, and both review endpoints say
    so with a 503 rather than a 500 or an empty success.

    The scenario list holds exactly the demo's built-in `spec/examples`
    scenario — which ships with the demo and survives every content root
    since the examples/ move — and nothing else: the arc needs the session
    store, so no review scenario may appear, and the built-in's own review
    affordance must be honestly unavailable.
    """
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    monkeypatch.setenv("DULY_DEMO_FORCE_FIXTURE", "1")
    reload_demo()
    demo_app._reset_runtime()

    with TestClient(demo_app.app) as fixture_client:
        res = fixture_client.get("/api/scenarios")
        assert res.status_code == 200
        scenarios = res.json()
        [built_in] = scenarios  # the built-in only; the arc needs the store
        assert built_in["extraction"]["source"] == "fixture"
        assert built_in["review"]["available"] is False
        assert not any(
            s["id"].endswith(demo_app.REVIEW_ID_SUFFIX) for s in scenarios
        )

        refused = _correct(
            fixture_client,
            "urn:duly:review:sha256:" + "0" * 64,
            scenarioId=SCENARIO,
        )
        assert refused.status_code == 503
        assert "fixture" in refused.json()["detail"].lower()

        golden = fixture_client.get("/api/review/golden-case", params={"itemId": "urn:x"})
        assert golden.status_code == 503

    demo_app._reset_runtime()
    monkeypatch.undo()
    reload_demo()


def test_fixture_mode_lists_the_committed_example_honestly(monkeypatch):
    """COMMITTED CONTENT that does not move: the built-in fixture scenario is
    served from `spec/examples`, which stays when `examples/` is deleted — this
    test survives the deletion gate on purpose. The built-in fixture
    scenario is a committed receipt served without an extraction run, and it
    must say both things — no store-backed scenario, no review affordance, and
    a label that does not pretend an extractor ran."""
    monkeypatch.setenv("DULY_DEMO_FORCE_FIXTURE", "1")
    reload_demo()
    demo_app._reset_runtime()

    with TestClient(demo_app.app) as fixture_client:
        scenarios = fixture_client.get("/api/scenarios").json()
        assert scenarios
        # Not one of them is the arc: it exists only in the session store.
        assert not any(s["id"].endswith(demo_app.REVIEW_ID_SUFFIX) for s in scenarios)

        fixture = scenarios[0]
        assert fixture["review"]["available"] is False
        assert fixture["review"]["note"]
        assert fixture["extraction"]["source"] == "fixture"
        assert "no extraction run" in fixture["extraction"]["label"]

        payload = _adjudicate(
            fixture_client,
            fixture["id"],
            attribute=fixture["questions"][0]["attribute"],
            as_of=fixture["defaultAsOf"],
        )
        assert payload["review"]["available"] is False
        assert payload["review"]["note"]

    demo_app._reset_runtime()
    monkeypatch.undo()
    reload_demo()


# ---------------------------------------------------------------------------
# Golden export
# ---------------------------------------------------------------------------


def test_golden_export_bundle_replays_byte_for_byte(client, content_root):
    payload = _adjudicate(client, REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    # Export before resolution is refused.
    early = client.get("/api/review/golden-case", params={"itemId": item_id})
    assert early.status_code == 409

    assert _correct(client, item_id).status_code == 200

    res = client.get("/api/review/golden-case", params={"itemId": item_id})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    bundle = zipfile.ZipFile(io.BytesIO(res.content))
    names = bundle.namelist()
    case_yaml_name = next(n for n in names if n.endswith("case.yaml"))
    case_id = case_yaml_name.split("/")[1]
    # A fresh id from the review-NNNN series, never one the corpus already
    # holds — `build_content_root` seeds `review-0001` precisely so this
    # assertion has a collision to survive rather than a free slot to take.
    assert case_id.startswith("review-") and case_id != SEEDED_REVIEW_CASE
    assert f"receipts/{case_id}.json" in names

    # One file per *live* fact, which is the scenario's three attributes — the
    # human correction replaces the machine score rather than joining it.
    fact_names = [n for n in names if f"cases/{case_id}/facts/" in n]
    assert len(fact_names) == 3
    facts = [json.loads(bundle.read(n)) for n in fact_names]
    (score,) = [f for f in facts if f["attribute"] == "fx:score"]
    assert score["assertion"]["kind"] == "human"
    assert score["value"] == {"kind": "decimal", "value": CORRECTED_SCORE}

    # Replay: adjudicate the bundle's facts with the pinned pack at the
    # bundle's as-of pair and byte-compare against the bundled receipt. The
    # pack path is resolved against the *content root* — it is where the case
    # says the pack is, and this repository is only one possible answer.
    case = yaml.safe_load(bundle.read(case_yaml_name))
    from duly_kernel.api import adjudicate  # noqa: PLC0415

    pack_path = content_root / case["pack"]
    assert pack_path.is_file(), case["pack"]
    pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    fresh = adjudicate(
        facts, pack, case["asOfEffective"], case["asOfKnowledge"], case["question"]
    )
    fresh_bytes = (json.dumps(fresh, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    assert fresh_bytes == bundle.read(f"receipts/{case_id}.json")
    assert fresh["decision"]["value"] == {"kind": "boolean", "value": False}
    assert fresh["abstentions"] == []  # the superseded fact is out of the projection
