"""Shared fixtures for the what-if suite.

A module rather than a conftest.py: test directories carry no `__init__.py`,
so pytest imports by basename and identical filenames collide across suites
(CLAUDE.md, "Test helpers").

Cases come from the committed golden corpus rather than from hand-built
dicts, deliberately. A what-if answer is only interesting if it is an answer
about the artifacts the repo actually ships, and the corpus is the thing the
replay verifier already holds byte-stable — so a boundary asserted here is
pinned against a case nothing may silently change.
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

z3_only = pytest.mark.z3

try:  # pragma: no cover - the marker skips when this fails
    import z3 as _z3  # noqa: F401

    HAVE_Z3 = True
except ImportError:  # pragma: no cover
    HAVE_Z3 = False

needs_z3 = pytest.mark.skipif(not HAVE_Z3, reason="z3-solver is not installed")


def repo_registry():
    from duly_conformance.registry import load_repo_registry

    return load_repo_registry(ONTOLOGIES)


def load_case(case_id: str):
    """(case dict, facts, pack) for a committed golden case."""
    directory = GOLDEN / case_id
    case = yaml.safe_load((directory / "case.yaml").read_text())
    facts = [
        json.loads(p.read_text()) for p in sorted((directory / "facts").glob("*.json"))
    ]
    pack = yaml.safe_load((REPO_ROOT / str(case["pack"])).read_text())
    return case, facts, pack


def query_for(case_id: str, free: str, **overrides):
    """A `Query` over a golden case, with the case supplying every default."""
    from duly_whatif.query import Query

    case, facts, pack = load_case(case_id)
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
