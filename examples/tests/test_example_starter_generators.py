"""Re-running a starter's `make_documents.py` must change nothing.

The example content's own test suite: its subject is the six committed
starters and the scripts that build them, and `git rm -r examples/` deletes
both in one move.

A generator here is *two* things at once, and only the first was safe. It
renders PDFs and renditions — deterministic since `invariant=1`, and long
proven byte-stable. It also writes `scenario.json`, and it wrote it from a
literal inside itself, so every re-run reverted whatever the manifest had
grown since that literal was last touched: `domain` on all six scenarios,
`demoExtractor` on county-recording (the stub pin without which a live
Docling run silently overwrites the scripted below-floor confidence the
review arc depends on), and the entire `reviewArc` block on notice-ny. The
same drift ran the other way too — tila-rescission's literal went on naming
two rescission-period fact files that had been deleted from its manifest and
from the disk.

None of it was visible in CI, because nothing re-ran the generators. This
test does, into a copy of the tree, and asserts the bytes.
"""

from __future__ import annotations

import importlib.util
import json
import datetime as _date
import shutil
import subprocess
import sys

import pytest

from exampletest_helpers import STARTERS

#: The generators, and the scenarios each one writes. notice-ny and trid have
#: no module of their own: they predate the shared helpers and are written by
#: `tools/make_documents.py`'s own `main()`.
GENERATORS = {
    "tools/make_documents.py": ("notice-ny", "trid"),
    "county-recording/make_documents.py": ("county-recording",),
    "esign-package/make_documents.py": ("esign-package",),
    "ron-closing/make_documents.py": ("ron-closing",),
    "tila-rescission/make_documents.py": ("tila-rescission",),
}


def _shared_module():
    """`tools/make_documents.py`, loaded by path — two modules in this tree
    are called make_documents, so a plain import is ambiguous."""
    spec = importlib.util.spec_from_file_location(
        "duly_starter_make_documents_under_test", STARTERS / "tools" / "make_documents.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def starters_copy(tmp_path_factory):
    """A throwaway copy of `examples/starters/`, so a generator run under test
    writes there and never into the committed tree."""
    root = tmp_path_factory.mktemp("starters") / "starters"
    shutil.copytree(STARTERS, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _run(root, script):
    proc = subprocess.run(
        [sys.executable, str(root / script)],
        capture_output=True,
        text=True,
        cwd=root.parent,
    )
    assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"
    return proc


def test_every_generator_and_scenario_on_disk_is_covered():
    """`GENERATORS` is a literal, not a glob — a parametrize over the
    filesystem yields zero cases when the tree is deleted and reports that as
    success (CLAUDE.md). The cost is that it can go stale, so this is the line
    that fails when a seventh starter arrives."""
    on_disk = {
        str(p.relative_to(STARTERS)) for p in STARTERS.rglob("make_documents.py")
    }
    assert on_disk == set(GENERATORS)
    covered = {s for scenarios in GENERATORS.values() for s in scenarios}
    assert covered == {p.parent.name for p in STARTERS.glob("*/scenario.json")}


@pytest.mark.parametrize("script,scenarios", sorted(GENERATORS.items()))
def test_regenerating_a_starter_changes_nothing(starters_copy, script, scenarios):
    """Documents, renditions and manifest, all byte-for-byte. The manifest is
    the half that was not holding: it is merged into the committed file now,
    not written over it."""
    proc = _run(starters_copy, script)
    assert "warning:" not in proc.stderr, proc.stderr
    for scenario in scenarios:
        for name in ("scenario.json",):
            regenerated = (starters_copy / scenario / name).read_bytes()
            committed = (STARTERS / scenario / name).read_bytes()
            assert regenerated == committed, f"{scenario}/{name} changed on re-run"
        for sub in ("documents", "renditions"):
            for path in sorted((STARTERS / scenario / sub).iterdir()):
                mirror = starters_copy / scenario / sub / path.name
                assert mirror.read_bytes() == path.read_bytes(), mirror


def test_every_manifest_fact_path_exists():
    """The other direction of the same drift: a generator's `facts` literal
    naming a file that is not there. `write_manifest` warns; this fails."""
    for scenario in sorted(p for p in STARTERS.iterdir() if (p / "scenario.json").is_file()):
        manifest = json.loads((scenario / "scenario.json").read_text())
        assert manifest["facts"], scenario.name
        for ref in manifest["facts"]:
            assert (scenario / ref).is_file(), f"{scenario.name}: {ref}"


def test_a_hand_maintained_manifest_key_survives_a_regeneration(tmp_path):
    """The rule, on a scenario dir of its own: a key the generator does not
    emit is the human's and survives; a key it does emit is the script's and
    is authoritative. `domain`, `demoExtractor` and `reviewArc` are the three
    that exist today, and all three were being reverted."""
    root = tmp_path / "starters"
    shutil.copytree(STARTERS, root, ignore=shutil.ignore_patterns("__pycache__"))
    path = root / "ron-closing" / "scenario.json"

    manifest = json.loads(path.read_text())
    manifest["operatorNote"] = "hand-added, and not a key any generator writes"
    manifest["documents"][0]["reviewedBy"] = "a human"
    manifest["title"] = "edited in the JSON, which is the wrong place"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    _run(root, "ron-closing/make_documents.py")

    after = json.loads(path.read_text())
    assert after["operatorNote"] == manifest["operatorNote"]
    assert after["documents"][0]["reviewedBy"] == "a human"
    assert after["domain"] == "mortgage"  # the real one, same mechanism
    # ...and the generator still owns what it writes.
    assert after["title"] == json.loads((STARTERS / "ron-closing" / "scenario.json").read_text())["title"]
    assert after["documents"][0]["sha256"] == manifest["documents"][0]["sha256"]


def test_merge_keeps_the_committed_key_order():
    """A merge that reordered keys would produce a whole-file diff on every
    run, which is indistinguishable from a real change in review."""
    merge = _shared_module().merge_manifest
    existing = {"id": "x", "title": "t", "domain": "d", "documents": [], "facts": ["f"]}
    generated = {"id": "x", "title": "t2", "facts": ["g"], "documents": []}
    merged = merge(existing, generated)
    assert list(merged) == ["id", "title", "domain", "documents", "facts"]
    assert merged["title"] == "t2" and merged["facts"] == ["g"]
    assert merged["domain"] == "d"


def test_merge_matches_documents_by_id_and_takes_the_generator_list():
    """Per-document, the same rule — and membership comes from the generator,
    because the generator is what rendered the files."""
    merge = _shared_module().merge_manifest
    existing = {
        "documents": [
            {"id": "a", "title": "A", "sha256": "old", "note": "hand-added"},
            {"id": "gone", "title": "removed upstream"},
        ]
    }
    generated = {"documents": [{"id": "a", "title": "A", "sha256": "new"}]}
    merged = merge(existing, generated)
    assert merged["documents"] == [
        {"id": "a", "title": "A", "sha256": "new", "note": "hand-added"}
    ]


def test_merge_into_nothing_is_the_generated_manifest():
    """Bootstrapping a new starter: there is no committed manifest to keep."""
    merge = _shared_module().merge_manifest
    generated = {"id": "new", "documents": [{"id": "d", "sha256": "x"}]}
    assert merge({}, generated) == generated


def test_every_starter_declares_the_moment_it_opens_at():
    """Every shipped scenario pins its own effective date.

    Without one the demo falls back to `date.today()`, and a starter whose
    default answer moves with the calendar is a starter whose documented
    verdict can go stale on a day nobody touched the repository. The date is
    also a curation choice the facts cannot express: tila-rescission is only
    interesting *inside* the rescission window, and at any later date it
    answers `fundingPermitted = true` — the dull steady state.
    """
    manifests = sorted(STARTERS.glob("*/scenario.json"))
    assert manifests, "no starters found — this test would pass over an empty glob"

    missing = []
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        as_of = manifest.get("defaultAsOf")
        if not isinstance(as_of, str) or not as_of.strip():
            missing.append(path.parent.name)
            continue
        # Parseable, and a plain day rather than a timestamp: it is what the
        # page's date input opens on.
        _date.date.fromisoformat(as_of)
        assert manifest.get("defaultAsOfWhy"), (
            f"{path.parent.name} pins a date without saying why it is that "
            "date — the sibling field is where that reason lives"
        )
    assert not missing, f"starters with no declared defaultAsOf: {missing}"
