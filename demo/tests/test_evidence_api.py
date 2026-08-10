"""API tests for the demo's Evidence Browser (demo/evidence_api.py).

The browser is **toolkit** (M5 plan, D2): it shows whatever documents, facts
and event log a deployment's cases have, not any particular ones. So these run
against a content root assembled from [`fixtures/`](../../fixtures/README.md)
rather than against the teaching starters in `starters/`.

That is a correction, and worth stating. This module used to say these tests
run against the committed starters "not fixtures", because "a projection that
only works on a hand-made case would tell us nothing" — true of a case invented
to make one assertion pass, false of a corpus built to exercise the
projection's range. The real cost of pointing at `starters/` was invisible:
delete the teaching content and nothing here fails. Every loop iterates an
empty case list and every `assert checked >= 12` is preceded by no checks at
all, which reads exactly like success (CLAUDE.md, "a test that would still
pass with its subject deleted").

What the fixture content has to carry for this suite, and why each is here
rather than convenient:

* a scenario whose facts are grounded in **character spans of a committed
  rendition** — the corpus cases attest, which leaves the span machinery this
  page is built around untested;
* one of those confidences scripted **below the pack's floor**, so a fact is
  reported as *abstained* rather than merely uncited;
* a **review arc**, so the session store holds a supersession: it is the only
  source of a superseded or not-yet-known fact here, and therefore the only
  thing that makes the knowledge dial worth dragging;
* **committed source bytes** with a manifest `sha256`, so "served and verified"
  is a check rather than a claim.

Two things the fixture content cannot witness. They are reported rather than
worked around, because an assertion loosened until it passes is worse than an
assertion that is not made:

* the fixture pack's two decisions read the *same* bindings, so no fact is an
  input to one question and not the other. `test_citations_name_the_questions`
  asserts the weaker true thing — a fact cited by both questions, and one
  (`fx:inspector`) read by no rule and cited by neither;
* the content root holds a single document, so "a document that exists, but
  not in this case" has no witness. The path-shaped probes stay.

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

from demotest_helpers import (  # noqa: E402
    REVIEW_SCENARIO,
    SCENARIO,
    build_content_root,
    reload_demo,
)

#: The two cases an assembled fixture content root has: the scenario, and the
#: review arc the demo builds from it in the session store.
CASES = (SCENARIO, REVIEW_SCENARIO)

#: The attribute the scenario's `reviewArc` scripts below the pack's 0.80
#: floor, and the decision that abstains over it.
REVIEW_ATTRIBUTE = "fx:score"
REVIEW_QUESTION = "fx:permitted"

#: `reviewArc.defaultAsOf` in the scenario manifest. Passed explicitly wherever
#: a decision *value* is asserted: the non-review scenario's facts carry no
#: `effectiveFrom`, so its `defaultAsOf` falls back to today's date, and an
#: assertion resting on that would be reading the wall clock.
REVIEW_AS_OF = "2026-06-01"

#: What the reviewer enters. The machine's own reading, at human authority —
#: which is the sharper arc: the decision flips (permitted true -> false)
#: because the value crossed the confidence floor, not because it changed.
CORRECTED_SCORE = "12"

#: Both of the fixture pack's questions. Every fact the rules read is read by
#: both, which is what `test_citations_name_the_questions` can and cannot say.
QUESTIONS = ("fx:permitted", "fx:assessedFee")

#: A fact grounded in the same document that no rule reads — the browser's
#: "cited by nothing" case. Carries `sensitivity: pii`, which is why it is a
#: plausible thing for a document to contain and no rule to consult.
UNREAD_ATTRIBUTE = "fx:inspector"


@pytest.fixture
def content_root(tmp_path_factory) -> Path:
    """A fresh content root per test.

    The session fact store is process-global and these tests supersede facts in
    it, so nothing may carry between tests anyway; a per-test root keeps the
    filesystem side of that honest too.
    """
    return build_content_root(tmp_path_factory.mktemp("content"))


@pytest.fixture
def client(content_root, monkeypatch):
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    # demo/tests/test_api.py forces fixture mode process-wide at import time,
    # so a collection that includes it leaves DULY_DEMO_FORCE_FIXTURE set for
    # everyone. These tests are about the store-backed browser; monkeypatch
    # puts the variable back afterwards so that suite still gets its fixtures.
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    # The scenario manifest already pins the stub, and the review ingest is
    # always the stub; pinning here as well keeps `_build_runtime` from
    # importing Docling at all on a machine that has the extra installed.
    monkeypatch.setenv("DULY_DEMO_EXTRACTOR", "stub")
    reload_demo()

    import demo.app
    import demo.evidence_api

    demo.app._reset_runtime()
    demo.evidence_api.reset_caches()
    with TestClient(demo.app.app) as c:
        yield c
    demo.app._reset_runtime()
    demo.evidence_api.reset_caches()

    # Roots are bound at import, so a suite that reloads on setup and not on
    # teardown leaves every later file in the directory run serving a temp
    # directory that no longer exists.
    monkeypatch.undo()
    reload_demo()


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
        "scenarioId": REVIEW_SCENARIO,
        "attribute": REVIEW_QUESTION,
        "asOfEffective": REVIEW_AS_OF,
    }
    adjudication = client.post("/api/adjudicate", json=body).json()
    abstentions = adjudication["abstentions"]
    assert abstentions, "the review arc's scripted below-floor fact did not abstain"
    item = abstentions[0]
    assert item["attribute"] == REVIEW_ATTRIBUTE
    res = client.post(
        "/api/review/correct",
        json={**body, "itemId": item["itemId"], "value": CORRECTED_SCORE,
              "reviewerName": "Dana Reyes", "reviewerRole": "Compliance analyst"},
    )
    assert res.status_code == 200, res.text
    resolution = res.json()["resolution"]
    return resolution["supersededFactId"], resolution["factId"]


# ---------------------------------------------------------------------------
# Discovery


def test_every_case_is_browsable_and_store_backed(client):
    payload = client.get("/api/evidence/cases").json()
    ids = {c["id"] for c in payload["cases"]}
    # Equality, not containment: the review arc's case exists only in the
    # session store, so a content root whose scenarios cannot be ingested would
    # quietly offer the scenario alone (demo/app.py swallows that failure by
    # design, so nothing else here would say so).
    assert ids == set(CASES)
    for case in payload["cases"]:
        assert case["storeBacked"], f"{case['id']} is not served from the session store"
        assert case["documentCount"] >= 1
        assert case["factCount"] >= 1
    assert payload["capabilities"]["store"] is True


def test_unknown_case_and_unparseable_knowledge_are_refused(client):
    assert client.get("/api/evidence/cases/nope").status_code == 404
    assert (
        client.get(
            f"/api/evidence/cases/{SCENARIO}", params={"knowledge": "not-a-date"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/evidence/cases/{SCENARIO}/facts/urn:duly:fact:sha256:deadbeef"
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
    import demo.app as demo_app

    runtime = demo_app._active_runtime()
    assert runtime is not None
    _correct_the_review_case(client)  # so at least one case has a supersession

    checked_points = 0
    for case_id in CASES:
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
    # One extraction point per case, plus the correction's own point on the
    # review case: the horizon where the two projections could most easily
    # disagree, and the reason the correction is run first.
    assert checked_points >= len(CASES) + 1


def test_facts_are_served_verbatim(client):
    """The wrapper carries the fact; it never edits it. A single added or
    reordered key would change the bytes the content hash is over."""
    checked = 0
    for case_id in CASES:
        for record in _case(client, case_id)["facts"]:
            fact = record["fact"]
            body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
            canonical = json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            assert hashlib.sha256(canonical).hexdigest() == fact["contentHash"], (
                f"{case_id}: {fact['id']} does not re-hash to its contentHash"
            )
            checked += 1
    # Three facts in fixtures/scenario/, seen twice: once as the scenario, once
    # as the review-arc case re-extracted from the same document.
    assert checked >= 6


def test_every_span_slices_its_own_quote_out_of_the_rendition(client):
    """The highlight the browser draws is the text the fact quotes — the whole
    claim the document pane makes."""
    checked = 0
    for case_id in CASES:
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
    # Every fact in fixtures/scenario/ is span-grounded, in both cases built
    # from it. The floor is what the content guarantees, not a round number.
    assert checked >= 6


# ---------------------------------------------------------------------------
# Supersession — the reason the timeline exists


def test_a_correction_appears_on_the_timeline_and_supersedes_in_place(client):
    machine_id, correction_id = _correct_the_review_case(client)
    payload = _case(client, REVIEW_SCENARIO)
    by_id = {f["id"]: f for f in payload["facts"]}

    assert by_id[machine_id]["state"] == "superseded"
    assert by_id[machine_id]["supersededBy"] == correction_id
    assert by_id[correction_id]["state"] == "live"
    assert by_id[correction_id]["supersedes"] == machine_id
    assert by_id[correction_id]["provenance"]["kind"] == "human"
    # A human correction is grounded in an attestation, not in the document —
    # a browser that only understood document groundings would show it as
    # ungrounded, which is the opposite of what it is.
    assert by_id[correction_id]["groundingKind"] == "attestation"
    assert by_id[correction_id]["groundingDetail"]["channel"] == "review-queue"

    last = payload["timeline"][-1]
    assert last["superseded"] == 1 and last["asserted"] == 1
    assert "superseded" in last["label"]


def test_dragging_the_dial_back_unwinds_the_correction(client):
    machine_id, correction_id = _correct_the_review_case(client)
    payload = _case(client, REVIEW_SCENARIO)
    before = payload["timeline"][-2]["at"]

    earlier = _case(client, REVIEW_SCENARIO, knowledge=before)
    by_id = {f["id"]: f for f in earlier["facts"]}
    assert by_id[machine_id]["state"] == "live"
    assert by_id[correction_id]["state"] == "future"
    # The supersession is visible as pending rather than silently absent.
    assert by_id[machine_id]["pendingSupersededBy"] == correction_id
    assert earlier["counts"]["future"] >= 1

    # The unwind, counted. This case's machine facts arrive in one envelope, so
    # the earliest horizon is the one before the correction: nothing superseded
    # yet, and the correction not yet known. (The live *count* is equal at both
    # ends — the correction replaces the fact it supersedes one for one — so it
    # is the superseded and future counts that carry the claim here.)
    first = payload["timeline"][0]["at"]
    earliest = _case(client, REVIEW_SCENARIO, knowledge=first)
    assert earliest["counts"]["future"] >= 1
    assert earliest["counts"]["superseded"] == 0
    assert payload["counts"]["superseded"] >= 1
    assert payload["counts"]["future"] == 0


def test_history_walks_the_supersession_chain_in_both_directions(client):
    machine_id, correction_id = _correct_the_review_case(client)
    for fact_id in (machine_id, correction_id):
        history = _fact(client, REVIEW_SCENARIO, fact_id)["history"]
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
    checked = 0
    for case_id in CASES:
        for record in _case(client, case_id)["facts"]:
            conformance = _fact(client, case_id, record["id"])["conformance"]
            assert conformance["available"] is True
            assert conformance["conformant"] is True, conformance["issues"]
            assert conformance["slot"] is not None
            assert conformance["slot"]["kind"]
            checked += 1
    assert checked >= 6


def test_citations_name_the_questions_that_used_the_fact(client):
    """`fx:score` is read by the exception behind *both* of the pack's
    decisions, so one fact is cited twice; `fx:inspector` sits in the same
    document, is read by no rule, and is cited by neither.

    The correction runs first because the machine's own `fx:score` is scripted
    below the floor: it is *abstained*, not an input (the test below). A fact
    only becomes an input once a human has stood behind it, which is the arc
    this page exists to make visible.
    """
    _machine_id, correction_id = _correct_the_review_case(client)
    payload = _case(client, REVIEW_SCENARIO)
    by_attr = {f["attribute"]: f for f in payload["facts"] if f["state"] == "live"}

    corrected = _fact(
        client, REVIEW_SCENARIO, correction_id, effective=REVIEW_AS_OF
    )["citations"]
    assert corrected["available"] is True
    roles = {q["attribute"]: q["role"] for q in corrected["questions"]}
    assert set(roles) == set(QUESTIONS)
    assert all(roles[attribute] == "input" for attribute in QUESTIONS), roles

    unread = _fact(
        client, REVIEW_SCENARIO, by_attr[UNREAD_ATTRIBUTE]["id"], effective=REVIEW_AS_OF
    )["citations"]
    unread_roles = {q["attribute"]: q["role"] for q in unread["questions"]}
    assert set(unread_roles) == set(QUESTIONS)
    assert all(unread_roles[attribute] is None for attribute in QUESTIONS), unread_roles


def test_an_abstained_fact_is_reported_as_abstained_not_as_uncited(client):
    """Below the floor is not the same as unused, and the difference is the
    whole point: the decision stands on a presumption *because* this fact was
    excluded."""
    payload = _case(client, SCENARIO)
    fact = next(f for f in payload["facts"] if f["attribute"] == REVIEW_ATTRIBUTE)
    citations = _fact(client, SCENARIO, fact["id"])["citations"]
    roles = {q["role"] for q in citations["questions"]}
    assert "abstained" in roles


# ---------------------------------------------------------------------------
# Source documents


def test_source_bytes_are_served_and_verified_against_the_manifest(client):
    payload = _case(client, SCENARIO)
    assert payload["documents"]
    for doc in payload["documents"]:
        source = doc["source"]
        assert source["available"] is True
        assert source["verified"] is True, "committed bytes drifted from the manifest"
        res = client.get(
            f"/api/evidence/cases/{SCENARIO}/documents/{doc['id']}/source"
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        assert res.content.startswith(b"%PDF")
        assert hashlib.sha256(res.content).hexdigest() == source["sha256"]


def test_a_document_id_is_never_a_path(client):
    """The client names an id; the server resolves it in an index built from
    the committed manifests. Nothing a request carries reaches the filesystem.

    The third probe this test used to make — a document that exists, but in
    another case — has no witness in a fixture content root: it holds one
    document, and the review arc is built from that same one. The refusal is
    still implemented (`document_id not in scenario["documents"]`); it is not
    asserted here rather than asserted against content invented to carry it.
    """
    for probe in ("../../pyproject.toml", "doc:not-a-real-document"):
        res = client.get(f"/api/evidence/cases/{SCENARIO}/documents/{probe}/source")
        assert res.status_code == 404, probe


# ---------------------------------------------------------------------------
# Honest degradation


def test_without_a_store_the_browser_says_so_instead_of_faking_a_timeline(
    content_root, monkeypatch
):
    """No session store: committed facts from disk, all live, and a note saying
    the timeline is absent rather than empty-because-nothing-happened.

    The store is removed the way a deployment removes it — `_build_runtime`
    returns None when `duly_store`/`duly_extraction`/`duly_review` are not
    importable — rather than by forcing fixture mode, which also stops the
    scenarios loading at all and would leave this asserting over no case.
    """
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    reload_demo()

    import demo.app
    import demo.evidence_api

    monkeypatch.setattr(demo.app, "_build_runtime", lambda: None)
    demo.app._reset_runtime()
    demo.evidence_api.reset_caches()
    try:
        with TestClient(demo.app.app) as c:
            listing = c.get("/api/evidence/cases").json()
            assert listing["cases"], "no case to degrade honestly over"
            assert listing["capabilities"]["store"] is False
            assert all(not case["storeBacked"] for case in listing["cases"])

            payload = _case(c, SCENARIO)
            assert payload["storeBacked"] is False
            assert payload["timeline"] == []
            assert payload["knowledge"] is None
            assert "no event log" in payload["note"]
            assert payload["counts"]["live"] == len(payload["facts"])

            detail = _fact(c, SCENARIO, payload["facts"][0]["id"])
            assert detail["history"] == []
            assert detail["conformance"]["available"] is True
    finally:
        demo.app._reset_runtime()
        demo.evidence_api.reset_caches()
        monkeypatch.undo()
        reload_demo()
