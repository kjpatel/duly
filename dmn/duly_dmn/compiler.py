"""DMN model -> duly rule-IR pack dict.

The whole compiler is here: hit-policy mapping, the annotation convention that
carries citation and effective dates, binding resolution, and the UNIQUE
disjointness pre-check. Read spec/dmn.md first — every non-obvious choice
below is argued there, and this module is the argument executed.

The output is a plain dict in the exact key order the emitter writes and the
kernel expects. It is handed to `duly_kernel.ir.validate_pack` before it is
returned: a compiler that emits a pack the kernel would reject has not
compiled anything.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

from .errors import (
    BINDING_ERROR,
    MALFORMED_DOCUMENT,
    MISSING_CITATION,
    MISSING_EFFECTIVE_DATE,
    MISSING_RULE_ID,
    UNPROVABLE_UNIQUE,
    UNSUPPORTED_EXPRESSION,
    UNSUPPORTED_HIT_POLICY,
    UNSUPPORTED_TABLE_SHAPE,
    DmnCompileError,
    Location,
)
from .reader import Decision, Definitions, InputColumn, Row, read_file, read_string
from .sfeel import Endpoint, InputTest, compile_input_entry, compile_output_entry

# --- hit policies ----------------------------------------------------------

SUPPORTED_HIT_POLICIES = ("UNIQUE", "FIRST", "PRIORITY")

# Why each unsupported policy is unsupported, quoted back at the author. A
# policy is refused because duly cannot express it, not because nobody got
# round to it, and the message says which.
_UNSUPPORTED_HIT_POLICIES: dict[str, str] = {
    "ANY": (
        "ANY permits overlapping rows provided they agree on the output. duly's "
        "kernel resolves same-priority conclusions by refusing the pack, and has "
        "no notion of \"overlapping but agreeing\" — compiling ANY would mean "
        "either fabricating an ordering the author did not write or dropping the "
        "agreement check the policy exists for"
    ),
    "COLLECT": (
        "COLLECT returns a list (optionally aggregated with sum/min/max/count). "
        "A duly decision is a single value for a single attribute on a single "
        "entity; there is no list-valued conclusion in the IR and no aggregation "
        "operator in the expression language"
    ),
    "RULE ORDER": (
        "RULE ORDER returns every matching row, in order. Same objection as "
        "COLLECT: duly concludes one value, not a sequence"
    ),
    "OUTPUT ORDER": (
        "OUTPUT ORDER returns every matching row sorted by output priority. Same "
        "objection as COLLECT, plus the outputValues ordering PRIORITY needs"
    ),
}

# DMN permits the single-letter abbreviations in the `hitPolicy` attribute.
_SINGLE_LETTER = {
    "U": "UNIQUE",
    "F": "FIRST",
    "P": "PRIORITY",
    "A": "ANY",
    "C": "COLLECT",
    "R": "RULE ORDER",
    "O": "OUTPUT ORDER",
}

# Rows in a FIRST/PRIORITY table get priorities descending in row order, in
# steps of this size, with the last row at 0. The step is only cosmetic — the
# kernel compares priorities, never their spacing — but leaving gaps means a
# hand-edit inserting a rule between two compiled ones has somewhere to go.
PRIORITY_STEP = 100

# --- annotation convention -------------------------------------------------

ANN_RULE_ID = "duly:ruleId"
ANN_CITATION = "duly:citation"
ANN_CITATION_URL = "duly:citationUrl"
ANN_EFFECTIVE_FROM = "duly:effectiveFrom"
ANN_EFFECTIVE_TO = "duly:effectiveTo"
ANN_VERSION = "duly:version"
ANN_OVERRIDES = "duly:overrides"

KNOWN_ANNOTATIONS = (
    ANN_RULE_ID,
    ANN_CITATION,
    ANN_CITATION_URL,
    ANN_EFFECTIVE_FROM,
    ANN_EFFECTIVE_TO,
    ANN_VERSION,
    ANN_OVERRIDES,
)

DEFAULT_RULE_VERSION = "1.0.0"

_VALUE_KINDS = ("string", "decimal", "money", "date", "boolean", "code", "entityRef")

# Reserved in the duly expression language; a column labelled with one of
# these would compile to source that no longer means what the cell said.
_RESERVED_NAMES = frozenset(
    {"and", "or", "not", "true", "false", "date", "days_between", "abs", "min", "max",
     "add_business_days"}
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_file(path) -> dict:
    """Compile a .dmn file into a validated rule-IR pack dict."""
    return compile_definitions(read_file(path))


def compile_source(source: str) -> dict:
    """Compile DMN XML text into a validated rule-IR pack dict."""
    return compile_definitions(read_string(source))


def compile_definitions(defs: Definitions) -> dict:
    pack_meta = _pack_metadata(defs)

    concluded: dict[str, str] = {}
    for decision in defs.decisions:
        attribute = _require_ext(decision, "attribute")
        if attribute in concluded and concluded[attribute] != decision.id:
            # Two tables concluding one attribute is legal in duly (that is how
            # a default and its exception can live apart), so this is not an
            # error — it only matters for derived-binding inference below.
            pass
        concluded.setdefault(attribute, decision.id)

    decisions_out: list[dict] = []
    rules_out: list[dict] = []
    seen_rule_ids: dict[str, str] = {}

    for decision in defs.decisions:
        decision_entry, rules = _compile_decision(decision, concluded)
        decisions_out.append(decision_entry)
        for rule in rules:
            rid = rule["id"]
            if rid in seen_rule_ids:
                raise DmnCompileError(
                    MALFORMED_DOCUMENT,
                    f"rule id {rid!r} is declared twice (already used by decision "
                    f"{seen_rule_ids[rid]!r}). Rule ids are the audit handle on every "
                    f"receipt and must be unique across the pack.",
                    Location(decision=decision.id, rule_id=rid),
                )
            seen_rule_ids[rid] = decision.id
            rules_out.append(rule)

    pack: dict = {"pack": pack_meta, "decisions": decisions_out, "rules": rules_out}

    from duly_kernel.ir import PackValidationError, validate_pack

    try:
        validate_pack(pack)
    except PackValidationError as e:
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            f"the compiled pack does not validate against the rule IR: {e}",
            Location(),
        ) from None
    return pack


# ---------------------------------------------------------------------------
# Pack metadata
# ---------------------------------------------------------------------------


def _pack_metadata(defs: Definitions) -> dict:
    meta = defs.pack
    for field in ("name", "version"):
        if not meta.get(field):
            raise DmnCompileError(
                MALFORMED_DOCUMENT,
                f"the document declares no pack {field}. Add "
                f"`<extensionElements><duly:pack name=\"...\" version=\"...\"/>"
                f"</extensionElements>` to `definitions` "
                f"(spec/dmn.md, \"The duly extension elements\").",
                Location(),
            )
    out = {"name": meta["name"], "version": meta["version"]}
    if meta.get("ontology"):
        out["ontology"] = meta["ontology"]
    if meta.get("ontologyVersion"):
        out["ontologyVersion"] = meta["ontologyVersion"]
    description = meta.get("description") or defs.description
    if description:
        out["description"] = description
    return out


# ---------------------------------------------------------------------------
# One decision table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Binding:
    label: str
    kind: str  # "attribute" | "derived"
    curie: str


def _require_ext(decision: Decision, field: str) -> str:
    value = getattr(decision, {"attribute": "attribute", "entityType": "entity_type",
                               "valueKind": "value_kind"}[field])
    if not value:
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            f"decision declares no {field}. DMN has no vocabulary for the entity a "
            f"decision is about, the attribute it concludes, or that attribute's duly "
            f"value kind, so all three come from "
            f"`<extensionElements><duly:decision .../></extensionElements>` "
            f"(spec/dmn.md M3).",
            Location(decision=decision.id),
        )
    return value


def _compile_decision(decision: Decision, concluded: dict[str, str]) -> tuple[dict, list[dict]]:
    loc = Location(decision=decision.id)
    table = decision.table

    entity_type = _require_ext(decision, "entityType")
    attribute = _require_ext(decision, "attribute")
    value_kind = _require_ext(decision, "valueKind")
    if value_kind not in _VALUE_KINDS:
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            f"valueKind {value_kind!r} is not a rule-IR value kind. "
            f"One of: {', '.join(_VALUE_KINDS)}.",
            loc,
        )

    _check_hit_policy(table.hit_policy, table.outputs, loc)

    if len(table.outputs) != 1:
        raise DmnCompileError(
            UNSUPPORTED_TABLE_SHAPE,
            f"decision table declares {len(table.outputs)} output columns. A duly "
            f"rule concludes exactly one attribute for one entity, so a compiled "
            f"table has exactly one output column; split a multi-output table into "
            f"one decision per output (spec/dmn.md M5).",
            loc,
        )
    if not table.rows:
        raise DmnCompileError(
            UNSUPPORTED_TABLE_SHAPE, "decision table has no rules.", loc
        )

    entity_var = decision.entity_var or _default_entity_var(entity_type)
    bindings = _resolve_bindings(table.inputs, entity_var, concluded, decision, loc)
    names = frozenset([b.label for b in bindings])

    rules: list[dict] = []
    row_facts: list[tuple[Row, dict[str, str], dict]] = []
    for row in table.rows:
        rule, guards = _compile_row(
            decision, row, bindings, names, entity_var, entity_type, attribute,
            value_kind, table.hit_policy, len(table.rows),
        )
        rules.append(rule)
        row_facts.append((row, guards, rule))

    if table.hit_policy == "UNIQUE":
        _check_unique_disjointness(decision, row_facts, loc)

    decision_entry = {"attribute": attribute, "entityType": entity_type}
    if decision.question:
        decision_entry["question"] = decision.question
    return decision_entry, rules


def _default_entity_var(entity_type: str) -> str:
    local = entity_type.rsplit(":", 1)[-1]
    return local[:1].lower() + local[1:] if local else "entity"


def _check_hit_policy(policy: str, outputs, loc: Location) -> None:
    expanded = _SINGLE_LETTER.get(policy, policy)
    if expanded in SUPPORTED_HIT_POLICIES:
        if expanded == "PRIORITY" and outputs and outputs[0].output_values:
            raise DmnCompileError(
                UNSUPPORTED_HIT_POLICY,
                "hit policy PRIORITY is compiled as descending rule priority in ROW "
                "order, but this table declares `outputValues` — under DMN, PRIORITY "
                "orders by the position of a row's output in that list, not by row "
                "position. Compiling it as row order would silently contradict the "
                "table. Remove `outputValues`, or reorder the rows and use FIRST "
                "(spec/dmn.md M2).",
                loc,
            )
        return
    reason = _UNSUPPORTED_HIT_POLICIES.get(expanded)
    if reason is None:
        raise DmnCompileError(
            UNSUPPORTED_HIT_POLICY,
            f"hit policy {policy!r} is not a DMN hit policy. "
            f"Supported: {', '.join(SUPPORTED_HIT_POLICIES)}.",
            loc,
        )
    raise DmnCompileError(
        UNSUPPORTED_HIT_POLICY,
        f"hit policy {expanded} is not supported in v1: {reason}. "
        f"Supported: {', '.join(SUPPORTED_HIT_POLICIES)} "
        f"(spec/dmn.md, \"Hit-policy mapping\").",
        loc,
    )


def _resolve_bindings(
    inputs: tuple[InputColumn, ...],
    entity_var: str,
    concluded: dict[str, str],
    decision: Decision,
    loc: Location,
) -> list[_Binding]:
    bindings: list[_Binding] = []
    seen: dict[str, str] = {}
    for column in inputs:
        label = column.label
        if not _IDENT.match(label):
            raise DmnCompileError(
                BINDING_ERROR,
                f"input column {column.index + 1} binds under the name {label!r}, "
                f"which is not a duly identifier ([A-Za-z_][A-Za-z0-9_]*). Set the "
                f"column's `label` attribute to a usable name.",
                Location(decision=decision.id, column=label, expression=column.expression),
            )
        if label in _RESERVED_NAMES:
            raise DmnCompileError(
                BINDING_ERROR,
                f"input column binds under {label!r}, which is reserved in the duly "
                f"expression language. Set the column's `label` attribute.",
                Location(decision=decision.id, column=label, expression=column.expression),
            )
        if label == entity_var:
            raise DmnCompileError(
                BINDING_ERROR,
                f"input column binds under {label!r}, which collides with the entity "
                f"binding for {decision.entity_type!r}. Set the column's `label`, or "
                f"set `entityVar` on `duly:decision`.",
                Location(decision=decision.id, column=label, expression=column.expression),
            )
        if label in seen:
            raise DmnCompileError(
                BINDING_ERROR,
                f"two input columns bind under {label!r} "
                f"({seen[label]} and {column.expression}). Give them distinct `label`s.",
                Location(decision=decision.id, column=label, expression=column.expression),
            )
        seen[label] = column.expression
        # A column whose CURIE is concluded by a decision in this document is a
        # `derived` binding — DMN's own information-requirement relation, read
        # off the decisions rather than off href plumbing.
        kind = "derived" if column.expression in concluded else "attribute"
        bindings.append(_Binding(label, kind, column.expression))
    return bindings


# ---------------------------------------------------------------------------
# One row
# ---------------------------------------------------------------------------


def _compile_row(
    decision: Decision,
    row: Row,
    bindings: list[_Binding],
    names: frozenset[str],
    entity_var: str,
    entity_type: str,
    attribute: str,
    value_kind: str,
    hit_policy: str,
    row_count: int,
) -> tuple[dict, dict[str, str]]:
    rule_id = _annotation(decision, row, ANN_RULE_ID)
    if not rule_id:
        raise DmnCompileError(
            MISSING_RULE_ID,
            f"row has no {ANN_RULE_ID!r} annotation. A duly rule id is the handle "
            f"every receipt cites, so it is authored, never derived: an id computed "
            f"from row position would silently re-label history the first time "
            f"somebody inserts a row above it "
            f"(spec/dmn.md, \"The annotation convention\").",
            Location(decision=decision.id, row=row.index),
        )
    loc = Location(decision=decision.id, row=row.index, rule_id=rule_id)

    _reject_unknown_annotations(row, loc)

    citation_text = _annotation(decision, row, ANN_CITATION)
    if not citation_text:
        raise DmnCompileError(
            MISSING_CITATION,
            f"row has no {ANN_CITATION!r} annotation. Every duly rule cites its "
            f"authority; the compiler will not invent a `TODO(verify)` on an "
            f"author's behalf. Cite the source, or — for a genuine presumption — "
            f"say so explicitly, e.g. \"Default presumption\" "
            f"(spec/dmn.md, \"The annotation convention\").",
            loc,
        )

    effective_from = _annotation(decision, row, ANN_EFFECTIVE_FROM)
    if not effective_from:
        raise DmnCompileError(
            MISSING_EFFECTIVE_DATE,
            f"row has no {ANN_EFFECTIVE_FROM!r} annotation. Rule selection is "
            f"effective-dated: without a start date the kernel cannot say which "
            f"rulebase was in force on the day being adjudicated.",
            loc,
        )
    _check_iso_date(effective_from, ANN_EFFECTIVE_FROM, loc)
    effective_to = _annotation(decision, row, ANN_EFFECTIVE_TO)
    if effective_to:
        _check_iso_date(effective_to, ANN_EFFECTIVE_TO, loc)

    if len(row.input_entries) != len(bindings):
        raise DmnCompileError(
            UNSUPPORTED_TABLE_SHAPE,
            f"row has {len(row.input_entries)} input entries but the table declares "
            f"{len(bindings)} input columns.",
            loc,
        )

    # Compile every cell first: a cell is only "irrelevant" to the bindings if
    # no other cell in the row names it.
    tests: list[InputTest] = []
    for binding, cell in zip(bindings, row.input_entries):
        cell_loc = Location(
            decision=decision.id, row=row.index, rule_id=rule_id,
            column=binding.label, expression=binding.curie, text=cell,
        )
        tests.append(compile_input_entry(cell, binding.label, names, cell_loc))

    out_loc = Location(
        decision=decision.id, row=row.index, rule_id=rule_id,
        column="<output>", expression=attribute, text=row.output_entry,
    )
    output = compile_output_entry(row.output_entry, names, out_loc)

    referenced: set[str] = set()
    for test in tests:
        referenced.update(test.references)
    referenced.update(output.references)

    given: dict = {entity_var: {"entityType": entity_type}}
    for binding, test in zip(bindings, tests):
        if test.irrelevant and binding.label not in referenced:
            # A `-` cell says the input is irrelevant to this row. Binding it
            # anyway would make the row require the fact to exist, quietly
            # turning a catch-all default into a conditional (spec/dmn.md M4).
            continue
        given[binding.label] = {binding.kind: binding.curie}

    when = [t.condition for t in tests if t.condition is not None]

    rule: dict = {"id": rule_id}
    if row.description:
        rule["description"] = row.description
    rule["version"] = _annotation(decision, row, ANN_VERSION) or DEFAULT_RULE_VERSION
    rule["priority"] = _priority(hit_policy, row.index, row_count)
    citation: dict = {"text": citation_text}
    url = _annotation(decision, row, ANN_CITATION_URL)
    if url:
        citation["url"] = url
    rule["citation"] = citation
    rule["effectiveFrom"] = effective_from
    if effective_to:
        rule["effectiveTo"] = effective_to
    rule["given"] = given
    if when:
        rule["when"] = when
    rule["then"] = {
        "entity": entity_var,
        "attribute": attribute,
        "value": _then_value(output, value_kind, decision, out_loc),
    }
    overrides = _annotation(decision, row, ANN_OVERRIDES)
    if overrides:
        rule["overrides"] = [o.strip() for o in overrides.split(",") if o.strip()]

    guards = {
        binding.curie: test.equality_literal
        for binding, test in zip(bindings, tests)
        if binding.kind == "attribute"
        and test.equality_literal is not None
        and binding.label in given
    }
    return rule, guards


def _priority(hit_policy: str, row_index: int, row_count: int) -> int:
    policy = _SINGLE_LETTER.get(hit_policy, hit_policy)
    if policy == "UNIQUE":
        # UNIQUE asserts the rows never overlap, so there is nothing to break a
        # tie between: they all sit at one priority and the disjointness check
        # below has to earn it.
        return 0
    return (row_count - row_index) * PRIORITY_STEP


def _annotation(decision: Decision, row: Row, name: str) -> str | None:
    value = row.annotations.get(name)
    return value.strip() if value and value.strip() else None


def _reject_unknown_annotations(row: Row, loc: Location) -> None:
    for name in sorted(row.annotations):
        if name.startswith("duly:") and name not in KNOWN_ANNOTATIONS:
            raise DmnCompileError(
                MALFORMED_DOCUMENT,
                f"unknown annotation column {name!r}. The `duly:` annotation "
                f"namespace is closed so that a typo is a failure rather than a "
                f"silently ignored citation. Known: {', '.join(KNOWN_ANNOTATIONS)}.",
                loc,
            )


def _check_iso_date(value: str, what: str, loc: Location) -> None:
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        raise DmnCompileError(
            MISSING_EFFECTIVE_DATE,
            f"{what} is {value!r}, which is not an ISO calendar date (YYYY-MM-DD).",
            loc,
        ) from None


def _unquote(raw: str) -> str:
    return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def _then_value(output, value_kind: str, decision: Decision, loc: Location) -> dict:
    literal: Endpoint | None = output.literal
    if literal is None:
        # Computed conclusion.
        if value_kind == "code":
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                "a `code` conclusion must be a string literal: the expression "
                "language has no way to construct a code value (a code carries a "
                "code system and version, which an arithmetic result does not).",
                loc,
            )
        value: dict = {"kind": value_kind}
        if value_kind == "money":
            value["currency"] = _require_currency(decision, loc)
        value["expr"] = output.expr
        return value

    if value_kind == "money":
        if literal.kind != "number":
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"a `money` conclusion needs a numeric amount; this cell is a "
                f"{literal.kind} literal.",
                loc,
            )
        return {"kind": "money", "amount": literal.raw, "currency": _require_currency(decision, loc)}
    if value_kind == "code":
        if literal.kind != "string":
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"a `code` conclusion needs a quoted code value; this cell is a "
                f"{literal.kind} literal.",
                loc,
            )
        if not decision.code_system:
            raise DmnCompileError(
                MALFORMED_DOCUMENT,
                "a `code` conclusion needs `codeSystem` on `duly:decision`; a bare "
                "code with no system is exactly the ambiguity the ontology gate "
                "exists to reject.",
                loc,
            )
        out = {"kind": "code", "value": _unquote(literal.raw), "codeSystem": decision.code_system}
        if decision.code_system_version:
            out["codeSystemVersion"] = decision.code_system_version
        return out
    if value_kind == "boolean":
        if literal.kind != "boolean":
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"a `boolean` conclusion needs `true` or `false`; this cell is a "
                f"{literal.kind} literal.",
                loc,
            )
        return {"kind": "boolean", "value": literal.raw == "true"}
    if value_kind == "decimal":
        if literal.kind != "number":
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"a `decimal` conclusion needs a number; this cell is a "
                f"{literal.kind} literal.",
                loc,
            )
        return {"kind": "decimal", "value": literal.raw}
    if value_kind == "date":
        if literal.kind == "date":
            return {"kind": "date", "value": _unquote(literal.raw[len("date("):-1])}
        if literal.kind == "string":
            iso = _unquote(literal.raw)
            _check_iso_date(iso, "output cell", loc)
            return {"kind": "date", "value": iso}
        raise DmnCompileError(
            UNSUPPORTED_EXPRESSION,
            f"a `date` conclusion needs `date(\"YYYY-MM-DD\")` or a quoted ISO date; "
            f"this cell is a {literal.kind} literal.",
            loc,
        )
    # string / entityRef
    if literal.kind != "string":
        raise DmnCompileError(
            UNSUPPORTED_EXPRESSION,
            f"a `{value_kind}` conclusion needs a quoted string; this cell is a "
            f"{literal.kind} literal.",
            loc,
        )
    return {"kind": value_kind, "value": _unquote(literal.raw)}


def _require_currency(decision: Decision, loc: Location) -> str:
    if not decision.currency:
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            "a `money` conclusion needs `currency` on `duly:decision`. DMN's "
            "`number` type carries no currency and the IR refuses to guess one.",
            loc,
        )
    return decision.currency


# ---------------------------------------------------------------------------
# UNIQUE disjointness
# ---------------------------------------------------------------------------


def _windows_overlap(a: dict, b: dict) -> bool:
    a_from, a_to = a.get("effectiveFrom"), a.get("effectiveTo")
    b_from, b_to = b.get("effectiveFrom"), b.get("effectiveTo")
    return (a_to is None or b_from is None or b_from < a_to) and (
        b_to is None or a_from is None or a_from < b_to
    )


def _check_unique_disjointness(decision: Decision, row_facts, loc: Location) -> None:
    """UNIQUE says the rows can never both match. duly's kernel refuses a pack
    whose same-priority rules it cannot *prove* disjoint, and it accepts exactly
    two proofs: non-overlapping effective windows, or contradictory
    quoted-string equality guards on the same bound attribute. Anything else —
    numeric ranges, boolean splits, `derived` bindings — is unprovable, and the
    compiler says so here rather than letting the kernel's message point at
    rule ids the author has to map back to rows themselves.

    The refusal is deliberate. Emitting pairwise `overrides` instead would turn
    "these rows never overlap" into "row 2 beats row 3" — an ordering the
    author did not write, silently substituted for the mutual-exclusion claim
    UNIQUE makes. If ordering IS what they mean, FIRST says so."""
    unprovable: list[str] = []
    for i, (row_a, guards_a, rule_a) in enumerate(row_facts):
        for row_b, guards_b, rule_b in row_facts[i + 1:]:
            if not _windows_overlap(rule_a, rule_b):
                continue
            if any(attr in guards_b and guards_b[attr] != lit for attr, lit in guards_a.items()):
                continue
            if rule_b["id"] in (rule_a.get("overrides") or []) or rule_a["id"] in (
                rule_b.get("overrides") or []
            ):
                continue
            unprovable.append(
                f"rows {row_a.index} and {row_b.index} "
                f"({rule_a['id']!r} / {rule_b['id']!r})"
            )
    if not unprovable:
        return
    raise DmnCompileError(
        UNPROVABLE_UNIQUE,
        "hit policy UNIQUE claims these rows can never both match, but their "
        "disjointness cannot be proven: " + "; ".join(unprovable) + ". The kernel "
        "accepts exactly two proofs for same-priority rules concluding one "
        "attribute — non-overlapping effective windows, or contradictory "
        "quoted-string equality guards on the same *attribute* binding (a "
        "numeric range, a boolean split, or a guard on a `derived` binding does "
        "NOT count). Either scope the rows with string equality cells, give them "
        "disjoint duly:effectiveFrom/duly:effectiveTo windows, or — if you meant "
        "\"the earlier row wins\" rather than \"they never overlap\" — use hit "
        "policy FIRST (spec/dmn.md, \"Refusal classes\").",
        loc,
    )
