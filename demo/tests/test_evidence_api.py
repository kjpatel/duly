"""API tests for the demo's Evidence Browser (demo/evidence_api.py).

These run against the *committed* starters and the session fact store the demo
actually builds, not fixtures: the browser's job is to show what the store
holds, and a projection that only works on a hand-made case would tell us
nothing.

The load-bearing test is ``test_the_browsers_projection_is_the_stores`` — the
module deliberately replays the event log rather than calling ``as_of``, so
that the two can be compared. Everything else here is ordinary coverage.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest demo/tests -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from demo import app as demo_app  # noqa: E402
from demo import evidence_api  # noqa: E402
from demo.app import app  # noqa: E402

REVIEW_CASE = "notice-ny-review"
STARTER_CASES = (
    "county-recording",
    "esign-package",
    "notice-ny",
    "ron-closing",
    "tila-rescission",
    "trid",
)


@pytest.fixture
def client(monkeypatch):
    # demo/tests/test_api.py forces fixture mode process-wide at import time,
    # so a collection that includes it leaves DULY_DEMO_FORCE_FIXTURE set for
    # everyone. These tests are about the store-backed browser; monkeypatch
    # puts the variable back afterwards so that suite still gets its fixtures.
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    demo_app._reset_runtime()
    evidence_api.reset_caches()
    with TestClient(app) as c:
        yield c
    # The store is process-global and the review test supersedes a fact in it;
    # a fresh runtime keeps cases independent of test order.
    demo_app._reset_runtime()
    evidence_api.reset_caches()


def _case(client, case_id, **params):
    res = client.get(f"/api/evidence/cases/{case_id}", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _fact(client, case_id, fact_id, **params):
    res = client.get(f"/api/evidence/cases/{case_id}/facts/{fact_id}", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _correct_the_review_case(client):
    """Run the review arc: abstain, correct, supersede. Returns (machine id,
    correction id)."""
    body = {
        "scenarioId": REVIEW_CASE,
        "attribute": "nc:noticeCompliant",
        "asOfEffective": "2026-07-25",
    }
    adjudication = client.post("/api/adjudicate", json=body).json()
    item = adjudication["abstentions"][0]
    res = client.post(
        "/api/review/correct",
        json={**body, "itemId": item["itemId"], "value": "2026-06-01",
              "reviewerName": "Dana Reyes", "reviewerRole": "Compliance analyst"},
    )
    assert res.status_code == 200, res.text
    resolution = res.json()["resolution"]
    return resolution["supersededFactId"], resolution["factId"]


# ---------------------------------------------------------------------------
# Discovery


def test_every_starter_case_is_browsable_and_store_backed(client):
    payload = client.get("/api/evidence/cases").json()
    ids = {c["id"] for c in payload["cases"]}
    assert set(STARTER_CASES) <= ids
    assert REVIEW_CASE in ids
    for case in payload["cases"]:
        assert case["storeBacked"], f"{case['id']} is not served from the session store"
        assert case["documentCount"] >= 1
        assert case["factCount"] >= 1
    assert payload["capabilities"]["store"] is True


def test_unknown_case_and_unparseable_knowledge_are_refused(client):
    assert client.get("/api/evidence/cases/nope").status_code == 404
    assert (
        client.get("/api/evidence/cases/trid", params={"knowledge": "not-a-date"}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/evidence/cases/trid/facts/urn:duly:fact:sha256:deadbeef"
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# The projection


def test_the_browsers_projection_is_the_stores(client):
    """At every point on every case's timeline, the facts this module calls
    live are exactly the facts ``FactStore.as_of`` projects.

    The two answers are computed by different code — the browser replays the
    event log so it can also report superseded and not-yet-known facts, which
    as_of by design does not. A divergence is a bug in one of them, and either
    one would put a wrong fact set in front of a reader.
    """
    runtime = demo_app._active_runtime()
    assert runtime is not None
    _correct_the_review_case(client)  # so at least one case has a supersession

    checked_points = 0
    for case_id in (*STARTER_CASES, REVIEW_CASE):
        head = _case(client, case_id)
        assert head["timeline"], f"{case_id} has no event log"
        case_urn = head["caseId"]
        for point in head["timeline"]:
            payload = _case(client, case_id, knowledge=point["at"])
            browser_live = {f["id"] for f in payload["facts"] if f["state"] == "live"}
            store_live = {
                f["id"] for f in runtime.store.as_of(case_urn, knowledge=point["at"])
            }
            assert browser_live == store_live, (
                f"{case_id} at {point['at']}: browser and store disagree"
            )
            checked_points += 1
    assert checked_points >= len(STARTER_CASES)


def test_facts_are_served_verbatim(client):
    """The wrapper carries the fact; it never edits it. A single added or
    reordered key would change the bytes the content hash is over."""
    for case_id in STARTER_CASES:
        for record in _case(client, case_id)["facts"]:
            fact = record["fact"]
            body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
            canonical = json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            assert hashlib.sha256(canonical).hexdigest() == fact["contentHash"], (
                f"{case_id}: {fact['id']} does not re-hash to its contentHash"
            )


def test_every_span_slices_its_own_quote_out_of_the_rendition(client):
    """The highlight the browser draws is the text the fact quotes — the whole
    claim the document pane makes."""
    checked = 0
    for case_id in STARTER_CASES:
        payload = _case(client, case_id)
        renditions = {d["id"]: d["renditionText"] for d in payload["documents"]}
        for record in payload["facts"]:
            if not record["charSpan"] or not record["document"]:
                continue
            text = renditions[record["document"]["id"]]
            span = record["charSpan"]
            assert text[span["start"] : span["end"]] == record["quote"], (
                f"{case_id}: {record['attribute']} span does not slice its quote"
            )
            checked += 1
    assert checked >= 12


# ---------------------------------------------------------------------------
# Supersession — the reason the timeline exists


def test_a_correction_appears_on_the_timeline_and_supersedes_in_place(client):
    machine_id, correction_id = _correct_the_review_case(client)
    payload = _case(client, REVIEW_CASE)
    by_id = {f["id"]: f for f in payload["facts"]}

    assert by_id[machine_id]["state"] == "superseded"
    assert by_id[machine_id]["supersededBy"] == correction_id
    assert by_id[correction_id]["state"] == "live"
    assert by_id[correction_id]["supersedes"] == machine_id
    assert by_id[correction_id]["provenance"]["kind"] == "human"

    last = payload["timeline"][-1]
    assert last["superseded"] == 1 and last["asserted"] == 1
    assert "superseded" in last["label"]


def test_dragging_the_dial_back_unwinds_the_correction(client):
    machine_id, correction_id = _correct_the_review_case(client)
    payload = _case(client, REVIEW_CASE)
    before = payload["timeline"][-2]["at"]

    earlier = _case(client, REVIEW_CASE, knowledge=before)
    by_id = {f["id"]: f for f in earlier["facts"]}
    assert by_id[machine_id]["state"] == "live"
    assert by_id[correction_id]["state"] == "future"
    # The supersession is visible as pending rather than silently absent.
    assert by_id[machine_id]["pendingSupersededBy"] == correction_id
    assert earlier["counts"]["future"] >= 1

    first = payload["timeline"][0]["at"]
    earliest = _case(client, REVIEW_CASE, knowledge=first)
    assert earliest["counts"]["future"] >= 1
    assert earliest["counts"]["live"] < payload["counts"]["live"]


def test_history_walks_the_supersession_chain_in_both_directions(client):
    machine_id, correction_id = _correct_the_review_case(client)
    for fact_id in (machine_id, correction_id):
        history = _fact(client, REVIEW_CASE, fact_id)["history"]
        kinds = {(e["kind"], e["factId"]) for e in history}
        assert ("asserted", machine_id) in kinds
        assert ("asserted", correction_id) in kinds
        assert ("superseded", machine_id) in kinds
        assert any(e["self"] for e in history)


# ---------------------------------------------------------------------------
# Ontology and citations


def test_every_committed_fact_conforms_to_the_ontology_it_pins(client):
    """The same verdict `python -m duly_conformance check` gives in CI, per
    fact, with the slot definition the reader needs to interpret it."""
    for case_id in STARTER_CASES:
        for record in _case(client, case_id)["facts"]:
            conformance = _fact(client, case_id, record["id"])["conformance"]
            assert conformance["available"] is True
            assert conformance["conformant"] is True, conformance["issues"]
            assert conformance["slot"] is not None
            assert conformance["slot"]["kind"]


def test_citations_name_the_questions_that_used_the_fact(client):
    """`trid:feeType` decides the tolerance category and feeds the cure
    amount; the baseline amount feeds only the cure. A fact's citations are
    per question, not per case."""
    payload = _case(client, "trid")
    by_attr = {f["attribute"]: f for f in payload["facts"]}

    fee_type = _fact(client, "trid", by_attr["trid:feeType"]["id"])["citations"]
    assert fee_type["available"] is True
    roles = {q["attribute"]: q["role"] for q in fee_type["questions"]}
    assert roles["trid:toleranceCategory"] == "input"
    assert roles["trid:toleranceCureAmount"] == "input"

    baseline = _fact(client, "trid", by_attr["trid:disclosedAmountAtBaseline"]["id"])
    baseline_roles = {q["attribute"]: q["role"] for q in baseline["citations"]["questions"]}
    assert baseline_roles["trid:toleranceCureAmount"] == "input"
    assert baseline_roles["trid:toleranceCategory"] is None


def test_an_abstained_fact_is_reported_as_abstained_not_as_uncited(client):
    payload = _case(client, "county-recording")
    fact = next(
        f for f in payload["facts"] if f["attribute"] == "rec:firstPageTopSpaceInches"
    )
    citations = _fact(client, "county-recording", fact["id"])["citations"]
    roles = {q["role"] for q in citations["questions"]}
    assert "abstained" in roles


# ---------------------------------------------------------------------------
# Source documents


def test_source_bytes_are_served_and_verified_against_the_manifest(client):
    payload = _case(client, "trid")
    for doc in payload["documents"]:
        source = doc["source"]
        assert source["available"] is True
        assert source["verified"] is True, "committed bytes drifted from the manifest"
        res = client.get(
            f"/api/evidence/cases/trid/documents/{doc['id']}/source"
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        assert res.content.startswith(b"%PDF")
        assert hashlib.sha256(res.content).hexdigest() == source["sha256"]


def test_a_document_id_is_never_a_path(client):
    """The client names an id; the server resolves it in an index built from
    the committed manifests. Nothing a request carries reaches the filesystem."""
    for probe in ("../../pyproject.toml", "doc:not-a-real-document"):
        res = client.get(f"/api/evidence/cases/trid/documents/{probe}/source")
        assert res.status_code == 404, probe
    # A document that exists, but not in this case.
    other = _case(client, "notice-ny")["documents"][0]["id"]
    res = client.get(f"/api/evidence/cases/trid/documents/{other}/source")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Honest degradation


def test_without_a_store_the_browser_says_so_instead_of_faking_a_timeline(monkeypatch):
    monkeypatch.setenv("DULY_DEMO_FORCE_FIXTURE", "1")
    demo_app._reset_runtime()
    evidence_api.reset_caches()
    try:
        with TestClient(app) as c:
            listing = c.get("/api/evidence/cases").json()
            assert listing["capabilities"]["store"] is False
            assert all(not case["storeBacked"] for case in listing["cases"])

            payload = _case(c, "notice-ny")
            assert payload["storeBacked"] is False
            assert payload["timeline"] == []
            assert payload["knowledge"] is None
            assert "no event log" in payload["note"]
            assert payload["counts"]["live"] == len(payload["facts"])

            detail = _fact(c, "notice-ny", payload["facts"][0]["id"])
            assert detail["history"] == []
            assert detail["conformance"]["available"] is True
    finally:
        monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
        demo_app._reset_runtime()
        evidence_api.reset_caches()
