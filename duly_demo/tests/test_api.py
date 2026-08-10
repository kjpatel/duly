"""API tests for the duly demo app.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest duly_demo/tests -q
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

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from duly_demo.app import _determination, _render_answer, app  # noqa: E402

client = TestClient(app)


FIXTURE_PACK = REPO_ROOT / "fixtures" / "pack.yaml"


def _pack() -> dict:
    """A rule pack, loaded as the demo loads it.

    Determination tests build their scenario around a *real* pack because the
    wording under test lives in the pack's `phrasing:` block, not in
    duly_demo/app.py — fabricating one inline would only test the renderer.

    That pack is the toolkit's own fixture, which grew a non-boolean decision
    (`fx:assessedFee`, money, with phrasing) precisely so these tests stop
    depending on the teaching content. A boolean decision takes the kernel's
    Yes/No fallback and never reaches the phrasing path at all, which is why
    the fixture could not serve them until it did.

    It used to take a `name`, selecting a committed pack for the few tests
    whose subject genuinely *was* a teaching pack. Those tests now live in
    `examples/tests/test_example_packs_api.py` and are deleted with the packs
    they describe.
    """
    return yaml.safe_load(FIXTURE_PACK.read_text(encoding="utf-8"))


def _scenario(facts: list[dict] | None = None) -> dict:
    return {"pack": _pack(), "facts": facts or []}


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


def test_determination_is_the_only_place_verdict_wording_lives():
    """The client renders determination verbatim, so it must be self-sufficient."""
    receipt = {
        "decision": {
            "attribute": "fx:assessedFee",
            "value": {"kind": "money", "amount": "0.00", "currency": "USD"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }

    found = _determination(receipt, _scenario(), "2026-07-29")

    # The fixture pack's unguarded fallback case; the guarded one is asserted
    # by the money receipt below.
    assert found["verdict"] == "No fee"
    assert found["detail"] == "Nothing is owed on this widget"
    # No as-of date in the structured fields: the client renders that separately.
    assert "2026-07-29" not in found["verdict"] + found["detail"]


def test_unmapped_attributes_fall_back_without_claiming_a_verdict():
    """An attribute the pack declares no phrasing for degrades honestly.

    This is the fallback the pack-authoring guide points at: the demo says
    `attribute = value` rather than inventing a verdict it cannot support.
    """
    receipt = {
        "decision": {
            "attribute": "nc:someFutureAttribute",
            "value": {"kind": "code", "value": "Whatever"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }
    scenario = _scenario()

    found = _determination(receipt, scenario, "2026-07-29")

    assert found["generic"] is True
    assert found["tone"] == ""
    assert _render_answer(receipt, scenario, "2026-07-29") == (
        "nc:someFutureAttribute = Whatever as of 2026-07-29."
    )


def test_a_boolean_decision_needs_no_phrasing_block():
    """The Yes/No fallback, so a simple pack declares nothing at all."""
    receipt = {
        "decision": {
            "attribute": "nc:someFutureFlag",
            "value": {"kind": "boolean", "value": True},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }
    scenario = _scenario()
    scenario["pack"]["decisions"].append(
        {"attribute": "nc:someFutureFlag", "entityType": "fx:Widget"}
    )

    found = _determination(receipt, scenario, "2026-07-29")

    assert found == {"verdict": "Yes", "detail": "", "tone": "pos"}


def test_verdict_wording_is_pack_data_not_demo_code():
    """Editing the pack changes the wording; no demo code names the verdict.

    This is the contribution-surface promise: a pack author who wants
    different wording edits their pack, and a *new* pack's decision renders
    without anyone touching duly_demo/app.py.
    """
    receipt = {
        "decision": {
            "attribute": "fx:assessedFee",
            "value": {"kind": "money", "amount": "250.00", "currency": "USD"},
        },
        "asOf": {"effective": "2026-07-29T00:00:00Z"},
    }
    scenario = _scenario()
    for decision in scenario["pack"]["decisions"]:
        if decision["attribute"] == "fx:assessedFee":
            decision["phrasing"] = [
                {"verdict": "Gebühr fällig", "detail": "{money}", "tone": "neg"}
            ]

    assert _determination(receipt, scenario, "2026-07-29") == {
        "verdict": "Gebühr fällig",
        "detail": "250.00 USD",
        "tone": "neg",
    }


def test_fixture_mode_refuses_questions_the_fixture_receipt_cannot_answer(monkeypatch):
    """The fixture receipt answers one attribute; the rest must fail loudly.

    Serving it for another question would show an unrelated determination as if
    it were the answer to the one that was asked.
    """
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    monkeypatch.setattr("duly_demo.app._run_kernel", lambda *args, **kwargs: (None, None))

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


def test_report_endpoint_exports_receipt_as_prov_o_jsonld(monkeypatch):
    """format=jsonld on the export endpoint serves the receipt wrapped for
    RDF consumers — deliberately endpoint-only, no UI button (a demo viewer
    wants the receipt; a lineage stack wants an HTTP path, not a button)."""
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    scenario = _first_scenario()
    res = client.get(
        "/api/report",
        params={
            "scenarioId": scenario["id"],
            "attribute": scenario["questions"][0]["attribute"],
            "asOfEffective": scenario["defaultAsOf"],
            "format": "jsonld",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/ld+json")
    assert ".jsonld" in res.headers["content-disposition"]
    doc = res.json()
    assert doc["@context"].endswith("decision-receipt.context.jsonld")
    assert doc["@id"].startswith("urn:duly:receipt:sha256:")
    # The stored receipt rides inside unchanged: same decision, same hash field.
    assert doc["receiptSha256"] == doc["@id"].rsplit(":", 1)[-1]
    assert doc["decision"]["attribute"] == scenario["questions"][0]["attribute"]


def test_static_assets_revalidate_rather_than_letting_the_browser_guess():
    """Starlette sends etag/last-modified but no cache-control, and a browser
    with no directive invents its own freshness window and serves from cache
    without asking — which is how a stale stylesheet renders against new
    markup. `no-cache` requires revalidation; the etag keeps it cheap."""
    for path in ("/style.css", "/app.js", "/index.html"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers.get("cache-control") == "no-cache", path
        assert res.headers.get("etag"), path

    # Revalidation must still be a 304 with no body, or this trades one bug
    # for a bandwidth regression.
    etag = client.get("/style.css").headers["etag"]
    fresh = client.get("/style.css", headers={"If-None-Match": etag})
    assert fresh.status_code == 304
    assert not fresh.content


def _export(scenario, fmt: str):
    return client.get(
        "/api/report",
        params={
            "scenarioId": scenario["id"],
            "attribute": scenario["questions"][0]["attribute"],
            "asOfEffective": scenario["defaultAsOf"],
            "format": fmt,
        },
    )


def test_the_workspace_exports_a_receipt_the_viewer_can_verify(monkeypatch):
    """The receipt download is a server round trip, and the reason is numeric
    fidelity rather than tidiness: `abstentions[].confidence.score` and
    `.threshold.minConfidence` are JSON *numbers* in the receipt schema, and
    the browser assembling this file wrote a score of 1.0 back out as 1 — a
    different canonical body, so the download failed its own hash check. The
    assertion that catches a regression is the round trip, not the shape."""
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    scenario = _first_scenario()
    res = _export(scenario, "receipt")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")

    checked = client.post(
        "/api/receipts/inspect", json={"documents": [res.text]}
    ).json()
    states = {c["id"]: c["state"] for c in checked["verification"]["checks"]}
    assert states["receiptHash"] == "pass"


def test_the_workspace_exports_a_bundle_that_replays_whole(monkeypatch):
    """The bundle is the receipt *and* the fact set it was adjudicated over,
    so it verifies on all three checks with nothing else in hand — which a
    bare receipt cannot do, because a receipt pins its facts by hash rather
    than carrying them."""
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    scenario = _first_scenario()
    res = _export(scenario, "bundle")
    assert res.status_code == 200
    docs = res.json()
    assert isinstance(docs, list)
    assert sum("receiptSha256" in d for d in docs) == 1
    assert sum("contentHash" in d and "receiptSha256" not in d for d in docs) >= 1

    checked = client.post(
        "/api/receipts/inspect", json={"documents": [res.text]}
    ).json()
    states = {c["id"]: c["state"] for c in checked["verification"]["checks"]}
    assert states == {"receiptHash": "pass", "facts": "pass", "replay": "pass"}


def test_report_endpoint_rejects_unknown_format():
    scenario = _first_scenario()
    res = client.get(
        "/api/report",
        params={
            "scenarioId": scenario["id"],
            "attribute": scenario["questions"][0]["attribute"],
            "asOfEffective": scenario["defaultAsOf"],
            "format": "xml",
        },
    )
    assert res.status_code == 422
