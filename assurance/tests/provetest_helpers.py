"""Shared fixtures for the Z3 static pack verifier tests.

A module rather than a conftest.py: test directories carry no `__init__.py`,
so pytest imports by basename and identical filenames collide across suites
(CLAUDE.md, "Test helpers").

Toy packs are built here rather than committed as fixture files because each
one exists to isolate exactly one encoding question, and a dict beside its
assertion is easier to read than a YAML file three directories away.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from duly_kernel.ir import load_pack

REPO_ROOT = Path(__file__).resolve().parents[2]
RULEPACKS = REPO_ROOT / "examples" / "rulepacks"
ONTOLOGIES = REPO_ROOT / "examples" / "ontologies"
DMN_PACK = REPO_ROOT / "examples" / "dmn" / "trid-fee-tolerance.pack.yaml"

# Example content, discovered rather than listed — and **absent is a legal
# state**. `rulepacks/` is teaching content an adopter deletes, and a
# module-level `iterdir()` on it turns that deletion into a *collection error*:
# every test in this file stops existing, including the ones that have nothing
# to do with the packs. A test that cannot be collected is worse than one that
# fails, because pytest reports the count that remains and nothing says what
# left.
COMMITTED_PACKS = (
    sorted(p.name for p in RULEPACKS.iterdir() if (p / "pack.yaml").is_file())
    if RULEPACKS.is_dir()
    else []
)

z3_only = pytest.mark.z3

try:  # pragma: no cover - the marker skips when this fails
    import z3 as _z3  # noqa: F401

    HAVE_Z3 = True
except ImportError:  # pragma: no cover
    HAVE_Z3 = False


def repo_registry():
    from duly_conformance.registry import load_repo_registry

    return load_repo_registry(ONTOLOGIES)


def committed_pack(name: str) -> dict:
    return load_pack(RULEPACKS / name / "pack.yaml")


def dmn_pack() -> dict:
    return load_pack(DMN_PACK)


def perturbed(pack: dict, old: str, new: str) -> dict:
    """A copy of `pack` with `old` replaced by `new` in every guard.

    The perturbation lever spec/dmn.md measures its fixture-boundedness with.
    """
    out = copy.deepcopy(pack)
    for rule in out["rules"]:
        rule["when"] = [c.replace(old, new) for c in (rule.get("when") or [])]
    return out


# ---------------------------------------------------------------------------
# Toy packs
# ---------------------------------------------------------------------------


def _rule(rid: str, priority: int, when: list[str], value, *, given=None, overrides=None):
    # effectiveFrom is the encoding's own lower date bound so that a toy pack
    # with a default row is *totally* covered: any later date would leave the
    # pre-effective region uncovered, which is true but not what these tests
    # are about.
    rule = {
        "id": rid,
        "version": "1.0.0",
        "priority": priority,
        "citation": {"text": "Toy pack for encoding tests"},
        "effectiveFrom": "1900-01-01",
        "given": given or {"thing": {"entityType": "toy:Thing"}},
        "then": {"entity": "thing", "attribute": "toy:verdict", "value": value},
    }
    if when:
        rule["when"] = when
    if overrides:
        rule["overrides"] = overrides
    return rule


def _pack(name: str, rules: list[dict]) -> dict:
    return {
        "pack": {"name": name, "version": "1.0.0"},
        "decisions": [
            {"attribute": "toy:verdict", "entityType": "toy:Thing",
             "question": "What is the verdict?"}
        ],
        "rules": rules,
    }


TRUE = {"kind": "boolean", "value": True}
FALSE = {"kind": "boolean", "value": False}


def overlapping_numeric_pack() -> dict:
    """Two same-priority rules split by overlapping numeric ranges.

    The kernel's syntactic check accepts nothing here — `overrides` is what
    keeps the pack loadable — and the overlap is real: `amount == 10`.
    """
    given = {
        "thing": {"entityType": "toy:Thing"},
        "amount": {"attribute": "toy:amount"},
    }
    return _pack(
        "toy-overlapping-ranges",
        [
            _rule("TOY-LOW", 100, ["amount <= 10"], TRUE, given=given),
            _rule("TOY-HIGH", 100, ["amount >= 10"], FALSE, given=given,
                  overrides=["TOY-LOW"]),
        ],
    )


def disjoint_numeric_pack() -> dict:
    """The same shape, made genuinely disjoint — a proof the kernel cannot see."""
    given = {
        "thing": {"entityType": "toy:Thing"},
        "amount": {"attribute": "toy:amount"},
    }
    return _pack(
        "toy-disjoint-ranges",
        [
            _rule("TOY-LOW", 100, ["amount < 10"], TRUE, given=given),
            _rule("TOY-HIGH", 100, ["amount >= 10"], FALSE, given=given,
                  overrides=["TOY-LOW"]),
        ],
    )


def boolean_split_pack() -> dict:
    """`flag == true` / `flag == false`: the CLAUDE.md gotcha, provable here."""
    given = {
        "thing": {"entityType": "toy:Thing"},
        "flag": {"attribute": "toy:flag"},
    }
    return _pack(
        "toy-boolean-split",
        [
            _rule("TOY-ON", 100, ["flag == true"], TRUE, given=given),
            _rule("TOY-OFF", 100, ["flag == false"], FALSE, given=given,
                  overrides=["TOY-ON"]),
        ],
    )


def derived_guard_pack() -> dict:
    """Disjointness that turns on a *derived* value.

    `_equality_guards` inspects only `attribute` bindings, so the kernel
    cannot see this one at all (spec/dmn.md M6, CLAUDE.md's first gotcha).
    """
    return {
        "pack": {"name": "toy-derived-guard", "version": "1.0.0"},
        "decisions": [
            {"attribute": "toy:verdict", "entityType": "toy:Thing",
             "question": "What is the verdict?"}
        ],
        "rules": [
            {
                "id": "TOY-CAT",
                "version": "1.0.0",
                "priority": 0,
                "citation": {"text": "Toy pack"},
                "effectiveFrom": "1900-01-01",
                "given": {
                    "thing": {"entityType": "toy:Thing"},
                    "amount": {"attribute": "toy:amount"},
                },
                "when": ["amount > 100"],
                "then": {
                    "entity": "thing", "attribute": "toy:band",
                    "value": {"kind": "string", "value": "High"},
                },
            },
            {
                "id": "TOY-CAT-LOW",
                "version": "1.0.0",
                "priority": 1,  # distinct only to keep the kernel's own check happy
                "citation": {"text": "Toy pack"},
                "effectiveFrom": "1900-01-01",
                "given": {
                    "thing": {"entityType": "toy:Thing"},
                    "amount": {"attribute": "toy:amount"},
                },
                "when": ["amount <= 100"],
                "then": {
                    "entity": "thing", "attribute": "toy:band",
                    "value": {"kind": "string", "value": "Low"},
                },
            },
            _rule(
                "TOY-HIGH", 100, ['band == "High"'], TRUE,
                given={
                    "thing": {"entityType": "toy:Thing"},
                    "band": {"derived": "toy:band"},
                },
                overrides=["TOY-LOW"],
            ),
            _rule(
                "TOY-LOW", 100, ['band == "Low"'], FALSE,
                given={
                    "thing": {"entityType": "toy:Thing"},
                    "band": {"derived": "toy:band"},
                },
            ),
        ],
    }


def uncovered_pack() -> dict:
    """A UNIQUE-style table with a hole: nothing concludes for `"C"`."""
    given = {
        "thing": {"entityType": "toy:Thing"},
        "grade": {"attribute": "toy:grade"},
    }
    return _pack(
        "toy-uncovered",
        [
            _rule("TOY-A", 100, ['grade == "A"'], TRUE, given=given),
            _rule("TOY-B", 100, ['grade == "B"'], FALSE, given=given),
        ],
    )


def covered_pack() -> dict:
    """The same table with a default row: total coverage."""
    given = {
        "thing": {"entityType": "toy:Thing"},
        "grade": {"attribute": "toy:grade"},
    }
    return _pack(
        "toy-covered",
        [
            _rule("TOY-DEF", 0, [], FALSE),
            _rule("TOY-A", 100, ['grade == "A"'], TRUE, given=given),
            _rule("TOY-B", 100, ['grade == "B"'], FALSE, given=given),
        ],
    )


def string_order_pack() -> dict:
    """One rule inside the fragment, one outside it.

    String ordering is deliberately not encoded: the finite-domain index
    preserves equality but not lexicographic order, so encoding `<` would be
    a silent approximation. The pair verdict must say so by name.
    """
    given = {
        "thing": {"entityType": "toy:Thing"},
        "grade": {"attribute": "toy:grade"},
    }
    return _pack(
        "toy-string-ordering",
        [
            _rule("TOY-A", 100, ['grade == "A"'], TRUE, given=given),
            _rule("TOY-ORD", 100, ['grade < "B"'], FALSE, given=given,
                  overrides=["TOY-A"]),
        ],
    )


def untypable_pack() -> dict:
    """Two symbols the ontology does not type and use does not disambiguate."""
    given = {
        "thing": {"entityType": "toy:Thing"},
        "stamp": {"attribute": "toy:stamp"},
        "other": {"attribute": "toy:other"},
    }
    return _pack(
        "toy-untypable",
        [
            _rule("TOY-CMP", 100, ["stamp < other"], TRUE, given=given),
            _rule("TOY-DEF", 0, [], FALSE),
        ],
    )
