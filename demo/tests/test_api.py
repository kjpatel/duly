"""API tests for the duly demo app.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest demo/tests -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Pin fixture mode so tests are deterministic even once starters/ and the live
# kernel land (they exercise the committed spec/examples receipt path).
os.environ["DULY_DEMO_FORCE_FIXTURE"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from demo.app import app  # noqa: E402

client = TestClient(app)


def _first_scenario():
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) >= 1
    return scenarios[0]


def test_scenarios_lists_fixture_scenario():
    scenario = _first_scenario()
    assert scenario["id"]
    assert scenario["title"]
    assert scenario["caseId"] == "case:policy:HO-77401-NY"
    assert len(scenario["documents"]) >= 1
    assert len(scenario["questions"]) >= 1
    assert scenario["questions"][0]["attribute"] == "nc:noticeCompliant"
    assert scenario["defaultAsOf"]


def test_adjudicate_returns_receipt_with_fact_index():
    scenario = _first_scenario()
    res = client.post(
        "/api/adjudicate",
        json={
            "scenarioId": scenario["id"],
            "attribute": scenario["questions"][0]["attribute"],
            "asOfEffective": scenario["defaultAsOf"],
        },
    )
    assert res.status_code == 200
    payload = res.json()

    assert payload["engineMode"] in ("live", "fixture")
    assert isinstance(payload["answer"], str) and payload["answer"]

    receipt = payload["receipt"]
    assert "decision" in receipt
    assert receipt["decision"]["attribute"] == "nc:noticeCompliant"
    assert "value" in receipt["decision"]
    assert receipt.get("rulesFired")
    assert receipt.get("derivation")

    fact_index = payload["factIndex"]
    assert isinstance(fact_index, dict) and len(fact_index) > 0
    for entry in fact_index.values():
        assert entry["attribute"]
        assert entry["value"]


def test_fact_spans_slice_correctly_out_of_rendition_text():
    scenario = _first_scenario()
    res = client.post(
        "/api/adjudicate",
        json={
            "scenarioId": scenario["id"],
            "attribute": scenario["questions"][0]["attribute"],
            "asOfEffective": scenario["defaultAsOf"],
        },
    )
    assert res.status_code == 200
    fact_index = res.json()["factIndex"]

    checked = 0
    for entry in fact_index.values():
        if not entry.get("documentId") or not entry.get("charSpan"):
            continue
        doc_res = client.get(
            f"/api/document/{scenario['id']}/{entry['documentId']}"
        )
        assert doc_res.status_code == 200
        doc = doc_res.json()
        assert doc["title"]
        text = doc["renditionText"]
        start, end = entry["charSpan"]["start"], entry["charSpan"]["end"]
        assert 0 <= start < end <= len(text)
        assert text[start:end] == entry["quote"]
        checked += 1
    assert checked > 0


def test_unknown_scenario_and_document_404():
    assert (
        client.post(
            "/api/adjudicate",
            json={
                "scenarioId": "nope",
                "attribute": "nc:noticeCompliant",
                "asOfEffective": "2026-07-25",
            },
        ).status_code
        == 404
    )
    scenario = _first_scenario()
    assert client.get(f"/api/document/{scenario['id']}/doc:nope").status_code == 404


def test_index_html_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "duly" in res.text
