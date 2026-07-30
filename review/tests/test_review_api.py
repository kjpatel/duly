"""API tests for the review-queue FastAPI surface (TestClient, like demo).

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest review/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reviewtest_helpers import (  # noqa: E402
    ARC_AS_OF_KNOWLEDGE,
    ARC_CASE_ID,
    ARC_CORRECTION_TS,
    ARC_MAILED_CONFIDENCE,
    adjudicate_arc,
    build_arc_facts,
    load_notice_pack,
    mailed_fact,
    make_correction,
)

from fastapi.testclient import TestClient  # noqa: E402

from duly_review import ReviewQueue  # noqa: E402
from duly_review.api import create_app  # noqa: E402
from duly_store.store import FactStore  # noqa: E402

T0 = ARC_AS_OF_KNOWLEDGE
T1 = ARC_CORRECTION_TS


@pytest.fixture()
def harness():
    """(client, store, facts, receipt): in-memory app with the arc's machine
    facts ingested and the abstaining receipt ready to enqueue."""
    queue = ReviewQueue(":memory:", check_same_thread=False)
    store = FactStore(":memory:", check_same_thread=False)
    store.init_schema()
    client = TestClient(create_app(queue, store))
    facts = build_arc_facts()
    for f in facts:
        store.ingest(f)
    receipt = adjudicate_arc(facts)
    return client, store, facts, receipt


def _enqueue(client, receipt) -> str:
    res = client.post("/api/enqueue", json={"receipt": receipt, "recordedAt": T0})
    assert res.status_code == 200
    (item,) = res.json()["items"]
    assert item["created"] is True
    return item["itemId"]


def test_enqueue_list_get_and_events(harness):
    client, _, _, receipt = harness
    item_id = _enqueue(client, receipt)

    # Idempotent re-enqueue over HTTP.
    res = client.post("/api/enqueue", json={"receipt": receipt, "recordedAt": T1})
    assert res.json()["items"] == [{"itemId": item_id, "created": False}]

    res = client.get("/api/items")
    assert res.status_code == 200
    (item,) = res.json()
    assert item["itemId"] == item_id
    assert item["status"] == "open"
    assert item["caseId"] == ARC_CASE_ID

    assert client.get("/api/items", params={"status": "resolved"}).json() == []
    assert client.get("/api/items", params={"caseId": "case:none"}).json() == []

    res = client.get(f"/api/items/{item_id}")
    assert res.status_code == 200
    assert res.json()["entry"] == receipt["abstentions"][0]

    res = client.get(f"/api/items/{item_id}/events")
    assert res.status_code == 200
    assert [e["event_kind"] for e in res.json()] == ["opened"]


def test_tampered_receipt_is_rejected(harness):
    client, _, _, receipt = harness
    tampered = dict(receipt)
    tampered["caseId"] = "case:evil"
    res = client.post("/api/enqueue", json={"receipt": tampered, "recordedAt": T0})
    assert res.status_code == 400
    assert "receiptSha256 mismatch" in res.json()["detail"]


def test_claim_resolve_flow_and_store_roundtrip(harness):
    client, store, facts, receipt = harness
    item_id = _enqueue(client, receipt)

    res = client.post(f"/api/items/{item_id}/claim",
                      json={"assignee": "reviewer:kp", "recordedAt": T0})
    assert res.status_code == 200
    assert res.json()["assignee"] == "reviewer:kp"
    assert res.json()["status"] == "open"

    correction = make_correction(mailed_fact(facts))
    res = client.post(f"/api/items/{item_id}/resolve",
                      json={"correction": correction, "recordedAt": T1})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "resolved"
    assert body["resolution"]["factId"] == correction["id"]
    assert body["resolution"]["label"]["correct"] == 1

    # The correction reached the real fact store through the API.
    after = store.as_of(ARC_CASE_ID, knowledge=T1)
    assert correction["id"] in {f["id"] for f in after}
    assert mailed_fact(facts)["id"] not in {f["id"] for f in after}

    # Terminal: a second resolution is a conflict.
    res = client.post(f"/api/items/{item_id}/resolve",
                      json={"correction": correction, "recordedAt": T1})
    assert res.status_code == 409


def test_dismiss_flow(harness):
    client, _, _, receipt = harness
    item_id = _enqueue(client, receipt)
    res = client.post(f"/api/items/{item_id}/dismiss",
                      json={"reason": "scan illegible", "recordedAt": T1})
    assert res.status_code == 200
    assert res.json()["status"] == "dismissed"
    assert res.json()["dismissal"] == {"reason": "scan illegible"}
    res = client.post(f"/api/items/{item_id}/claim",
                      json={"assignee": "reviewer:kp", "recordedAt": T1})
    assert res.status_code == 409


def test_invalid_correction_is_422(harness):
    client, _, facts, receipt = harness
    item_id = _enqueue(client, receipt)
    bad = make_correction(mailed_fact(facts), actor={"id": "reviewer:kp"})  # no role
    res = client.post(f"/api/items/{item_id}/resolve",
                      json={"correction": bad, "recordedAt": T1})
    assert res.status_code == 422
    assert "id and role" in res.json()["detail"]
    assert client.get(f"/api/items/{item_id}").json()["status"] == "open"


def test_unknown_item_is_404(harness):
    client, _, facts, _ = harness
    bogus = "urn:duly:review:sha256:" + "0" * 64
    assert client.get(f"/api/items/{bogus}").status_code == 404
    assert client.get(f"/api/items/{bogus}/events").status_code == 404
    assert client.post(f"/api/items/{bogus}/dismiss",
                       json={"reason": "x", "recordedAt": T1}).status_code == 404


def test_calibration_pairs_endpoint(harness):
    client, _, facts, receipt = harness
    res = client.get("/api/calibration/pairs")
    assert res.status_code == 200
    assert res.json()["pairs"] == []
    assert "Censored sample" in res.json()["note"]

    item_id = _enqueue(client, receipt)
    correction = make_correction(mailed_fact(facts))
    client.post(f"/api/items/{item_id}/resolve",
                json={"correction": correction, "recordedAt": T1})
    res = client.get("/api/calibration/pairs")
    assert res.json() == {
        "pairs": [[ARC_MAILED_CONFIDENCE["score"], 1]],
        "count": 1,
        "note": res.json()["note"],
    }


def test_routed_enqueue_filter_over_http(harness):
    client, _, _, _ = harness
    pack = load_notice_pack()
    pack["abstentionPolicy"]["routeTo"] = "notice-review"
    routed = adjudicate_arc(build_arc_facts(), pack)
    res = client.post("/api/enqueue",
                      json={"receipt": routed, "recordedAt": T0, "routedTo": "other"})
    assert res.status_code == 200 and res.json()["items"] == []
    res = client.post("/api/enqueue",
                      json={"receipt": routed, "recordedAt": T0, "routedTo": "notice-review"})
    assert len(res.json()["items"]) == 1
