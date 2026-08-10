"""Shared fixtures for the what-if suite.

A module rather than a conftest.py: test directories carry no `__init__.py`,
so pytest imports by basename and identical filenames collide across suites
(CLAUDE.md, "Test helpers").

Two corpora, and the difference is the whole point of the split.

**`fixtures/`** is the toolkit's own: an invented domain, committed cases,
its own ontology. Every test asserting *solver* behaviour runs on it, so
`git rm -r examples/` leaves those tests failing-or-passing rather than
silently uncollected (CLAUDE.md, "A test that would still pass with its
subject deleted is not a test").

**`golden/`** is example content. What stays pointed at it are the tests
whose *subject* is a teaching pack's boundary answer — the 45-day notice
date, the TRID cure, the TILA business-day arithmetic. Those numbers are
README claims about the shipped packs, and they move with the packs.

Cases in both come from committed corpora rather than from hand-built dicts,
deliberately: a boundary asserted here is pinned against a case nothing may
silently change.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "golden" / "cases"
ONTOLOGIES = REPO_ROOT / "ontologies"

# The toolkit corpus. `fixtures/ontology` carries only `duly-fixture`, which
# the top-level `ontologies/` deliberately does not — the fixture registry is
# not a subset of the example one, and pointing a fixture query at
# `ontologies/` would silently drop to the no-registry path.
FIXTURES = REPO_ROOT / "fixtures"
FIXTURE_CASES = FIXTURES / "cases"
FIXTURE_ONTOLOGIES = FIXTURES / "ontology"

z3_only = pytest.mark.z3

try:  # pragma: no cover - the marker skips when this fails
    import z3 as _z3  # noqa: F401

    HAVE_Z3 = True
except ImportError:  # pragma: no cover
    HAVE_Z3 = False

needs_z3 = pytest.mark.skipif(not HAVE_Z3, reason="z3-solver is not installed")


def _registry(directory: Path):
    from duly_conformance.registry import load_repo_registry

    return load_repo_registry(directory)


def repo_registry():
    """The example content's ontology registry (`ontologies/`)."""
    return _registry(ONTOLOGIES)


def fixture_registry():
    """The toolkit corpus's registry (`fixtures/ontology`)."""
    return _registry(FIXTURE_ONTOLOGIES)


def _load(root: Path, case_id: str):
    directory = root / case_id
    case = yaml.safe_load((directory / "case.yaml").read_text())
    facts = [
        json.loads(p.read_text()) for p in sorted((directory / "facts").glob("*.json"))
    ]
    pack = yaml.safe_load((REPO_ROOT / str(case["pack"])).read_text())
    return case, facts, pack


def _query(root: Path, case_id: str, free: str, **overrides):
    from duly_whatif.query import Query

    case, facts, pack = _load(root, case_id)
    kwargs = dict(
        facts=facts,
        pack=pack,
        as_of_effective=str(case["asOfEffective"]),
        as_of_knowledge=str(case["asOfKnowledge"]),
        decision=str(case["question"]),
        free=free,
    )
    kwargs.update(overrides)
    return Query(**kwargs)


# --- the toolkit corpus ------------------------------------------------------


def load_fixture_case(case_id: str):
    """(case dict, facts, pack) for a committed fixture case."""
    return _load(FIXTURE_CASES, case_id)


def fixture_query(case_id: str, free: str, **overrides):
    """A `Query` over a fixture case, with the case supplying every default."""
    return _query(FIXTURE_CASES, case_id, free, **overrides)


def fixture_solve(case_id: str, free: str, **overrides):
    from duly_whatif.query import solve

    return solve(fixture_query(case_id, free, **overrides), fixture_registry())


# --- example content (moves with examples/) ----------------------------------


def load_case(case_id: str):
    """(case dict, facts, pack) for a committed golden case."""
    return _load(GOLDEN, case_id)


def query_for(case_id: str, free: str, **overrides):
    """A `Query` over a golden case, with the case supplying every default."""
    return _query(GOLDEN, case_id, free, **overrides)


def solve_for(case_id: str, free: str, **overrides):
    from duly_whatif.query import solve

    return solve(query_for(case_id, free, **overrides), repo_registry())


def perturbed(pack: dict, old: str, new: str) -> dict:
    """A copy of `pack` with `old` replaced by `new` in every guard.

    The same perturbation lever `assurance/tests/provetest_helpers.py` uses,
    and spec/dmn.md measures its fixture-boundedness with: `> disclosed`
    becoming `>= disclosed` moves exactly one boundary and nothing else.
    """
    out = copy.deepcopy(pack)
    for rule in out["rules"]:
        if rule.get("when"):
            rule["when"] = [c.replace(old, new) for c in rule["when"]]
    return out


TRUE = {"kind": "boolean", "value": True}
FALSE = {"kind": "boolean", "value": False}


def money(amount: str, currency: str = "USD") -> dict:
    return {"kind": "money", "amount": amount, "currency": currency}
