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

from demo.app import _determination, _render_answer, app  # noqa: E402

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


def test_every_scenario_carries_a_domain(monkeypatch):
    """Domains group the picker by regulated vertical; a scenario without one
    falls into the "other" group rather than erroring (manifest field is
    optional — presentation metadata, not contract)."""
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert scenarios
    for scenario in scenarios:
        assert scenario["domain"], scenario["id"]
        assert scenario["domainLabel"], scenario["id"]

    by_id = {s["id"]: s for s in scenarios}
    assert by_id["notice-ny"]["domain"] == "insurance"
    assert by_id["notice-ny"]["domainLabel"] == "Insurance"
    for scenario_id in (
        "trid",
        "ron-closing",
        "esign-package",
        "tila-rescission",
        "county-recording",
    ):
        assert by_id[scenario_id]["domain"] == "mortgage", scenario_id
        assert by_id[scenario_id]["domainLabel"] == "Mortgage closing", scenario_id
    if "notice-ny-review" in by_id:
        assert by_id["notice-ny-review"]["domain"] == "insurance"


def test_every_offered_question_is_answerable_and_phrased_for_humans(monkeypatch):
    """Whatever a pack advertises must adjudicate and render without CURIEs.

    Derived from the packs rather than a hard-coded list, so adding a decision
    extends the coverage instead of breaking the test.
    """
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert scenarios

    for scenario in scenarios:
        questions = scenario["questions"]
        # The demo is meant to show the as-of flip *and* a derived intermediate,
        # so every starter scenario should offer more than a single question.
        assert len(questions) > 1, scenario["id"]
        for question in questions:
            attribute = question["attribute"]
            assert question["question"]
            response = client.post(
                "/api/adjudicate",
                json={
                    "scenarioId": scenario["id"],
                    "attribute": attribute,
                    "asOfEffective": scenario["defaultAsOf"],
                },
            )
            assert response.status_code == 200, (scenario["id"], attribute)
            payload = response.json()
            assert payload["receipt"]["decision"]["attribute"] == attribute

            # A recognised attribute gets a verdict; the generic fallback would
            # leak the raw CURIE into the rendered answer.
            found = payload["determination"]
            assert found["verdict"], attribute
            assert not found.get("generic"), attribute
            assert found["tone"] in {"pos", "neg", "warn", ""}

            namespace = f"{attribute.split(':')[0]}:"
            assert namespace not in payload["answer"], payload["answer"]
            assert namespace not in found["verdict"]
            assert namespace not in found["detail"]


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


def test_render_answer_describes_tolerance_cure_as_a_determination():
    receipt = {
        "decision": {
            "attribute": "trid:toleranceCureAmount",
            "value": {"kind": "money", "amount": "250.00", "currency": "USD"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }

    answer = _render_answer(receipt, {"facts": []}, "2026-07-29")

    assert answer == "Cure required: 250.00 USD tolerance cure as of 2026-07-29."
    assert _determination(receipt, {"facts": []}, "2026-07-29") == {
        "verdict": "Cure required",
        "detail": "250.00 USD tolerance cure",
        "tone": "warn",
    }


def test_determination_is_the_only_place_verdict_wording_lives():
    """The client renders determination verbatim, so it must be self-sufficient."""
    receipt = {
        "decision": {
            "attribute": "trid:toleranceCategory",
            "value": {"kind": "code", "value": "ZeroTolerance"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }

    found = _determination(receipt, {"facts": []}, "2026-07-29")

    assert found["verdict"] == "Zero tolerance"
    assert found["detail"] == "The disclosed amount may not increase at closing"
    # No as-of date in the structured fields: the client renders that separately.
    assert "2026-07-29" not in found["verdict"] + found["detail"]


def test_unmapped_attributes_fall_back_without_claiming_a_verdict():
    receipt = {
        "decision": {
            "attribute": "nc:someFutureAttribute",
            "value": {"kind": "code", "value": "Whatever"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }

    found = _determination(receipt, {"facts": []}, "2026-07-29")

    assert found["generic"] is True
    assert found["tone"] == ""
    assert _render_answer(receipt, {"facts": []}, "2026-07-29") == (
        "nc:someFutureAttribute = Whatever as of 2026-07-29."
    )


def test_fixture_mode_refuses_questions_the_fixture_receipt_cannot_answer(monkeypatch):
    """The fixture receipt answers one attribute; the rest must fail loudly.

    Serving it for another question would show an unrelated determination as if
    it were the answer to the one that was asked.
    """
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    monkeypatch.setattr("demo.app._run_kernel", lambda *args, **kwargs: (None, None))

    served = client.post(
        "/api/adjudicate",
        json={
            "scenarioId": "notice-ny",
            "attribute": "nc:noticeCompliant",
            "asOfEffective": "2026-07-29",
        },
    )
    assert served.status_code == 200
    assert served.json()["engineMode"] == "fixture"

    refused = client.post(
        "/api/adjudicate",
        json={
            "scenarioId": "notice-ny",
            "attribute": "nc:requiredMinimumNoticeDays",
            "asOfEffective": "2026-07-29",
        },
    )
    assert refused.status_code == 503
    detail = refused.json()["detail"]
    assert "nc:requiredMinimumNoticeDays" in detail
    assert "nc:noticeCompliant" in detail


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
