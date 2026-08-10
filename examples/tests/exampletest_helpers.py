"""Shared roots and loaders for the example content's own test suite.

A module rather than a `conftest.py`: test directories in this repo carry no
`__init__.py`, so pytest imports by basename and two files called `conftest`
collide across suites (CLAUDE.md, "Test helpers").

**Everything under `examples/tests/` is the example content's own test suite.**
The toolkit's suites live beside the code they test and run on
[`fixtures/`](../../fixtures/README.md); these run on the teaching content in
`examples/` and assert what *it* says — the NY notice's 45-day boundary, the
TRID cure amount, the committed starter facts, the grandfathered rule ids.
They exist only while `examples/` does: `git rm -r examples/` deletes the
claims and the tests that check them in one move, which is the whole point of
putting them here rather than leaving them to pass vacuously over an empty
glob (CLAUDE.md, "A test that would still pass with its subject deleted").

Run them with:

    uv run pytest examples/tests -q

Every path below is derived from this file's own location, so the tree moves
as a unit. `EXAMPLES` is also a demo/corpus **content root**: `golden/`,
`rulepacks/`, `starters/`, `ontologies/` and `dmn/` sit directly under it, and
the repo-relative references inside committed artifacts (`case.yaml`'s `pack:`,
`expected.yaml`'s `factsFrom:`) resolve against it rather than against the
repository root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

#: The example content root: `golden/`, `rulepacks/`, `starters/`,
#: `ontologies/`, `dmn/`.
EXAMPLES = Path(__file__).resolve().parents[1]

#: The repository, for the few things that legitimately live outside the
#: example tree — `spec/` demos executed as tests, chiefly.
REPO_ROOT = Path(__file__).resolve().parents[2]

RULEPACKS = EXAMPLES / "rulepacks"
STARTERS = EXAMPLES / "starters"
GOLDEN = EXAMPLES / "golden"
GOLDEN_CASES = GOLDEN / "cases"
ONTOLOGIES = EXAMPLES / "ontologies"
DMN = EXAMPLES / "dmn"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_facts(directory: Path) -> list[dict]:
    """Every committed GroundedFact in `directory` (receipts skipped)."""
    facts = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" in doc:
            continue
        facts.append(doc)
    return facts


# --- optional dependencies ---------------------------------------------------
#
# The marked tests here keep the posture they had in their home suites: the
# marker declares what they exercise, the skipif keeps a core run green. Both
# markers are declared in the repository's `pyproject.toml`, which is where
# they resolved from before the move as well.

try:  # pragma: no cover - the skipif covers the other branch
    import z3 as _z3  # noqa: F401

    HAVE_Z3 = True
except ImportError:  # pragma: no cover
    HAVE_Z3 = False

needs_z3 = pytest.mark.skipif(not HAVE_Z3, reason="z3-solver is not installed")


# --- the DMN teaching corpus -------------------------------------------------
#
# The TRID decision table is the one an adopter reads and then deletes. Only
# the two suites whose *subject* is that content reach for these —
# `test_equivalence.py` (does the compiled pack decide what the hand-written
# one decides?) and `test_refusals.py` (does every committed refusal example
# refuse?). A test about the *compiler* belongs on `dmn/tests/`'s fixture
# constants instead, or deleting this tree leaves it passing over an empty
# glob (CLAUDE.md).

REFUSALS = DMN / "refusals"

TRID_DMN = DMN / "trid-fee-tolerance.dmn"
TRID_COMPILED = DMN / "trid-fee-tolerance.pack.yaml"
TRID_HAND_WRITTEN = RULEPACKS / "trid-fee-tolerance-us-federal" / "pack.yaml"
TRID_EXPECTED = RULEPACKS / "trid-fee-tolerance-us-federal" / "expected.yaml"
TRID_FACTS = STARTERS / "trid" / "facts"


def value_kinds(ontologies: Path) -> dict[str, str]:
    """Attribute CURIE -> duly value kind, from a directory of ontologies.

    The compiler takes this mapping rather than a path, so it never reaches
    for a directory of its own choosing. Tests and the spec demo are
    repo-resident and may supply a repo directory; a compiler that did the
    same would be assuming a layout it cannot rely on.

    It exists because of the one defect DMN cannot self-diagnose: a money
    column tested against a bare number. DMN's `typeRef` is the author's
    declaration and duly's value kinds are not DMN's.

    A second copy of `dmntest_helpers.value_kinds`, and deliberately: the
    toolkit suite must keep its own when this tree is deleted, and neither
    directory can import the other's helper module.
    """
    from duly_conformance import load_repo_registry

    kinds: dict[str, str] = {}
    for ontology in load_repo_registry(ontologies):
        for klass in ontology.classes.values():
            for slot in klass.slots.values():
                kinds[slot.curie] = slot.kind
    return kinds


def refusal_value_kinds() -> dict[str, str]:
    """The mapping the committed refusal *examples* pin, from `ontologies/`."""
    return value_kinds(ONTOLOGIES)
