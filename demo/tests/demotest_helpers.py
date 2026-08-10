"""A demo content root built from `fixtures/`.

A module rather than a conftest.py: test directories carry no `__init__.py`,
so pytest imports by basename and identical filenames collide across suites
(CLAUDE.md, "Test helpers").

The four demo surfaces are **toolkit** (M5 plan, D2): each reads whatever
packs, scenarios, cases and receipts exist rather than any particular ones.
Their suites should therefore assert against content the toolkit owns — and
`fixtures/` is that content, but it is laid out as a *corpus*
(`cases/`, `receipts/`, `pack.yaml`) rather than as the repository shape the
demo reads (`golden/`, `rulepacks/<name>/pack.yaml`, `ontologies/`).

So the mapping is performed here, in code, rather than committed as a second
copy of the fixtures under a different layout. Two reasons. A committed copy
would be two artifacts that must not disagree, which is the defect
`duly_core` exists to remove one level down. And writing the mapping out makes
it *readable*: `rulepacks/<pack.name>/pack.yaml` is not an arbitrary path, it
is what a receipt's `rulePack.name` resolves to, and seeing the assembly is
seeing why.
"""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"

#: The fixture case whose receipt has a nested derivation, a defeated
#: presumption and pinned input facts — the shape a receipt viewer has
#: something to show for. `fx-0002` decides on the default alone and pins
#: nothing, which is a different and thinner shape.
CASE = "fx-0001"

#: The case carrying a live `low_confidence` abstention.
ABSTAINING_CASE = "fx-0003"

#: The scenario: one document, its rendition, and three facts grounded in
#: character spans of that rendition — one of them below the pack's confidence
#: floor, so the review arc has something to resolve. The corpus cases use
#: attestation grounding, which leaves the span machinery untested.
SCENARIO = "fx-0005"

#: The scenario's review arc, as `demo/app.py` names it (`REVIEW_ID_SUFFIX`).
#: Derived there from whichever scenario opts in, so it is derived here too.
REVIEW_SCENARIO = f"{SCENARIO}-review"

#: The case id `duly_review.golden` hands out first. `next_review_case_id`
#: scans the corpus for `review-*` and takes the first free slot, so in a
#: content root built fresh the first export would be `review-0001` — the id
#: this repository's own `golden/` has held since M3. `build_content_root`
#: seeds it (see below) so the fixture corpus poses the same question.
SEEDED_REVIEW_CASE = "review-0001"


def build_content_root(root: Path) -> Path:
    """Lay `fixtures/` out as a demo content root under `root`.

    Returns `root`, which is what `DULY_DEMO_CONTENT` should be set to.
    """
    pack = yaml.safe_load((FIXTURES / "pack.yaml").read_text())
    pack_name = pack["pack"]["name"]

    shutil.copytree(FIXTURES / "cases", root / "golden" / "cases")
    shutil.copytree(FIXTURES / "receipts", root / "golden" / "receipts")

    # A corpus that already holds `review-0001`, because this repository's does
    # and the export path's *interesting* behaviour is the collision:
    # `duly_review.golden.next_review_case_id` takes the first free `review-*`
    # slot, so a fresh corpus hands out `review-0001` and never exercises the
    # skip. `fx-0004` is the honest thing to seed it with — it is already the
    # post-review case, the same shape a resolution exports.
    #
    # The receipt is copied **byte-for-byte**: it is content-addressed, so an
    # edit is a forgery, and its own `caseId` therefore still reads
    # `case:fixture:fx-0003` (the correction supersedes an fx-0003 fact). That
    # is not a mismatch to fix — a golden case's *name* and the case id inside
    # its receipt are different namespaces here, and every corpus reader keys
    # off the filename. The one line that must move is `case.yaml`'s `id`,
    # which is what `duly_assurance.verify` resolves the receipt filename from:
    # left at `fx-0004` this directory would silently verify fx-0004 twice and
    # never open the receipt beside it.
    seeded = root / "golden" / "cases" / SEEDED_REVIEW_CASE
    shutil.copytree(FIXTURES / "cases" / "fx-0004", seeded)
    seeded_yaml = seeded / "case.yaml"
    seeded_yaml.write_text(
        seeded_yaml.read_text().replace("id: fx-0004", f"id: {SEEDED_REVIEW_CASE}")
    )
    shutil.copy(
        FIXTURES / "receipts" / "fx-0004.json",
        root / "golden" / "receipts" / f"{SEEDED_REVIEW_CASE}.json",
    )

    # Each case names the pack it was decided under. In `fixtures/` that is the
    # repo-relative `fixtures/pack.yaml`; in a content root it is where the pack
    # actually sits. The studio matches this string exactly to decide which
    # corpus cases a pack governs, so leaving it un-rewritten does not error —
    # it silently offers zero golden fact sets, which looks like a pack nothing
    # cites rather than like a broken path.
    for case_yaml in (root / "golden" / "cases").glob("*/case.yaml"):
        case_yaml.write_text(
            case_yaml.read_text().replace(
                "pack: fixtures/pack.yaml", f"pack: rulepacks/{pack_name}/pack.yaml"
            )
        )

    # A receipt names its pack by name, and the surfaces resolve that name to
    # `rulepacks/<name>/pack.yaml`. Placing it anywhere else would make every
    # receipt here report `pack-moved`, which is a real outcome and not the one
    # under test.
    pack_dir = root / "rulepacks" / pack_name
    pack_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "pack.yaml", pack_dir / "pack.yaml")

    # The pack's declared cases, with their `factsFrom` rewritten from
    # repo-relative (`fixtures/cases/...`, correct where the file is committed)
    # to the content root's layout. Same rewrite, same reason, as the scenario
    # manifest's `rulePack` below.
    expected = (FIXTURES / "expected.yaml").read_text()
    (pack_dir / "expected.yaml").write_text(
        expected.replace("factsFrom: fixtures/cases/", "factsFrom: golden/cases/")
    )

    shutil.copytree(FIXTURES / "ontology", root / "ontologies")

    # The DMN inputs the rule studio's import panel reads, under the name it
    # discovers them by. One table that compiles and one that is refused: the
    # refusal is the more important of the two, because "a refusal is a result,
    # not a 500" is the claim the panel exists to make.
    shutil.copytree(FIXTURES / "dmn", root / "dmn" / "examples")

    # The scenario, under the name the demo discovers starters by. Its
    # `rulePack` is repo-relative (`fixtures/pack.yaml`) in the committed
    # artifact, because that is what it resolves to when the demo serves this
    # repository; inside a content root the pack lives where a receipt's
    # `rulePack.name` resolves, so the reference is rewritten to match.
    scenario_dir = root / "starters" / SCENARIO
    shutil.copytree(FIXTURES / "scenario", scenario_dir)
    manifest = json.loads((scenario_dir / "scenario.json").read_text())
    manifest["rulePack"] = f"rulepacks/{pack_name}/pack.yaml"
    (scenario_dir / "scenario.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )

    # The extraction targets, under the one directory the demo indexes them
    # from: `starters/tools/targets/*.json`, keyed by each file's `documentId`
    # *field* rather than its name. Without them the store-backed runtime does
    # not fail — `_ingest_starter_case` returns None the moment a document has
    # no targets entry, and `_ingest_review_case` simply returns — so the
    # scenario falls back to its committed disk facts and the review arc does
    # not appear at all. A deployment with no arc and a deployment with no
    # targets look identical from the outside, which is why this mapping is
    # here rather than assumed.
    shutil.copytree(FIXTURES / "targets", root / "starters" / "tools" / "targets")
    return root


def reload_demo() -> None:
    """Rebind every demo module's content roots to the current environment.

    The surfaces read `DULY_DEMO_CONTENT` at *import*, which is right for a
    server — import is startup — so moving the environment after import moves
    nothing until the modules are reloaded, in dependency order.

    Shared rather than copied per suite, and that is the whole point. This
    teardown is the reason converting one suite to a fixture content root once
    turned 0 failures into 50 across the rest of the directory: `monkeypatch`
    unsets the variable and un-reloads nothing, so a suite that reloads on setup
    and not on teardown leaves every later file serving a temp directory that no
    longer exists. A guard rewritten per call site is a guard that will
    eventually be rewritten wrong.
    """
    import demo.app
    import demo.content
    import demo.evidence_api
    import demo.receipts_api
    import demo.rules_api

    importlib.reload(demo.content)
    for module in (demo.rules_api, demo.evidence_api, demo.receipts_api, demo.app):
        importlib.reload(module)
