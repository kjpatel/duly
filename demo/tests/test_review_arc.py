"""API tests for the demo's store-backed scenarios and the review arc.

The arc under test is the M3 demo moment: extraction runs over the committed
starter documents into a per-process fact store; the review scenario's mailed
date lands below the notice pack's 0.9 attribute floor and abstains (the
decision falls to the compliance presumption); a human correction supersedes
the below-floor fact through duly_review; the decision re-adjudicates and
flips; and the resolution exports as a golden-case bundle that replays
byte-for-byte.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest demo/tests -q
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

import demo.app as demo_app  # noqa: E402
from demo.app import REVIEW_SCENARIO_ID, app  # noqa: E402

client = TestClient(app)

REVIEW_QUESTION = "nc:noticeCompliant"
REVIEW_AS_OF = "2026-07-25"


@pytest.fixture
def live_runtime(monkeypatch):
    """A fresh store-backed runtime with the extractor pinned to the stub.

    The stub pin keeps the byte-identity assertions meaningful on machines
    where the Docling extra is installed (Docling produces a different
    rendition, hence different facts — correct, but not what these tests
    assert). Reset on teardown so other test modules rebuild lazily.
    """
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    monkeypatch.setenv("DULY_DEMO_EXTRACTOR", "stub")
    demo_app._reset_runtime()
    yield
    demo_app._reset_runtime()


def _adjudicate(scenario_id: str, attribute: str = REVIEW_QUESTION, as_of: str = REVIEW_AS_OF):
    res = client.post(
        "/api/adjudicate",
        json={"scenarioId": scenario_id, "attribute": attribute, "asOfEffective": as_of},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _correct(item_id: str, value: str = "2026-07-25", **overrides):
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


def test_store_backed_scenario_facts_are_byte_identical_to_disk(live_runtime):
    """The stub reproduces the committed starter fact sets exactly, so the
    store projection the demo serves must match the disk JSON document for
    document (canonical form — key order is presentation, not content)."""
    runtime = demo_app._active_runtime()
    assert runtime is not None

    for scenario_id in ("notice-ny", "trid"):
        scenario_dir = REPO_ROOT / "starters" / scenario_id
        manifest = json.loads((scenario_dir / "scenario.json").read_text())
        disk_facts = [
            json.loads((scenario_dir / rel).read_text()) for rel in manifest["facts"]
        ]
        store_facts = runtime.store.as_of(
            manifest["caseId"], knowledge=demo_app._now_knowledge()
        )
        canon = lambda facts: sorted(  # noqa: E731
            json.dumps(f, sort_keys=True, separators=(",", ":")) for f in facts
        )
        assert canon(store_facts) == canon(disk_facts), scenario_id


def test_scenarios_report_extraction_provenance(live_runtime):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = {s["id"]: s for s in res.json()}

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
    # committed below-floor confidence, which Docling would not reproduce).
    review = scenarios[REVIEW_SCENARIO_ID]
    assert review["extraction"]["extractor"]["name"] == "duly-demo-extractor"


# ---------------------------------------------------------------------------
# The abstention
# ---------------------------------------------------------------------------


def test_review_scenario_abstains_below_the_attribute_floor(live_runtime):
    payload = _adjudicate(REVIEW_SCENARIO_ID)
    assert payload["engineMode"] == "live"

    found = payload["determination"]
    assert found["verdict"] == "Compliant"
    assert found["tone"] == "warn"
    assert "0.62" in found["detail"] and "0.9" in found["detail"]

    assert len(payload["abstentions"]) == 1
    entry = payload["abstentions"][0]
    assert entry["reason"] == "low_confidence"
    assert entry["attribute"] == "nc:noticeMailedDate"
    assert entry["confidence"] == {"score": 0.62, "method": "platt"}
    assert entry["threshold"]["minConfidence"] == 0.9
    assert entry["threshold"]["source"] == "attribute"
    assert entry["threshold"]["pack"] == "termination-notice-us-states"
    assert entry["threshold"]["packVersion"]
    assert entry["itemId"].startswith("urn:duly:review:sha256:")
    assert entry["itemStatus"] == "open"

    # The receipt itself stays verbatim — enrichment lives beside it.
    receipt_entry = payload["receipt"]["abstentions"][0]
    assert "itemId" not in receipt_entry and "itemStatus" not in receipt_entry

    # The abstained fact links to its document span like any grounded fact.
    abstained = payload["factIndex"][entry["facts"][0]]
    assert abstained["quote"] == "Date of Mailing: July 25, 2026"
    assert abstained["documentId"]
    assert abstained["charSpan"]["end"] > abstained["charSpan"]["start"]
    assert abstained["provenance"]["kind"] == "machine"

    review = payload["review"]
    assert review["available"] is True
    assert review["calibrationPairs"] == 0
    assert review["resolved"] == []


def test_other_scenarios_carry_no_abstentions(live_runtime):
    payload = _adjudicate("notice-ny")
    assert payload["abstentions"] == []
    assert payload["determination"]["verdict"] == "Not compliant"


# ---------------------------------------------------------------------------
# The correction flow
# ---------------------------------------------------------------------------


def test_correction_round_trip_flips_the_decision(live_runtime):
    payload = _adjudicate(REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    res = _correct(item_id)
    assert res.status_code == 200, res.text
    corrected = res.json()

    # The flip: verdict changes, abstention gone.
    assert corrected["receipt"]["decision"]["value"] == {"kind": "boolean", "value": False}
    assert corrected["determination"]["verdict"] == "Not compliant"
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
    assert resolved["value"] == {"kind": "date", "value": "2026-07-25"}
    assert review["calibrationPairs"] == 1
    assert review["calibrationNote"]

    # Re-adjudicating fresh shows the corrected world: no abstention entry.
    again = _adjudicate(REVIEW_SCENARIO_ID)
    assert again["abstentions"] == []
    assert again["determination"]["verdict"] == "Not compliant"

    # Terminal item: a second correction is refused.
    assert _correct(item_id).status_code == 409


def test_correction_rejects_a_malformed_value_and_leaves_the_item_open(live_runtime):
    payload = _adjudicate(REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    res = _correct(item_id, value="not-a-date")
    assert res.status_code == 422
    assert "ISO date" in res.json()["detail"]

    res = _correct(item_id, reviewerName="   ")
    assert res.status_code == 422

    # Nothing resolved: the abstention is still there and still open.
    again = _adjudicate(REVIEW_SCENARIO_ID)
    assert again["abstentions"][0]["itemStatus"] == "open"
    assert again["review"]["calibrationPairs"] == 0


def test_unknown_item_and_wrong_scenario_are_refused(live_runtime):
    payload = _adjudicate(REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    assert _correct("urn:duly:review:sha256:" + "0" * 64).status_code == 404
    # The item belongs to the review case, not notice-ny's.
    assert _correct(item_id, scenarioId="notice-ny").status_code == 409


# ---------------------------------------------------------------------------
# Fixture mode degrades honestly
# ---------------------------------------------------------------------------


def test_fixture_mode_disables_the_review_flow_honestly(monkeypatch):
    monkeypatch.setenv("DULY_DEMO_FORCE_FIXTURE", "1")
    demo_app._reset_runtime()

    scenarios = client.get("/api/scenarios").json()
    ids = {s["id"] for s in scenarios}
    assert REVIEW_SCENARIO_ID not in ids  # the arc needs the session store

    fixture = scenarios[0]
    assert fixture["review"]["available"] is False
    assert fixture["review"]["note"]
    assert fixture["extraction"]["source"] == "fixture"
    assert "no extraction run" in fixture["extraction"]["label"]

    payload = _adjudicate(fixture["id"], fixture["questions"][0]["attribute"])
    assert payload["review"]["available"] is False
    assert payload["review"]["note"]

    refused = _correct("urn:duly:review:sha256:" + "0" * 64, scenarioId=fixture["id"])
    assert refused.status_code == 503
    assert "fixture" in refused.json()["detail"].lower()

    golden = client.get("/api/review/golden-case", params={"itemId": "urn:x"})
    assert golden.status_code == 503

    demo_app._reset_runtime()


# ---------------------------------------------------------------------------
# Golden export
# ---------------------------------------------------------------------------


def test_golden_export_bundle_replays_byte_for_byte(live_runtime):
    payload = _adjudicate(REVIEW_SCENARIO_ID)
    item_id = payload["abstentions"][0]["itemId"]

    # Export before resolution is refused.
    early = client.get("/api/review/golden-case", params={"itemId": item_id})
    assert early.status_code == 409

    assert _correct(item_id).status_code == 200

    res = client.get("/api/review/golden-case", params={"itemId": item_id})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    bundle = zipfile.ZipFile(io.BytesIO(res.content))
    names = bundle.namelist()
    case_yaml_name = next(n for n in names if n.endswith("case.yaml"))
    case_id = case_yaml_name.split("/")[1]
    # A fresh id from the review-NNNN series, never the committed review-0001.
    assert case_id.startswith("review-") and case_id != "review-0001"
    assert f"receipts/{case_id}.json" in names
    fact_names = [n for n in names if f"cases/{case_id}/facts/" in n]
    assert len(fact_names) == 4

    # Replay: adjudicate the bundle's facts with the pinned pack at the
    # bundle's as-of pair and byte-compare against the bundled receipt.
    case = yaml.safe_load(bundle.read(case_yaml_name))
    facts = [json.loads(bundle.read(n)) for n in fact_names]
    from duly_kernel.api import adjudicate  # noqa: PLC0415

    pack = yaml.safe_load((REPO_ROOT / case["pack"]).read_text(encoding="utf-8"))
    fresh = adjudicate(
        facts, pack, case["asOfEffective"], case["asOfKnowledge"], case["question"]
    )
    fresh_bytes = (json.dumps(fresh, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    assert fresh_bytes == bundle.read(f"receipts/{case_id}.json")
    assert fresh["decision"]["value"] == {"kind": "boolean", "value": False}
    assert fresh["abstentions"] == []  # the superseded fact is out of the projection
