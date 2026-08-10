"""The county-recording starter's scripted abstention, over this repository.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `demo/tests/test_review_arc.py`, where the arc itself — extract,
abstain below the floor, correct, re-adjudicate, export a golden bundle — is
asserted against a content root assembled from `fixtures/`, because none of it
names a scenario. The one test here does name one, and that is the point of it:
the recording scenario's 0.58 top-space confidence is *scripted content*, and
deleting the starter should take the test with it.

No `DULY_DEMO_CONTENT`: the demo's default content root is this directory's
parent, so a plain `TestClient(demo.app.app)` serves the teaching content
exactly as `uvicorn demo.app:app` does. What the client fixture below does
still have to do is drop `DULY_DEMO_FORCE_FIXTURE` (`demo/tests/test_api.py`
sets it process-wide at *import*, so a combined run arrives here with it set)
and pin the stub extractor.
"""

from __future__ import annotations

import sys

import pytest

from exampletest_helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# `reload_demo` is imported rather than written out again. It is the guard that
# rebinds every demo module's content roots, and CLAUDE.md records what copying
# it costs: a second copy is one short of the version that gets edited wrong.
# The dependency only points this way — `demo/tests/` never reaches in here —
# so `git rm -r examples/` leaves the helper and its own suite intact.
_DEMO_TESTS = str(REPO_ROOT / "demo" / "tests")
if _DEMO_TESTS not in sys.path:
    sys.path.insert(0, _DEMO_TESTS)

import demo.app as demo_app  # noqa: E402
from demotest_helpers import reload_demo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def example_client(monkeypatch):
    """A store-backed runtime over this repository's example content.

    No `DULY_DEMO_CONTENT`, so the roots stay where they default; the reload on
    teardown is still here because another suite in the same run may have left
    them elsewhere.
    """
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    monkeypatch.setenv("DULY_DEMO_EXTRACTOR", "stub")
    reload_demo()
    demo_app._reset_runtime()

    with TestClient(demo_app.app) as c:
        yield c

    demo_app._reset_runtime()
    monkeypatch.undo()
    reload_demo()


def _adjudicate(client, scenario_id: str, attribute: str, as_of: str):
    res = client.post(
        "/api/adjudicate",
        json={"scenarioId": scenario_id, "attribute": attribute, "asOfEffective": as_of},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_county_recording_abstains_regardless_of_installed_extractor(example_client):
    """The recording scenario's 0.58 top-space confidence is scripted in its
    targets file, which only the stub passes through — Docling measures its own
    confidence and would sail over the floor, silently skipping the abstention
    arc the scenario exists to show. The manifest pins the stub
    (`demoExtractor`), so this must hold whether or not docling is importable.
    """
    scenarios = {s["id"]: s for s in example_client.get("/api/scenarios").json()}
    assert scenarios, "the demo served no scenarios over the example content"
    scenario = scenarios["county-recording"]

    payload = _adjudicate(
        example_client,
        "county-recording",
        attribute="rec:recordable",
        as_of=scenario["defaultAsOf"],
    )
    assert payload["engineMode"] == "live"

    found = payload["determination"]
    assert found["verdict"] == "Recordable"
    assert found["tone"] == "warn"
    assert "0.58" in found["detail"] and "0.85" in found["detail"]

    (entry,) = payload["abstentions"]
    assert entry["reason"] == "low_confidence"
    assert entry["attribute"] == "rec:firstPageTopSpaceInches"
    assert entry["routedTo"] == "recording-review"

    extractor = scenario["extraction"]["extractor"]
    assert extractor["name"] == "duly-demo-extractor"
