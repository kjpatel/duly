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

    # A receipt names its pack by name, and the surfaces resolve that name to
    # `rulepacks/<name>/pack.yaml`. Placing it anywhere else would make every
    # receipt here report `pack-moved`, which is a real outcome and not the one
    # under test.
    pack_dir = root / "rulepacks" / pack_name
    pack_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "pack.yaml", pack_dir / "pack.yaml")

    shutil.copytree(FIXTURES / "ontology", root / "ontologies")

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
