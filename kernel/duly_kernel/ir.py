"""Rule IR loading and pack validation (spec/rule-ir.md).

A pack is a dict (typically parsed from YAML) with `pack`, `decisions`, and
`rules`. Validation checks required fields, id uniqueness, `overrides`
referential integrity, cycles in the `derived` dependency graph, and
same-attribute/same-priority ambiguity.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import yaml

from . import expr as _expr


class PackValidationError(Exception):
    """The pack does not conform to the rule IR."""


_VALUE_KINDS = {"string", "decimal", "money", "date", "datetime", "boolean", "code", "entityRef"}
_BINDING_KINDS = {"attribute", "derived", "entityType"}


def load_pack(path: str | Path) -> dict:
    """Load a pack YAML file and validate it."""
    with open(path, "r", encoding="utf-8") as f:
        pack = yaml.safe_load(f)
    validate_pack(pack)
    return pack


def validate_pack(pack: dict) -> None:
    """Raise PackValidationError unless `pack` is a valid rule-IR pack."""
    if not isinstance(pack, dict):
        raise PackValidationError("pack document must be a mapping")

    meta = pack.get("pack")
    if not isinstance(meta, dict):
        raise PackValidationError("missing 'pack' section")
    for field in ("name", "version"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            raise PackValidationError(f"pack.{field} is required and must be a non-empty string")

    decisions = pack.get("decisions", [])
    if not isinstance(decisions, list):
        raise PackValidationError("'decisions' must be a list")
    for i, d in enumerate(decisions):
        if not isinstance(d, dict) or not isinstance(d.get("attribute"), str):
            raise PackValidationError(f"decisions[{i}] must have an 'attribute' CURIE")

    _validate_abstention_policy(pack.get("abstentionPolicy"))

    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        raise PackValidationError("'rules' must be a non-empty list")

    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        _validate_rule(rule, i, seen_ids)

    ids = {r["id"] for r in rules}
    for rule in rules:
        for target in rule.get("overrides", []) or []:
            if target not in ids:
                raise PackValidationError(
                    f"rule {rule['id']!r} overrides unknown rule {target!r}"
                )

    _check_derived_cycles(rules)
    _check_priority_ambiguity(rules)


def _validate_abstention_policy(policy: object) -> None:
    """Validate the optional pack-level abstention policy
    (spec/rule-ir.md, "Abstention policy")."""
    if policy is None:
        return
    if not isinstance(policy, dict):
        raise PackValidationError("'abstentionPolicy' must be a mapping")
    unknown = set(policy) - {"minConfidence", "attributes", "routeTo"}
    if unknown:
        raise PackValidationError(
            f"abstentionPolicy has unknown key(s): {', '.join(sorted(unknown))}"
        )
    _validate_confidence_floor(policy.get("minConfidence"), "abstentionPolicy.minConfidence")
    route_to = policy.get("routeTo")
    if route_to is not None and (not isinstance(route_to, str) or not route_to):
        raise PackValidationError("abstentionPolicy.routeTo must be a non-empty string")
    attributes = policy.get("attributes")
    if attributes is None:
        return
    if not isinstance(attributes, dict):
        raise PackValidationError(
            "abstentionPolicy.attributes must be a mapping of attribute CURIEs to floors"
        )
    for attr, floor in attributes.items():
        if not isinstance(attr, str) or not attr:
            raise PackValidationError(
                "abstentionPolicy.attributes keys must be non-empty attribute CURIEs"
            )
        _validate_confidence_floor(floor, f"abstentionPolicy.attributes[{attr!r}]")


def _validate_confidence_floor(v: object, where: str) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PackValidationError(f"{where} is required and must be a number in [0, 1]")
    if not 0 <= v <= 1:
        raise PackValidationError(f"{where} must be within [0, 1]")


def _validate_rule(rule: object, index: int, seen_ids: set[str]) -> None:
    where = f"rules[{index}]"
    if not isinstance(rule, dict):
        raise PackValidationError(f"{where} must be a mapping")

    rid = rule.get("id")
    if not isinstance(rid, str) or not rid:
        raise PackValidationError(f"{where}.id is required and must be a non-empty string")
    if rid in seen_ids:
        raise PackValidationError(f"duplicate rule id {rid!r}")
    seen_ids.add(rid)
    where = f"rule {rid!r}"

    if not isinstance(rule.get("version"), str) or not rule["version"]:
        raise PackValidationError(f"{where}: 'version' is required")
    if not isinstance(rule.get("priority"), int) or isinstance(rule.get("priority"), bool):
        raise PackValidationError(f"{where}: 'priority' is required and must be an integer")

    citation = rule.get("citation")
    if not isinstance(citation, dict) or not isinstance(citation.get("text"), str):
        raise PackValidationError(f"{where}: 'citation' must be a mapping with 'text'")

    _validate_iso_date(rule.get("effectiveFrom"), f"{where}.effectiveFrom", required=True)
    _validate_iso_date(rule.get("effectiveTo"), f"{where}.effectiveTo", required=False)

    given = rule.get("given")
    if not isinstance(given, dict) or not given:
        raise PackValidationError(f"{where}: 'given' is required and must be a non-empty mapping")
    for name, binding in given.items():
        if not isinstance(binding, dict) or len(binding) != 1:
            raise PackValidationError(
                f"{where}: given.{name} must be a single-key mapping "
                f"(one of {sorted(_BINDING_KINDS)})"
            )
        (kind, ref), = binding.items()
        if kind not in _BINDING_KINDS:
            raise PackValidationError(f"{where}: given.{name} has unknown binding kind {kind!r}")
        if not isinstance(ref, str) or not ref:
            raise PackValidationError(f"{where}: given.{name}.{kind} must be a non-empty string")

    when = rule.get("when", [])
    if when is None:
        when = []
    if not isinstance(when, list):
        raise PackValidationError(f"{where}: 'when' must be a list of expressions")
    for j, cond in enumerate(when):
        if not isinstance(cond, str):
            raise PackValidationError(f"{where}: when[{j}] must be an expression string")
        try:
            _expr.parse(cond)
        except _expr.ExprError as e:
            raise PackValidationError(f"{where}: when[{j}] does not parse: {e}") from None

    then = rule.get("then")
    if not isinstance(then, dict):
        raise PackValidationError(f"{where}: 'then' is required")
    if not isinstance(then.get("entity"), str) or then["entity"] not in given:
        raise PackValidationError(
            f"{where}: then.entity must name a 'given' binding"
        )
    if not isinstance(then.get("attribute"), str) or not then["attribute"]:
        raise PackValidationError(f"{where}: then.attribute is required")
    _validate_then_value(then.get("value"), where)

    overrides = rule.get("overrides", [])
    if overrides is None:
        overrides = []
    if not isinstance(overrides, list) or not all(isinstance(o, str) for o in overrides):
        raise PackValidationError(f"{where}: 'overrides' must be a list of rule ids")
    if rid in overrides:
        raise PackValidationError(f"{where}: a rule cannot override itself")


def _validate_then_value(value: object, where: str) -> None:
    if not isinstance(value, dict):
        raise PackValidationError(f"{where}: then.value must be a mapping")
    kind = value.get("kind")
    if kind not in _VALUE_KINDS:
        raise PackValidationError(f"{where}: then.value.kind must be one of {sorted(_VALUE_KINDS)}")
    has_expr = "expr" in value
    if has_expr:
        if not isinstance(value["expr"], str):
            raise PackValidationError(f"{where}: then.value.expr must be a string")
        try:
            _expr.parse(value["expr"])
        except _expr.ExprError as e:
            raise PackValidationError(f"{where}: then.value.expr does not parse: {e}") from None
        if kind == "money" and not isinstance(value.get("currency"), str):
            raise PackValidationError(f"{where}: computed money value requires 'currency'")
    else:
        if kind == "money":
            if "amount" not in value or "currency" not in value:
                raise PackValidationError(f"{where}: literal money value requires amount and currency")
        elif "value" not in value:
            raise PackValidationError(f"{where}: then.value requires 'value' or 'expr'")


def _validate_iso_date(v: object, where: str, *, required: bool) -> None:
    if v is None:
        if required:
            raise PackValidationError(f"{where} is required")
        return
    if not isinstance(v, (str, _dt.date)):
        raise PackValidationError(f"{where} must be an ISO date string")
    if isinstance(v, str):
        try:
            _dt.date.fromisoformat(v)
        except ValueError:
            try:
                _expr.parse_datetime(v)
            except ValueError:
                raise PackValidationError(f"{where} is not a valid ISO date: {v!r}") from None


def derived_attributes(rule: dict) -> list[str]:
    """The attributes this rule consumes via `derived` bindings, in given order."""
    out = []
    for binding in rule["given"].values():
        if "derived" in binding:
            out.append(binding["derived"])
    return out


def _check_derived_cycles(rules: list[dict]) -> None:
    """Cycle detection over the derived-dependency graph.

    Edge: rule R -> rule S when R has a `derived` binding on attribute A and
    S concludes A.
    """
    producers: dict[str, list[str]] = {}
    for rule in rules:
        producers.setdefault(rule["then"]["attribute"], []).append(rule["id"])

    edges: dict[str, list[str]] = {r["id"]: [] for r in rules}
    for rule in rules:
        for attr in derived_attributes(rule):
            edges[rule["id"]].extend(producers.get(attr, []))

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {rid: WHITE for rid in edges}

    def visit(rid: str, stack: list[str]) -> None:
        color[rid] = GRAY
        stack.append(rid)
        for dep in edges[rid]:
            if color[dep] == GRAY:
                cycle = stack[stack.index(dep):] + [dep]
                raise PackValidationError(
                    "cycle in derived dependencies: " + " -> ".join(cycle)
                )
            if color[dep] == WHITE:
                visit(dep, stack)
        stack.pop()
        color[rid] = BLACK

    for rid in sorted(edges):
        if color[rid] == WHITE:
            visit(rid, [])


def _windows_overlap(a: dict, b: dict) -> bool:
    """Effective windows are [from, to); versioned rules with disjoint windows
    can never both be in force, so they are not ambiguous."""
    a_from, a_to = a.get("effectiveFrom"), a.get("effectiveTo")
    b_from, b_to = b.get("effectiveFrom"), b.get("effectiveTo")
    return (a_to is None or b_from is None or b_from < a_to) and (
        b_to is None or a_from is None or a_from < b_to
    )


_EQ_GUARD = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*==\s*"([^"]*)"\s*$')


def _equality_guards(rule: dict) -> dict[str, str]:
    """Map bound-attribute CURIE -> required literal, for `when` items of the
    syntactic form `var == "literal"` where var is an attribute binding.

    Used only to prove disjointness: two rules requiring different literals
    for the same attribute can never both fire on one case (v0: one live fact
    per attribute)."""
    guards: dict[str, str] = {}
    given = rule.get("given") or {}
    for item in rule.get("when") or []:
        m = _EQ_GUARD.match(item)
        if not m:
            continue
        var, literal = m.group(1), m.group(2)
        binding = given.get(var)
        if isinstance(binding, dict) and "attribute" in binding:
            guards[binding["attribute"]] = literal
    return guards


def _guards_disjoint(a: dict, b: dict) -> bool:
    ga, gb = _equality_guards(a), _equality_guards(b)
    return any(attr in gb and gb[attr] != lit for attr, lit in ga.items())


def _check_priority_ambiguity(rules: list[dict]) -> None:
    """Two rules concluding the same attribute at the same priority make the
    pack ambiguous — unless they can provably never both apply: disjoint
    effective windows (rule versioning) or contradictory equality guards on
    the same attribute (e.g. jurisdiction scoping: state == "US-NY" vs
    state == "US-FL"), or one overrides the other."""
    by_attr: dict[str, list[dict]] = {}
    for rule in rules:
        by_attr.setdefault(rule["then"]["attribute"], []).append(rule)
    for attr, group in sorted(by_attr.items()):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a["priority"] != b["priority"]:
                    continue
                if not _windows_overlap(a, b):
                    continue
                if _guards_disjoint(a, b):
                    continue
                a_over = set(a.get("overrides") or [])
                b_over = set(b.get("overrides") or [])
                if b["id"] in a_over or a["id"] in b_over:
                    continue
                raise PackValidationError(
                    f"ambiguous pack: rules {a['id']!r} and {b['id']!r} both conclude "
                    f"{attr!r} at priority {a['priority']}, cannot be proven disjoint "
                    f"(by effective window or equality guards), and neither overrides "
                    f"the other"
                )


def rule_strata(rules: list[dict]) -> dict[str, int]:
    """Assign each rule a stratum: rules with no derived bindings are 0; a
    rule consuming derived attribute A sits strictly above every producer of A.

    Assumes the pack passed cycle validation.
    """
    producers: dict[str, list[dict]] = {}
    by_id = {r["id"]: r for r in rules}
    for rule in rules:
        producers.setdefault(rule["then"]["attribute"], []).append(rule)

    memo: dict[str, int] = {}

    def stratum(rid: str) -> int:
        if rid in memo:
            return memo[rid]
        rule = by_id[rid]
        level = 0
        for attr in derived_attributes(rule):
            for producer in producers.get(attr, []):
                level = max(level, stratum(producer["id"]) + 1)
        memo[rid] = level
        return level

    for rid in sorted(by_id):
        stratum(rid)
    return memo
