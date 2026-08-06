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

#: The scenario: one document, its rendition, and two facts grounded in
#: character spans of that rendition — one of them below the pack's confidence
#: floor, so the review arc has something to resolve. The corpus cases use
#: attestation grounding, which leaves the span machinery untested.
SCENARIO = "fx-0005"


def build_content_root(root: Path) -> Path:
    """Lay `fixtures/` out as a demo content root under `root`.

    Returns `root`, which is what `DULY_DEMO_CONTENT` should be set to.
    """
    pack = yaml.safe_load((FIXTURES / "pack.yaml").read_text())
    pack_name = pack["pack"]["name"]

    shutil.copytree(FIXTURES / "cases", root / "golden" / "cases")
    shutil.copytree(FIXTURES / "receipts", root / "golden" / "receipts")

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
