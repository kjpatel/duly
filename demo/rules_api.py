"""Rule Studio — the demo's rule-pack browsing, authoring and testing API.

The decision workspace answers *what did the rules decide about this
document*. The Rule Studio answers the two questions that come next: *what do
the rules actually say*, and *what happens if I change them*.

Three stances hold this file together, and each of them is a refusal:

**Edits are session drafts; the server never writes into `rulepacks/`.** Same
principle as the golden-case export in ``demo/app.py``: committing an artifact
into the repository is a human act, made through a diff a human read. The
studio hands you `pack.yaml` bytes and a diff; `git add` is yours. A draft
lives in this process and dies with it.

**A change is not evaluated until it has been run.** Every editing surface is
wired to the same four instruments the repository already ships — the kernel's
`validate_pack`, the pack's own `expected.yaml` cases, an ad-hoc case you
build by hand, and golden-corpus impact analysis — because a rule edit whose
consequences you have not seen is not an edit, it is a guess. Impact
especially: `expected.yaml` catches a pack that *breaks*, only the corpus
catches a pack whose *meaning moved* (rulepacks/README.md).

**The DMN view is a projection, not a round trip.** `duly_dmn` compiles DMN
into the IR and deliberately does not decompile (spec/dmn.md). The decision
table this module renders is a *view of the IR*, computed with the kernel's
own expression parser; it is the friendliest way to read a rulebase, and it
says out loud where a rule does not fit a table's shape rather than
flattening it until it seems to. Authoring *through* DMN is the compile
endpoint, which is the real, tested, one-way path.

Everything optional degrades honestly: no z3 means the prove/equivalence
panel says so instead of disappearing, and no `duly_dmn` on the path means the
import panel says so instead of erroring.
"""

from __future__ import annotations

import difflib
import io
import json
import re
import threading
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
RULEPACKS_DIR = REPO_ROOT / "rulepacks"
GOLDEN_DIR = REPO_ROOT / "golden"
ONTOLOGIES_DIR = REPO_ROOT / "ontologies"


def _dmn_value_kinds() -> dict[str, str]:
    """Attribute CURIE -> duly value kind, for the DMN import panel.

    Without it the compiler cannot tell that a column is money-valued, so a
    cell like `> 200` imports cleanly and produces a draft that fails at
    adjudication (spec/dmn.md, "Refusal classes"). The studio's whole argument
    is that instruments should disagree on screen rather than in production, so
    the import panel supplies what the compiler needs to refuse it here.

    A missing directory is not an error — the analysis simply loses this one
    check, exactly as it loses enum sharpening above.
    """
    if not ONTOLOGIES_DIR.is_dir():
        return {}
    # Lazy, like every other conformance/kernel reach in this module: the demo
    # must degrade honestly when part of the toolkit is absent, not fail to
    # import.
    from duly_conformance.registry import load_repo_registry  # noqa: PLC0415

    kinds: dict[str, str] = {}
    for ontology in load_repo_registry(ONTOLOGIES_DIR):
        for klass in ontology.classes.values():
            for slot in klass.slots.values():
                kinds[slot.curie] = slot.kind
    return kinds
DMN_EXAMPLES_DIR = REPO_ROOT / "dmn" / "examples"

router = APIRouter(prefix="/api/rules")

SESSION_NOTE = (
    "Drafts live in this demo process only and are never written into "
    "rulepacks/ — download the pack.yaml and commit it yourself."
)

STUDIO_HEADER = [
    "# Drafted in the duly demo Rule Studio.",
    "# Re-emitted from the rule IR: YAML comments in the source pack are NOT",
    "# preserved by structured edits. Read the diff before committing, and see",
    "# rulepacks/README.md for the steps that are still yours (expected.yaml, a",
    "# starter, a golden-corpus generator template, ontology coverage).",
]


# ---------------------------------------------------------------------------
# Session drafts
# ---------------------------------------------------------------------------
#
# slug -> pack.yaml text. A slug that is not a committed pack directory is a
# pack the studio created this session; it has no committed side, so its diff
# is against the empty document and its export is a bundle rather than a file.

_DRAFT_LOCK = threading.Lock()
_DRAFTS: dict[str, str] = {}
_CREATED: set[str] = set()


def reset_drafts() -> None:
    """Drop every session draft (tests call this between cases)."""
    with _DRAFT_LOCK:
        _DRAFTS.clear()
        _CREATED.clear()


def _slug_ok(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug or ""):
        raise HTTPException(
            status_code=422,
            detail=f"Pack slug must be lowercase alphanumeric with dashes: {slug!r}",
        )
    return slug


def _committed_path(slug: str) -> Path | None:
    path = RULEPACKS_DIR / slug / "pack.yaml"
    return path if path.is_file() else None


def _committed_yaml(slug: str) -> str | None:
    path = _committed_path(slug)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _effective_yaml(slug: str) -> str:
    with _DRAFT_LOCK:
        draft = _DRAFTS.get(slug)
    if draft is not None:
        return draft
    committed = _committed_yaml(slug)
    if committed is None:
        raise HTTPException(status_code=404, detail=f"Unknown rule pack: {slug}")
    return committed


def _is_dirty(slug: str) -> bool:
    with _DRAFT_LOCK:
        return slug in _DRAFTS


def _known_slugs() -> list[str]:
    slugs = set()
    if RULEPACKS_DIR.is_dir():
        for path in sorted(RULEPACKS_DIR.glob("*/pack.yaml")):
            slugs.add(path.parent.name)
    with _DRAFT_LOCK:
        slugs |= set(_DRAFTS)
    return sorted(slugs)


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid YAML: {exc}")
    if not isinstance(doc, dict):
        raise HTTPException(status_code=422, detail="A pack must be a YAML mapping")
    return doc


def _validation(pack: dict[str, Any]) -> dict[str, Any]:
    """The kernel's own verdict on a pack — never a second opinion.

    A pack the kernel refuses cannot be adjudicated, so the studio reports the
    refusal verbatim (it already names the rule and field) and keeps the draft:
    an invalid intermediate state is a normal step in editing, and losing the
    text would be the hostile behaviour.
    """
    try:
        from duly_kernel.ir import PackValidationError, validate_pack  # noqa: PLC0415
    except Exception:
        return {"ok": None, "error": None, "note": "Kernel unavailable — pack not validated."}
    try:
        validate_pack(pack)
    except PackValidationError as exc:
        return {"ok": False, "error": str(exc), "note": None}
    except Exception as exc:  # a malformed pack can trip a non-validation path
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "note": None}
    return {"ok": True, "error": None, "note": None}


def _emit_text(pack: dict[str, Any]) -> str:
    """Pack dict -> pack.yaml text, through the DMN compiler's emitter.

    Reusing it rather than writing a second one is the same reflex as
    ``whatif`` reusing ``prove``'s encoder: two emitters would drift, and this
    one already guarantees byte-stability and round-trip equality (its own
    determinism suite asserts ``yaml.safe_load(emit(p)) == p``).
    """
    try:
        from duly_dmn.emit import emit_pack  # noqa: PLC0415
    except Exception:
        return yaml.safe_dump(pack, sort_keys=False, allow_unicode=True)
    return emit_pack(pack, header=STUDIO_HEADER)


def _emit(pack: dict[str, Any]) -> str:
    """`_emit_text` with the round-trip guard, for text that will be stored."""
    text = _emit_text(pack)
    # A structured edit that loses a key is the worst failure this file could
    # have: the draft would validate, adjudicate, and be wrong — an
    # `abstentionPolicy` dropped on re-emission changes every receipt while
    # the diff looks like a comment change. Cheap to check, so checked.
    if yaml.safe_load(text) != pack:
        raise HTTPException(
            status_code=500,
            detail="The pack emitter did not round-trip this pack; refusing to "
            "store a draft that does not say what you edited.",
        )
    return text


def _diff(before: str, after: str, from_label: str, to_label: str) -> list[str]:
    return list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=from_label,
            tofile=to_label,
            n=3,
        )
    )


def _diffs(slug: str, committed: str, draft: str) -> dict[str, list[str]]:
    """Two diffs, because the author is asking two different questions.

    *What did I change* is answered by diffing both sides through the same
    emitter: normalised, it isolates the semantic change to a few lines. *What
    am I about to commit* is answered by diffing the files, which for a
    structured edit also shows every comment the re-emission drops. Showing
    only the first would hide a real loss; showing only the second buries a
    one-value change in three hundred lines of reformatting.
    """
    file_diff = _diff(
        committed, draft,
        f"rulepacks/{slug}/pack.yaml (committed)",
        f"rulepacks/{slug}/pack.yaml (draft)",
    )
    try:
        before = _emit_text(_parse_yaml(committed)) if committed else ""
        after = _emit_text(_parse_yaml(draft))
    except HTTPException:
        # An unparseable side has no normal form; the file diff still stands.
        return {"file": file_diff, "semantic": []}
    return {
        "file": file_diff,
        "semantic": _diff(before, after, "committed (normalised)", "draft (normalised)"),
    }


# ---------------------------------------------------------------------------
# The decision-table projection
# ---------------------------------------------------------------------------
#
# A duly rule is a guarded conclusion; a DMN row is a conjunction of unary
# tests on named inputs plus one output. Where those coincide the projection
# is exact and the grid is the best way to read the pack. Where they do not —
# a guard relating two bindings, e.g. `days_between(mailed, expiration) <
# minDays` — no single column owns the condition, and the row carries it in a
# trailing "cross-input conditions" cell. Naming that is the point: it is the
# same boundary spec/dmn.md draws from the other direction.


def _expr_vars(source: str) -> tuple[set[str], bool]:
    """Variable names referenced by an expression, via the kernel's parser.

    Returns ``(names, parsed)``; ``parsed`` is False when the expression does
    not parse, which the caller renders as an opaque cell rather than guessing.
    """
    try:
        from duly_kernel import expr as kernel_expr  # noqa: PLC0415
    except Exception:
        return set(), False
    try:
        node = kernel_expr.parse(source)
    except Exception:
        return set(), False

    names: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, kernel_expr.Var):
            names.add(n.name)
        elif isinstance(n, kernel_expr.Unary):
            walk(n.operand)
        elif isinstance(n, kernel_expr.Binary):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, kernel_expr.Call):
            for arg in n.args:
                walk(arg)

    walk(node)
    return names, True


def _binding_label(binding: Any) -> dict[str, Any]:
    """Flatten a `given` binding into {kind, ref} for display."""
    if not isinstance(binding, dict):
        return {"kind": "unknown", "ref": str(binding)}
    for kind in ("attribute", "derived", "entityType", "asOf"):
        if kind in binding:
            return {"kind": kind, "ref": str(binding[kind])}
    return {"kind": "unknown", "ref": json.dumps(binding, sort_keys=True)}


def _render_conclusion(then: dict[str, Any]) -> str:
    value = then.get("value")
    if not isinstance(value, dict):
        return str(value)
    if "expr" in value:
        return str(value["expr"])
    raw = value.get("value")
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if value.get("kind") == "money":
        return f"{value.get('amount')} {value.get('currency')}"
    return str(raw)


def _rule_view(rule: dict[str, Any]) -> dict[str, Any]:
    """One rule, flattened for display. The IR stays the source of truth; this
    is only a shape the browser can render without re-implementing the IR."""
    given = rule.get("given") or {}
    then = rule.get("then") or {}
    citation = rule.get("citation") or {}
    return {
        "id": rule.get("id"),
        "description": rule.get("description") or "",
        "version": rule.get("version"),
        "priority": rule.get("priority"),
        "effectiveFrom": rule.get("effectiveFrom"),
        "effectiveTo": rule.get("effectiveTo"),
        "citation": {"text": citation.get("text", ""), "url": citation.get("url")},
        "given": [
            {"name": name, **_binding_label(binding)}
            for name, binding in given.items()
        ],
        "when": [str(w) for w in (rule.get("when") or [])],
        "then": {
            "entity": then.get("entity"),
            "attribute": then.get("attribute"),
            "kind": (then.get("value") or {}).get("kind")
            if isinstance(then.get("value"), dict)
            else None,
            "display": _render_conclusion(then),
        },
        "overrides": list(rule.get("overrides") or []),
        "todoVerify": "TODO(verify)" in json.dumps(rule),
    }


def _decision_tables(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Group the pack's rules by the attribute they conclude and lay each
    group out as a decision table."""
    rules = [r for r in (pack.get("rules") or []) if isinstance(r, dict)]
    declared = {
        d.get("attribute"): d
        for d in (pack.get("decisions") or [])
        if isinstance(d, dict)
    }

    groups: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        attribute = (rule.get("then") or {}).get("attribute")
        if attribute:
            groups.setdefault(str(attribute), []).append(rule)

    tables: list[dict[str, Any]] = []
    for attribute, group in groups.items():
        # Columns in first-appearance order across the group. Entity-type
        # bindings are the table's *subject*, not an input, so they are hoisted
        # out rather than becoming a column of identical cells.
        columns: list[dict[str, Any]] = []
        seen: set[str] = set()
        subjects: list[str] = []
        for rule in group:
            for name, binding in (rule.get("given") or {}).items():
                label = _binding_label(binding)
                if label["kind"] == "entityType":
                    if label["ref"] not in subjects:
                        subjects.append(label["ref"])
                    continue
                if name not in seen:
                    seen.add(name)
                    columns.append({"name": name, **label})

        rows = []
        for rule in group:
            given = rule.get("given") or {}
            bound = {
                name
                for name, binding in given.items()
                if _binding_label(binding)["kind"] != "entityType"
            }
            # Each cell carries the indices of the `when` items it owns, so an
            # edit in the grid rewrites exactly those entries and leaves the
            # rest of the list — and therefore the rest of the diff — alone.
            cells: dict[str, list[str]] = {c["name"]: [] for c in columns}
            indices: dict[str, list[int]] = {c["name"]: [] for c in columns}
            cross: list[str] = []
            cross_indices: list[int] = []
            for position, condition in enumerate(rule.get("when") or []):
                source = str(condition)
                names, parsed = _expr_vars(source)
                targets = names & set(cells)
                if parsed and len(targets) == 1:
                    owner = next(iter(targets))
                    cells[owner].append(source)
                    indices[owner].append(position)
                else:
                    cross.append(source)
                    cross_indices.append(position)
            rows.append(
                {
                    "ruleId": rule.get("id"),
                    "priority": rule.get("priority"),
                    "effectiveFrom": rule.get("effectiveFrom"),
                    "effectiveTo": rule.get("effectiveTo"),
                    "citation": (rule.get("citation") or {}).get("text", ""),
                    "citationUrl": (rule.get("citation") or {}).get("url"),
                    "overrides": list(rule.get("overrides") or []),
                    # "unbound" is not the same as "unconstrained": a rule
                    # that does not bind an input does not require the fact at
                    # all, which is exactly the DMN `-` cell that surprises
                    # people (spec/dmn.md M4). The grid says which is which.
                    "cells": [
                        {
                            "column": column["name"],
                            "bound": column["name"] in bound,
                            "conditions": cells[column["name"]],
                            "indices": indices[column["name"]],
                        }
                        for column in columns
                    ],
                    "cross": cross,
                    "crossIndices": cross_indices,
                    "output": _render_conclusion(rule.get("then") or {}),
                }
            )

        priorities = {r.get("priority") for r in group}
        tables.append(
            {
                "attribute": attribute,
                "question": (declared.get(attribute) or {}).get("question"),
                "declared": attribute in declared,
                "entityTypes": subjects,
                # The hit policy a DMN author would have written to get this
                # group. One priority level means the rules must be mutually
                # exclusive (UNIQUE); several means highest-priority-wins.
                "hitPolicy": "UNIQUE" if len(priorities) <= 1 else "PRIORITY",
                "columns": columns,
                "rows": rows,
            }
        )
    return tables


# ---------------------------------------------------------------------------
# Golden-corpus usage
# ---------------------------------------------------------------------------


_USAGE_CACHE: dict[str, Any] | None = None


def _golden_usage() -> dict[str, Any]:
    """How many committed golden receipts cite each rule id.

    This is the number that makes a rule id permanent (CLAUDE.md: `NY-NR-45`
    is in 76 receipts) and the cheapest available answer to "what does this
    rule actually do around here". Read-only, computed once per process.
    """
    global _USAGE_CACHE
    if _USAGE_CACHE is not None:
        return _USAGE_CACHE
    by_rule: dict[str, int] = {}
    by_pack: dict[str, int] = {}
    receipts_dir = GOLDEN_DIR / "receipts"
    if receipts_dir.is_dir():
        for path in sorted(receipts_dir.glob("*.json")):
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = (receipt.get("rulePack") or {}).get("name")
            if name:
                by_pack[name] = by_pack.get(name, 0) + 1
            for fired in receipt.get("rulesFired") or []:
                rule_id = fired.get("ruleId")
                if rule_id:
                    by_rule[rule_id] = by_rule.get(rule_id, 0) + 1
    _USAGE_CACHE = {"byRule": by_rule, "byPack": by_pack}
    return _USAGE_CACHE


# ---------------------------------------------------------------------------
# Fact sets for the ad-hoc tester
# ---------------------------------------------------------------------------
#
# Hand-building a GroundedFact in a browser form is the wrong ask: grounding,
# assertion, schemaRef and a content hash are all load-bearing and none of them
# is what a rule author is thinking about. So the tester starts from a fact set
# that already exists — a pack's own expected.yaml case, or a golden case that
# cites the pack — and lets you *change values*. That is the same move the
# what-if module makes, and it reuses the same substitution helper, so a
# hand-run test and a solver answer are re-addressed identically.


def _expected_spec(slug: str) -> dict[str, Any] | None:
    path = RULEPACKS_DIR / slug / "expected.yaml"
    if not path.is_file():
        return None
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return spec if isinstance(spec, dict) else None


def _pack_name(pack: dict[str, Any]) -> str:
    return str((pack.get("pack") or {}).get("name") or "")


def _golden_cases_for(slug: str) -> list[dict[str, Any]]:
    """Golden cases whose case.yaml names this pack directory."""
    out: list[dict[str, Any]] = []
    cases_dir = GOLDEN_DIR / "cases"
    if not cases_dir.is_dir():
        return out
    needle = f"rulepacks/{slug}/pack.yaml"
    for case_dir in sorted(d for d in cases_dir.iterdir() if d.is_dir()):
        case_path = case_dir / "case.yaml"
        if not case_path.is_file():
            continue
        try:
            case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(case, dict) or str(case.get("pack", "")) != needle:
            continue
        out.append(
            {
                "id": str(case.get("id") or case_dir.name),
                "label": f"golden/{case_dir.name}",
                "source": "golden",
                "factsPath": f"golden/cases/{case_dir.name}/facts",
                "asOfEffective": str(case.get("asOfEffective") or "")[:10],
                "question": case.get("question"),
            }
        )
    return out


def _fact_sets(slug: str, pack: dict[str, Any]) -> list[dict[str, Any]]:
    sets: list[dict[str, Any]] = []
    spec = _expected_spec(slug)
    for case in (spec or {}).get("cases") or []:
        if not isinstance(case, dict) or not case.get("factsFrom"):
            continue
        sets.append(
            {
                "id": f"expected:{case['name']}",
                "label": f"expected.yaml — {case['name']}",
                "source": "expected",
                "factsPath": str(case["factsFrom"]),
                "asOfEffective": str(case.get("asOfEffective") or "")[:10],
                "question": case.get("question"),
            }
        )
    sets.extend(_golden_cases_for(slug))
    # Same facts directory reached twice is one fact set to a human.
    seen: set[str] = set()
    unique = []
    for entry in sets:
        key = entry["factsPath"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _load_facts(rel_path: str) -> list[dict[str, Any]]:
    """Facts from a repo-relative directory, refusing to leave the repo."""
    base = (REPO_ROOT / rel_path).resolve()
    try:
        base.relative_to(REPO_ROOT)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Path escapes the repo: {rel_path}")
    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"No such facts directory: {rel_path}")
    facts = []
    for path in sorted(base.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and "receiptSha256" not in doc:
            facts.append(doc)
    if not facts:
        raise HTTPException(status_code=404, detail=f"No facts in {rel_path}")
    return facts


def _input_value(template: dict[str, Any], raw: str) -> dict[str, Any]:
    """A fact value of the template's kind carrying the tester's scalar.

    Deliberately not ``demo.app._corrected_value``: that one serves a human
    *review correction*, refuses kinds a reviewer should not be inventing, and
    is bound to the review contract. This one serves a scratchpad test, so it
    accepts every kind the IR has — including money, where a reviewer form
    should not be silently changing a currency.
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="A test input value is required")
    kind = template.get("kind")
    value = json.loads(json.dumps(template))  # deep copy, plain JSON throughout
    if kind in ("date", "datetime"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", raw):
            raise HTTPException(
                status_code=422, detail=f"Not an ISO date/datetime: {raw!r}"
            )
        value["value"] = raw
    elif kind in ("decimal", "money"):
        try:
            Decimal(raw)
        except InvalidOperation:
            raise HTTPException(status_code=422, detail=f"Not a valid decimal: {raw!r}")
        if kind == "money":
            value["amount"] = raw
        else:
            value["value"] = raw
    elif kind == "boolean":
        if raw.lower() not in ("true", "false"):
            raise HTTPException(
                status_code=422, detail=f"Booleans must be 'true' or 'false': {raw!r}"
            )
        value["value"] = raw.lower() == "true"
    elif kind in ("string", "code", "entityRef"):
        value["value"] = raw
    else:
        raise HTTPException(status_code=422, detail=f"Unsupported value kind: {kind!r}")
    return value


def _live_inputs(facts: list[dict[str, Any]], pack: dict[str, Any], as_of: str) -> Any:
    from duly_whatif.casefacts import live_by_attribute  # noqa: PLC0415

    return live_by_attribute(facts, pack, as_of)


# ---------------------------------------------------------------------------
# Pack payloads
# ---------------------------------------------------------------------------


def _pack_summary(slug: str) -> dict[str, Any]:
    text = _effective_yaml(slug)
    try:
        pack = _parse_yaml(text)
    except HTTPException:
        pack = {}
    meta = pack.get("pack") or {}
    usage = _golden_usage()
    spec = _expected_spec(slug)
    return {
        "slug": slug,
        "name": meta.get("name") or slug,
        "version": meta.get("version"),
        "idPrefix": meta.get("idPrefix"),
        "ontology": meta.get("ontology"),
        "ontologyVersion": meta.get("ontologyVersion"),
        "description": meta.get("description") or "",
        "ruleCount": len(pack.get("rules") or []),
        "decisionCount": len(pack.get("decisions") or []),
        "expectedCases": len((spec or {}).get("cases") or []),
        "goldenReceipts": usage["byPack"].get(meta.get("name"), 0),
        "hasAbstentionPolicy": bool(pack.get("abstentionPolicy")),
        "hasCalendars": bool(pack.get("calendars")),
        "committed": _committed_path(slug) is not None,
        "dirty": _is_dirty(slug),
        "path": f"rulepacks/{slug}/pack.yaml",
    }


def _pack_detail(slug: str) -> dict[str, Any]:
    text = _effective_yaml(slug)
    pack = _parse_yaml(text)
    usage = _golden_usage()["byRule"]
    committed = _committed_yaml(slug) or ""
    rules = [
        {**_rule_view(r), "goldenReceipts": usage.get(r.get("id"), 0)}
        for r in (pack.get("rules") or [])
        if isinstance(r, dict)
    ]
    return {
        **_pack_summary(slug),
        "yaml": text,
        "pack": pack,
        "rules": rules,
        "decisions": pack.get("decisions") or [],
        "abstentionPolicy": pack.get("abstentionPolicy"),
        "calendars": list((pack.get("calendars") or {}).keys())
        if isinstance(pack.get("calendars"), dict)
        else [],
        "tables": _decision_tables(pack),
        "factSets": _fact_sets(slug, pack),
        "validation": _validation(pack),
        "diff": _diffs(slug, committed, text) if _is_dirty(slug) else {"file": [], "semantic": []},
        "sessionNote": SESSION_NOTE,
    }


# ---------------------------------------------------------------------------
# Endpoints — reading
# ---------------------------------------------------------------------------


@router.get("/packs")
def api_packs() -> dict[str, Any]:
    return {
        "packs": [_pack_summary(slug) for slug in _known_slugs()],
        "sessionNote": SESSION_NOTE,
        "capabilities": _capabilities(),
    }


@router.get("/packs/{slug}")
def api_pack(slug: str) -> dict[str, Any]:
    return _pack_detail(_slug_ok(slug))


def _capabilities() -> dict[str, Any]:
    """What this deployment can actually do, so the UI can say so up front
    rather than offering a button that 503s."""
    def importable(module: str) -> bool:
        import importlib.util  # noqa: PLC0415

        try:
            return importlib.util.find_spec(module) is not None
        except Exception:
            return False

    return {
        "kernel": importable("duly_kernel"),
        "dmn": importable("duly_dmn"),
        "impact": importable("duly_assurance") and (GOLDEN_DIR / "cases").is_dir(),
        "prove": importable("z3"),
        "whatif": importable("duly_whatif"),
    }


# ---------------------------------------------------------------------------
# Endpoints — drafting
# ---------------------------------------------------------------------------


class DraftRequest(BaseModel):
    yaml: str | None = None
    pack: dict[str, Any] | None = None


@router.put("/packs/{slug}/draft")
def api_put_draft(slug: str, body: DraftRequest) -> dict[str, Any]:
    """Replace the session draft, from YAML source or a structured pack.

    Validation failures do not reject the draft — they are reported on it. An
    author mid-edit has an invalid pack most of the time, and a studio that
    discarded the text at every intermediate state would be unusable.
    """
    slug = _slug_ok(slug)
    if _committed_path(slug) is None and slug not in _CREATED:
        raise HTTPException(status_code=404, detail=f"Unknown rule pack: {slug}")
    if body.yaml is not None:
        text = body.yaml
        _parse_yaml(text)  # 422 on unparseable source, before we store it
    elif body.pack is not None:
        text = _emit(body.pack)
    else:
        raise HTTPException(status_code=422, detail="Send either `yaml` or `pack`")
    with _DRAFT_LOCK:
        _DRAFTS[slug] = text
    return _pack_detail(slug)


@router.delete("/packs/{slug}/draft")
def api_delete_draft(slug: str) -> dict[str, Any]:
    slug = _slug_ok(slug)
    with _DRAFT_LOCK:
        _DRAFTS.pop(slug, None)
        if slug in _CREATED:
            _CREATED.discard(slug)
            return {"slug": slug, "discarded": True}
    return _pack_detail(slug)


class CreatePackRequest(BaseModel):
    slug: str
    name: str
    idPrefix: str
    ontology: str = "duly-starter-notice"
    ontologyVersion: str = "0.1.0"
    description: str = ""


@router.post("/packs")
def api_create_pack(body: CreatePackRequest) -> dict[str, Any]:
    """Start a new pack as a session draft, from a skeleton that already obeys
    the conventions a new pack most often gets wrong: an `idPrefix`, a
    convention-shaped default rule id, a cited default presumption, and a
    decision carrying phrasing so a non-boolean answer never renders as a raw
    CURIE."""
    slug = _slug_ok(body.slug)
    if _committed_path(slug) is not None:
        raise HTTPException(
            status_code=409, detail=f"rulepacks/{slug}/ already exists in the working tree"
        )
    prefix = body.idPrefix.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,7}", prefix):
        raise HTTPException(
            status_code=422,
            detail="idPrefix must be 2-8 uppercase letters/digits, e.g. NC or TRID",
        )
    attribute = f"{prefix.lower()}:eligible"
    skeleton = {
        "pack": {
            "name": body.name.strip() or slug,
            "version": "0.1.0",
            "idPrefix": prefix,
            "ontology": body.ontology,
            "ontologyVersion": body.ontologyVersion,
            "description": body.description.strip() or f"{body.name} rules.",
        },
        "decisions": [
            {
                "attribute": attribute,
                "entityType": f"{prefix.lower()}:Subject",
                "question": f"Is the subject eligible under {body.name}?",
                "phrasing": [
                    {"when": {"value": True}, "verdict": "Eligible", "tone": "pos"},
                    {"when": {"value": False}, "verdict": "Not eligible", "tone": "neg"},
                ],
            }
        ],
        "rules": [
            {
                "id": f"{prefix}-DEF-00",
                "description": "Default presumption — replace with cited rules.",
                "version": "1.0.0",
                "priority": 0,
                "citation": {"text": "TODO(verify) default presumption, not yet cited"},
                "effectiveFrom": "1900-01-01",
                "given": {"subject": {"entityType": f"{prefix.lower()}:Subject"}},
                "then": {
                    "entity": "subject",
                    "attribute": attribute,
                    "value": {"kind": "boolean", "value": False},
                },
            }
        ],
    }
    with _DRAFT_LOCK:
        _DRAFTS[slug] = _emit(skeleton)
        _CREATED.add(slug)
    return _pack_detail(slug)


@router.get("/packs/{slug}/pack.yaml")
def api_download_pack(slug: str) -> Response:
    slug = _slug_ok(slug)
    text = _effective_yaml(slug)
    return Response(
        content=text.encode("utf-8"),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{slug}-pack.yaml"'},
    )


@router.get("/packs/{slug}/bundle")
def api_download_bundle(slug: str) -> Response:
    """The draft as a `rulepacks/<slug>/` directory, zipped.

    Includes an `expected.yaml` skeleton and a NEXT-STEPS note, because the
    thing that actually goes wrong with a new pack is not the YAML — it is
    shipping one with no declared cases and no generator template, which reads
    as "0 of 351 decisions flip" forever (rulepacks/README.md).
    """
    slug = _slug_ok(slug)
    text = _effective_yaml(slug)
    pack = _parse_yaml(text)
    attribute = ""
    decisions = pack.get("decisions") or []
    if decisions and isinstance(decisions[0], dict):
        attribute = str(decisions[0].get("attribute") or "")
    expected = (
        "# Declared adjudication outcomes — this pack's own test suite.\n"
        "# Run by kernel/tests/test_rulepacks.py, which globs rulepacks/*/expected.yaml.\n"
        "# Cover every rule, every defeat chain, and both sides of each effective-date\n"
        "# boundary. `factsFrom` points at a starter's facts or at fixtures/.\n"
        "cases: []\n"
        f"#  - name: first-case\n"
        f"#    factsFrom: rulepacks/{slug}/fixtures/first-case/facts\n"
        f'#    asOfEffective: "2026-01-01"\n'
        f"#    question: {attribute}\n"
        f"#    expectDecision: {{ kind: boolean, value: false }}\n"
        f"#    expectRulesFired: []\n"
    )
    next_steps = (
        f"# {slug} — next steps\n\n"
        "This bundle was drafted in the demo Rule Studio. The studio produced a\n"
        "pack; it did not produce a *shipped* pack. Read rulepacks/README.md and\n"
        "work it from step 2 — none of the following is automatic:\n\n"
        "1. `expected.yaml` cases covering every rule and defeat chain.\n"
        "2. A golden-corpus generator template in\n"
        "   assurance/duly_assurance/generate.py — without one, impact analysis\n"
        "   reports 0 flips for every edit to this pack, forever.\n"
        "3. Ontology coverage: every attribute a fact carries must exist in the\n"
        "   pinned ontology version (`python -m duly_conformance check ...`).\n"
        "4. Decision phrasing for any non-boolean decision (spec/rule-ir.md).\n"
        "5. A starter scenario if the demo should show it.\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        # ZipInfo without a date_time pins the DOS epoch: the bundle bytes
        # depend only on the pack content, matching the golden-case export.
        for name, content in (
            (f"{slug}/pack.yaml", text),
            (f"{slug}/expected.yaml", expected),
            (f"{slug}/NEXT-STEPS.md", next_steps),
        ):
            bundle.writestr(zipfile.ZipInfo(name), content.encode("utf-8"))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-rulepack.zip"'},
    )


# ---------------------------------------------------------------------------
# Endpoints — testing
# ---------------------------------------------------------------------------


def _adjudicate(pack: dict[str, Any], facts: list[dict[str, Any]], as_of: str,
                attribute: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from duly_kernel.api import adjudicate  # noqa: PLC0415
    except Exception:
        raise HTTPException(
            status_code=503, detail="Kernel unavailable (duly_kernel not importable)."
        )
    try:
        receipt = adjudicate(facts, pack, as_of, f"{as_of}T23:59:59Z", attribute)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return receipt, None


def _reasoning(receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not receipt:
        return []
    return sorted(
        (
            {"ruleId": f.get("ruleId"), "defeated": sorted(f.get("defeated") or [])}
            for f in receipt.get("rulesFired") or []
        ),
        key=lambda r: str(r["ruleId"]),
    )


@router.post("/packs/{slug}/test/expected")
def api_test_expected(slug: str) -> dict[str, Any]:
    """Run the pack's declared `expected.yaml` cases against the effective
    pack — the same assertions `kernel/tests/test_rulepacks.py` makes, minus
    pytest, so an author sees them fail while editing rather than at commit."""
    slug = _slug_ok(slug)
    pack = _parse_yaml(_effective_yaml(slug))
    spec = _expected_spec(slug)
    if spec is None:
        return {
            "cases": [],
            "passed": 0,
            "failed": 0,
            "note": f"rulepacks/{slug}/expected.yaml does not exist — this pack "
            "declares no outcomes, so nothing here can catch it breaking.",
        }
    results = []
    for case in spec.get("cases") or []:
        if not isinstance(case, dict):
            continue
        name = str(case.get("name") or "<unnamed>")
        try:
            facts = _load_facts(str(case["factsFrom"]))
        except HTTPException as exc:
            results.append(
                {"name": name, "ok": False, "failures": [str(exc.detail)], "actual": None}
            )
            continue
        receipt, error = _adjudicate(
            pack, facts, str(case["asOfEffective"]), str(case["question"])
        )
        if error is not None:
            results.append(
                {"name": name, "ok": False, "failures": [error], "actual": None}
            )
            continue
        failures: list[str] = []
        actual_value = receipt["decision"]["value"]
        expected_value = dict(case.get("expectDecision") or {})
        if actual_value != expected_value:
            failures.append(
                f"decision: expected {json.dumps(expected_value, sort_keys=True)}, "
                f"got {json.dumps(actual_value, sort_keys=True)}"
            )
        fired = sorted({r["ruleId"] for r in receipt.get("rulesFired") or []})
        expected_fired = sorted(set(case.get("expectRulesFired") or []))
        if fired != expected_fired:
            failures.append(
                f"rulesFired: expected {expected_fired}, got {fired}"
            )
        defeated = {
            r["ruleId"]: sorted(r.get("defeated") or [])
            for r in receipt.get("rulesFired") or []
            if r.get("defeated")
        }
        expected_defeated = {
            k: sorted(v) for k, v in (case.get("expectDefeated") or {}).items()
        }
        if defeated != expected_defeated:
            failures.append(
                f"defeated: expected {json.dumps(expected_defeated, sort_keys=True)}, "
                f"got {json.dumps(defeated, sort_keys=True)}"
            )
        results.append(
            {
                "name": name,
                "question": case.get("question"),
                "asOfEffective": str(case.get("asOfEffective") or "")[:10],
                "ok": not failures,
                "failures": failures,
                "actual": {
                    "value": actual_value,
                    "rulesFired": fired,
                    "defeated": defeated,
                },
            }
        )
    return {
        "cases": results,
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "note": None,
    }


class CaseTestRequest(BaseModel):
    factsPath: str
    asOfEffective: str
    attribute: str
    overrides: dict[str, str] = {}


@router.post("/packs/{slug}/test/case")
def api_test_case(slug: str, body: CaseTestRequest) -> dict[str, Any]:
    """Adjudicate one hand-built case under the effective pack, and — when a
    draft is in play — under the committed pack too, so the answer to "did my
    edit change this" is on screen rather than in your head."""
    slug = _slug_ok(slug)
    pack = _parse_yaml(_effective_yaml(slug))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.asOfEffective or ""):
        raise HTTPException(
            status_code=422, detail="asOfEffective must be YYYY-MM-DD"
        )
    facts = _load_facts(body.factsPath)

    try:
        from duly_whatif.casefacts import substitute  # noqa: PLC0415
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="The case tester needs duly_whatif (fact substitution and "
            "re-addressing); it is not importable.",
        )

    inputs = _live_inputs(facts, pack, body.asOfEffective)
    applied: list[dict[str, Any]] = []
    for attribute, raw in sorted(body.overrides.items()):
        current = inputs.get(attribute)
        if current is None:
            raise HTTPException(
                status_code=422,
                detail=f"{attribute} has no live fact at {body.asOfEffective}, so "
                "there is no value shape to substitute into",
            )
        value = _input_value(current.get("value") or {}, raw)
        facts = substitute(facts, attribute, value)
        applied.append({"attribute": attribute, "value": value})

    receipt, error = _adjudicate(pack, facts, body.asOfEffective, body.attribute)

    baseline: dict[str, Any] | None = None
    if _is_dirty(slug) and _committed_yaml(slug) is not None:
        committed_pack = _parse_yaml(_committed_yaml(slug) or "")
        base_receipt, base_error = _adjudicate(
            committed_pack, facts, body.asOfEffective, body.attribute
        )
        baseline = {
            "value": (base_receipt or {}).get("decision", {}).get("value"),
            "rulesFired": _reasoning(base_receipt),
            "error": base_error,
        }

    return {
        "inputs": [
            {
                "attribute": attribute,
                "value": fact.get("value"),
                "assertion": (fact.get("assertion") or {}).get("kind"),
                "confidence": (fact.get("assertion") or {}).get("confidence"),
            }
            for attribute, fact in sorted(inputs.items())
        ],
        "applied": applied,
        "receipt": receipt,
        "error": error,
        "decision": (receipt or {}).get("decision"),
        "rulesFired": _reasoning(receipt),
        "abstentions": (receipt or {}).get("abstentions") or [],
        "baseline": baseline,
        "changed": baseline is not None
        and baseline["value"] != (receipt or {}).get("decision", {}).get("value"),
    }


@router.post("/packs/{slug}/impact")
def api_impact(slug: str) -> dict[str, Any]:
    """Re-adjudicate the whole golden corpus with the draft substituted for the
    committed pack: "this change flips N of M historical decisions".

    The one instrument that catches *drift* rather than breakage. A pack with
    no generator template gets a cheerful zero here for every edit — the
    response says so rather than letting the zero speak.
    """
    slug = _slug_ok(slug)
    committed = _committed_path(slug)
    if committed is None:
        raise HTTPException(
            status_code=409,
            detail="Impact analysis compares a draft against committed golden "
            "receipts; this pack has no committed side yet.",
        )
    try:
        from duly_assurance.impact import ImpactOperationalError, analyze  # noqa: PLC0415
    except Exception:
        raise HTTPException(
            status_code=503, detail="duly_assurance.impact is not importable."
        )
    pack = _parse_yaml(_effective_yaml(slug))
    validation = _validation(pack)
    if validation["ok"] is False:
        raise HTTPException(
            status_code=422,
            detail=f"The draft does not validate, so it cannot be adjudicated: "
            f"{validation['error']}",
        )
    try:
        report = analyze(GOLDEN_DIR, pack_overrides={committed.resolve(): pack})
    except ImpactOperationalError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    pack_name = _pack_name(pack)
    covered = _golden_usage()["byPack"].get(pack_name, 0)
    return {
        "summary": report["summary"],
        "totalCases": report["totalCases"],
        "flipCount": report["flipCount"],
        "reasoningChangeCount": report["reasoningChangeCount"],
        "flips": report["flips"][:25],
        "reasoningChanges": report["reasoningChanges"][:25],
        "packCases": covered,
        "note": (
            f"{covered} of the {report['totalCases']} golden cases exercise this "
            "pack."
            if covered
            else "No golden case exercises this pack, so impact analysis cannot "
            "see this change at all — it needs a generator template in "
            "assurance/duly_assurance/generate.py (rulepacks/README.md)."
        ),
    }


@router.post("/packs/{slug}/prove")
def api_prove(slug: str) -> dict[str, Any]:
    """Static verification of the effective pack, plus — when a draft differs
    from the committed pack — a proof of whether the two decide alike.

    Equivalence is the question editing actually raises, and it is the one a
    fixture list cannot answer: `>` becoming `>=` can leave every committed
    case identical and still change the receipt on every boundary input. z3 is
    an optional dependency; without it this returns a note, not an error.
    """
    slug = _slug_ok(slug)
    try:
        import z3  # noqa: F401, PLC0415
    except Exception:
        return {
            "available": False,
            "note": "Static verification needs the optional z3 solver: "
            "`uv sync --extra prove`.",
        }
    from duly_assurance.prove import (  # noqa: PLC0415
        analyze_pack,
        equivalence_report,
        report_json,
    )
    from duly_conformance.registry import load_repo_registry  # noqa: PLC0415

    pack = _parse_yaml(_effective_yaml(slug))
    validation = _validation(pack)
    if validation["ok"] is False:
        raise HTTPException(
            status_code=422,
            detail=f"The draft does not validate: {validation['error']}",
        )
    # An enum-bearing registry sharpens every answer (a closed value set turns
    # "these literals plus anything else" into exactly the permitted values),
    # but the analysis works without one. A missing directory is not an error.
    registry = load_repo_registry(ONTOLOGIES_DIR) if ONTOLOGIES_DIR.is_dir() else None
    report = analyze_pack(Path(f"rulepacks/{slug}/pack.yaml"), pack, registry)

    equivalence: dict[str, Any] | None = None
    committed_yaml = _committed_yaml(slug)
    if _is_dirty(slug) and committed_yaml is not None:
        committed_pack = _parse_yaml(committed_yaml)
        if _validation(committed_pack)["ok"] is not False:
            eq = equivalence_report(committed_pack, pack, registry)
            equivalence = {
                "error": eq.error,
                "onlyCommitted": eq.only_a,
                "onlyDraft": eq.only_b,
                "decisions": [
                    {
                        "attribute": d.attribute,
                        "verdict": d.verdict,
                        "reason": d.reason,
                        "witness": [list(pair) for pair in d.witness],
                        "witnessExact": d.witness_exact,
                        "committedValue": d.left_value,
                        "draftValue": d.right_value,
                    }
                    for d in eq.decisions
                ],
                "trace": None
                if eq.trace is None
                else {
                    "verdict": eq.trace.verdict,
                    "reason": eq.trace.reason,
                    "differences": eq.trace.differences,
                    "witness": [list(pair) for pair in eq.trace.witness],
                    "sharedRules": eq.trace.shared_rules,
                },
                "assumptions": eq.assumptions,
            }
    return {
        "available": True,
        "note": None,
        "report": report_json(report),
        "fatal": report.fatal,
        "equivalence": equivalence,
    }


# ---------------------------------------------------------------------------
# Endpoints — DMN
# ---------------------------------------------------------------------------


@router.get("/dmn/examples")
def api_dmn_examples() -> dict[str, Any]:
    """The committed .dmn documents, including the refusal corpus.

    The refusals are on this list on purpose: one minimal broken document per
    refusal class is the fastest way to learn what the compiler will not do,
    and a compiler that refuses is only trustworthy if you have watched it
    refuse.
    """
    examples = []
    if DMN_EXAMPLES_DIR.is_dir():
        paths = sorted(DMN_EXAMPLES_DIR.rglob("*.dmn"))
        # Compiling examples first: the point of the list is "here is one that
        # works, and here is one of each way it can fail", in that order.
        for path in sorted(paths, key=lambda p: (p.parent.name == "refusals", p.stem)):
            examples.append(
                {
                    "path": path.relative_to(REPO_ROOT).as_posix(),
                    "name": path.stem,
                    "refusal": path.parent.name == "refusals",
                }
            )
    return {"examples": examples}


class DmnSourceRequest(BaseModel):
    xml: str | None = None
    path: str | None = None


@router.post("/dmn/compile")
def api_dmn_compile(body: DmnSourceRequest) -> dict[str, Any]:
    """Compile DMN into a rule pack, or report exactly why it will not.

    A compile error here is the product, not a failure mode: it names the
    decision, the row and the cell, and it is what stops a rule the IR cannot
    honestly express from being silently approximated into one it can.
    """
    try:
        from duly_dmn import DmnCompileError, compile_source, emit_pack  # noqa: PLC0415
    except Exception:
        raise HTTPException(
            status_code=503, detail="duly_dmn is not importable in this deployment."
        )
    if body.path:
        target = (REPO_ROOT / body.path).resolve()
        try:
            target.relative_to(DMN_EXAMPLES_DIR)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="Only committed dmn/examples/ documents may be loaded by path.",
            )
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"No such DMN: {body.path}")
        xml = target.read_text(encoding="utf-8")
    elif body.xml:
        xml = body.xml
    else:
        raise HTTPException(status_code=422, detail="Send either `xml` or `path`")

    try:
        pack = compile_source(xml, _dmn_value_kinds())
    except DmnCompileError as exc:
        return {"ok": False, "error": str(exc), "xml": xml}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "xml": xml}
    text = emit_pack(pack, source=body.path or "(pasted)")
    return {
        "ok": True,
        "error": None,
        "xml": xml,
        "yaml": text,
        "pack": pack,
        "name": (pack.get("pack") or {}).get("name"),
        "ruleCount": len(pack.get("rules") or []),
        "decisionCount": len(pack.get("decisions") or []),
        "tables": _decision_tables(pack),
    }


class DmnAdoptRequest(BaseModel):
    slug: str
    xml: str | None = None
    path: str | None = None


@router.post("/dmn/adopt")
def api_dmn_adopt(body: DmnAdoptRequest) -> dict[str, Any]:
    """Compile a DMN document into a session draft under `slug`.

    The compiled pack is a pack like any other from here on, which is the
    whole claim: it goes straight into the same validator, the same declared
    cases, the same impact analysis as a hand-written one.
    """
    slug = _slug_ok(body.slug)
    result = api_dmn_compile(DmnSourceRequest(xml=body.xml, path=body.path))
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    with _DRAFT_LOCK:
        _DRAFTS[slug] = result["yaml"]
        if _committed_path(slug) is None:
            _CREATED.add(slug)
    return _pack_detail(slug)
