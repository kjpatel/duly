"""The demo is toolkit, and its content is configuration.

M5 decision D2: the four surfaces are toolkit rather than teaching content,
because each reads *whatever* packs, scenarios, cases and receipts exist rather
than any particular ones. The test of that claim is not that they work here —
they always did — but that they still stand up when pointed somewhere with
nothing in it, and say so. A surface that 500s on an empty corpus was teaching
content all along.

This is also Phase 3's acceptance criterion arriving early: after
`git rm -r examples/`, this is what "a working, empty toolkit" has to mean.

The other half of the claim — that configurable did not mean broken *here*,
that the default root still finds the six packs and the golden corpus — is a
statement about what this repository happens to ship. It is
`examples/tests/test_example_content_roots.py`, and it goes with them.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from demo.content import CONTENT, ENV_VAR, REPO_ROOT, ContentRoots  # noqa: E402


# --- the roots themselves ---------------------------------------------------


def test_the_default_root_is_this_repositorys_example_content():
    """So `uvicorn demo.app:app` needs no configuration, as before.

    The default moved with the content: this repository keeps its teaching
    content under `examples/`, so that is what it offers as the default root.
    The *contract* did not move — a root still holds `starters/`, `golden/`,
    `rulepacks/`, `ontologies/`, `dmn/` directly, and nobody pointing
    `DULY_DEMO_CONTENT` at their own corpus mirrors this repo's nesting.
    """
    assert ContentRoots.from_env({}).root == REPO_ROOT / "examples"


def test_the_env_var_moves_every_root_together(tmp_path):
    content = ContentRoots.from_env({ENV_VAR: str(tmp_path)})
    assert content.root == tmp_path.resolve()
    for name in ("starters", "golden", "rulepacks", "ontologies"):
        assert getattr(content, name).parent == tmp_path.resolve()
    assert content.dmn_examples == tmp_path.resolve() / "dmn"
    # Deliberately NOT moved by the env var: the built-in fixture scenario is
    # the demo's own, served from this repository's committed spec examples —
    # it ships with the demo rather than travelling with anyone's content.
    assert content.spec_examples == REPO_ROOT / "spec" / "examples"


def test_containment_accepts_a_path_inside_the_root(tmp_path):
    content = ContentRoots(root=tmp_path)
    assert content.contains(tmp_path / "rulepacks" / "x" / "pack.yaml")


@pytest.mark.parametrize("escape", ["..", "../..", "../elsewhere/pack.yaml"])
def test_containment_refuses_a_path_that_climbs_out(tmp_path, escape):
    """The guard behind every endpoint that takes a path from a caller. It is
    one method rather than four copies because a guard rewritten per call site
    is one that will eventually be rewritten wrong."""
    content = ContentRoots(root=tmp_path / "root")
    assert not content.contains(content.root / escape)


def test_a_missing_directory_is_not_an_error(tmp_path):
    """An adopter has no golden/ and no starters/ on day one. Roots are paths,
    not assertions that anything is there."""
    content = ContentRoots(root=tmp_path)
    assert not content.golden.exists()
    assert content.golden == tmp_path / "golden"


# --- the surfaces, against nothing ------------------------------------------


@pytest.fixture()
def empty_content(tmp_path, monkeypatch):
    """A demo whose content root holds nothing at all."""
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    # Each surface binds its roots at import — which is right for a server,
    # where import *is* startup — so the whole set is reloaded, in dependency
    # order, rather than just the app.
    yield from _reloaded_client()
    monkeypatch.delenv(ENV_VAR, raising=False)
    for _ in _reloaded_client():
        break


def _reloaded_client():
    import importlib

    import demo.app
    import demo.content
    import demo.evidence_api
    import demo.receipts_api
    import demo.rules_api

    importlib.reload(demo.content)
    for module in (demo.rules_api, demo.evidence_api, demo.receipts_api, demo.app):
        importlib.reload(module)
    yield TestClient(demo.app.app)


@pytest.mark.parametrize("path", ["/", "/rules", "/evidence", "/receipt"])
def test_every_page_still_renders_with_no_content(empty_content, path):
    assert empty_content.get(path).status_code == 200


@pytest.mark.parametrize(
    "endpoint,key,floor",
    [
        # The scenario listing is never fully empty: the built-in fixture
        # scenario ships with the demo (see the design-change test below), so
        # an empty corpus lists exactly that one, and nothing else.
        ("/api/scenarios", None, 1),
        ("/api/rules/packs", "packs", 0),
        ("/api/receipts/corpus", "receipts", 0),
    ],
)
def test_every_listing_reports_empty_rather_than_failing(empty_content, endpoint, key, floor):
    response = empty_content.get(endpoint)
    assert response.status_code == 200, response.text
    body = response.json()
    items = body if key is None else (body.get(key) or [])
    assert len(items) == floor


def test_the_built_in_fixture_scenario_ships_with_the_demo(empty_content):
    """DESIGN CHANGE with the examples/ move, on purpose: the built-in fixture
    scenario is served from this repository's committed `spec/examples` — the
    contract's own worked example — and no longer disappears under a custom
    content root. It could not stay content-derived: the repo's default root
    is now `examples/`, which does not contain `spec/`, so a content-derived
    path would have taken the built-in away from the *default* deployment.
    A deployment with an empty corpus therefore still has one honest thing to
    show, and `git rm -r examples/` leaves the demo demonstrating the contract
    rather than nothing at all."""
    import demo.app

    scenario = demo.app._build_fixture_scenario()
    assert scenario is not None
    assert scenario["extraction"]["source"] == "fixture"
