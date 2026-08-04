"""The demo is toolkit, and its content is configuration.

M5 decision D2: the four surfaces are toolkit rather than teaching content,
because each reads *whatever* packs, scenarios, cases and receipts exist rather
than any particular ones. The test of that claim is not that they work here —
they always did — but that they still stand up when pointed somewhere with
nothing in it, and say so. A surface that 500s on an empty corpus was teaching
content all along.

This is also Phase 3's acceptance criterion arriving early: after
`git rm -r examples/`, this is what "a working, empty toolkit" has to mean.
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


def test_the_default_root_is_this_repository():
    """So `uvicorn demo.app:app` needs no configuration, as before."""
    assert ContentRoots.from_env({}).root == REPO_ROOT


def test_the_env_var_moves_every_root_together(tmp_path):
    content = ContentRoots.from_env({ENV_VAR: str(tmp_path)})
    assert content.root == tmp_path.resolve()
    for name in ("starters", "golden", "rulepacks", "ontologies"):
        assert getattr(content, name).parent == tmp_path.resolve()
    assert content.spec_examples == tmp_path.resolve() / "spec" / "examples"
    assert content.dmn_examples == tmp_path.resolve() / "dmn" / "examples"


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
    "endpoint,key",
    [
        ("/api/scenarios", None),
        ("/api/rules/packs", "packs"),
        ("/api/receipts/corpus", "receipts"),
    ],
)
def test_every_listing_reports_empty_rather_than_failing(empty_content, endpoint, key):
    response = empty_content.get(endpoint)
    assert response.status_code == 200, response.text
    body = response.json()
    items = body if key is None else (body.get(key) or [])
    assert len(items) == 0


def test_the_built_in_fixture_scenario_is_content_too(empty_content):
    """It reads the committed spec examples, so a deployment pointed at its own
    corpus does not have it. Absent, not fabricated: `_build_fixture_scenario`
    returns None rather than raising, because a missing *demonstration* must
    not read as a broken server."""
    import demo.app

    assert demo.app._build_fixture_scenario() is None


def test_the_repo_default_still_finds_everything():
    """The other half of the claim: configurable did not mean broken here."""
    assert CONTENT.rulepacks.is_dir()
    assert CONTENT.golden.is_dir()
    assert len(list(CONTENT.rulepacks.glob("*/pack.yaml"))) == 6
