"""Deterministic rule evaluation (spec/rule-ir.md).

No wall-clock reads, no randomness. The bitemporal evaluation point comes
entirely from the caller. Dict iteration never affects output ordering:
rules are processed in pack order (within dependency strata), fact groups
in sorted order.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from . import ir as _ir
from .expr import (
    BoolV,
    EntityRefV,
    ExprTypeError,
    Value,
    evaluate,
    parse,
    parse_datetime,
    value_from_fact,
    value_to_fact,
)


class AdjudicationError(Exception):
    """The run could not produce a decision (bad inputs or no conclusion)."""


# A premise recorded on a firing, in `given` order:
#   ("fact", fact_id)                      — an attribute binding
#   ("derived", attribute, producer_rule)  — a derived binding
Premise = tuple


@dataclass
class Firing:
    rule: dict
    entity_id: str
    attribute: str
    value: Value
    premises: list[Premise] = field(default_factory=list)
    defeated: list[str] = field(default_factory=list)

    @property
    def rule_id(self) -> str:
        return self.rule["id"]


@dataclass
class EvalResult:
    case_id: str
    effective: _dt.datetime
    knowledge: _dt.datetime
    firings: dict[str, Firing]          # every rule that fired, by id
    surviving: list[Firing]             # firings whose conclusion survived, pack order
    fact_by_id: dict[str, dict]
    conflicts: list[dict]               # abstention entries, reason "conflict"

    def surviving_for(self, attribute: str) -> Firing | None:
        candidates = [f for f in self.surviving if f.attribute == attribute]
        return candidates[0] if candidates else None


def _as_utc(dt: _dt.datetime) -> _dt.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def normalize_point(s: str, *, end_of_day: bool = False) -> _dt.datetime:
    """Parse an asOf point: a bare date becomes midnight UTC (or 23:59:59Z
    when end_of_day), a datetime is taken as-is (naive = UTC)."""
    try:
        d = _dt.date.fromisoformat(s)
    except ValueError:
        return _as_utc(parse_datetime(s))
    t = _dt.time(23, 59, 59) if end_of_day else _dt.time(0, 0, 0)
    return _dt.datetime.combine(d, t, tzinfo=_dt.timezone.utc)


def _window_contains(point: _dt.datetime, frm: object, to: object) -> bool:
    """[frm, to) containment; either bound may be absent."""
    if frm is not None and point < normalize_point(str(frm)):
        return False
    if to is not None and point >= normalize_point(str(to)):
        return False
    return True


def _live_facts(facts: list[dict], effective: _dt.datetime) -> list[dict]:
    """Facts participating in the run: asserted (not superseded/retracted)
    and effective at asOf.effective when they carry a window.

    v0 note: asOf.knowledge is echoed on the receipt but does not filter
    facts — the caller supplies the fact set as known at the knowledge
    point (a bitemporal store projection is a later layer).
    """
    live = []
    for fact in facts:
        if fact.get("status", "asserted") != "asserted":
            continue
        if not _window_contains(effective, fact.get("effectiveFrom"), fact.get("effectiveTo")):
            continue
        live.append(fact)
    return live


def evaluate_pack(
    facts: list[dict],
    pack: dict,
    effective: _dt.datetime,
    knowledge: _dt.datetime,
) -> EvalResult:
    if not facts:
        raise AdjudicationError("no facts supplied")
    case_ids = sorted({f["caseId"] for f in facts})
    if len(case_ids) != 1:
        raise AdjudicationError(f"facts span multiple cases: {case_ids}")
    case_id = case_ids[0]
    fact_by_id = {f["id"]: f for f in facts}

    live = _live_facts(facts, effective)

    # Fact conflicts: two live facts asserting the same attribute of the
    # same entity. Resolution policy (spec/grounded-facts.md, "conflict
    # resolution"): if exactly one of the conflicting facts is human-asserted,
    # it outranks the machine assertions and binds; otherwise the attribute
    # becomes unbindable and the run records an abstention with reason
    # "conflict".
    by_entity_attr: dict[tuple[str, str], list[dict]] = {}
    for fact in live:
        by_entity_attr.setdefault((fact["entity"]["id"], fact["attribute"]), []).append(fact)
    conflicts = []
    conflicted_attrs: set[str] = set()
    outranked_ids: set[str] = set()
    for (entity_id, attribute), group in sorted(by_entity_attr.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if len(group) > 1:
            human = [f for f in group if f["assertion"]["kind"] == "human"]
            if len(human) == 1:
                outranked_ids.update(f["id"] for f in group if f is not human[0])
                continue
            conflicted_attrs.add(attribute)
            conflicts.append(
                {
                    "entity": entity_id,
                    "attribute": attribute,
                    "reason": "conflict",
                    "facts": sorted(f["id"] for f in group),
                }
            )
    if outranked_ids:
        live = [f for f in live if f["id"] not in outranked_ids]

    # Binding indexes (v0: one live fact per attribute, one entity per type).
    facts_by_attr: dict[str, list[dict]] = {}
    for fact in live:
        facts_by_attr.setdefault(fact["attribute"], []).append(fact)
    entities_by_type: dict[str, list[str]] = {}
    for fact in live:
        etype, eid = fact["entity"]["type"], fact["entity"]["id"]
        ids = entities_by_type.setdefault(etype, [])
        if eid not in ids:
            ids.append(eid)

    # Rules effective at asOf.effective, in pack order.
    rules = [
        r for r in pack["rules"]
        if _window_contains(effective, r.get("effectiveFrom"), r.get("effectiveTo"))
    ]

    # Evaluate in dependency strata so every producer of a derived attribute
    # is settled before any consumer binds it.
    strata = _ir.rule_strata(pack["rules"])
    pack_order = {r["id"]: i for i, r in enumerate(pack["rules"])}
    firings: dict[str, Firing] = {}
    for level in sorted({strata[r["id"]] for r in rules} or {0}):
        for rule in rules:
            if strata[rule["id"]] != level:
                continue
            firing = _try_fire(rule, facts_by_attr, entities_by_type, conflicted_attrs, firings, pack_order)
            if firing is not None:
                firings[rule["id"]] = firing

    surviving = _apply_defeat(firings, pack_order)
    return EvalResult(
        case_id=case_id,
        effective=effective,
        knowledge=knowledge,
        firings=firings,
        surviving=surviving,
        fact_by_id=fact_by_id,
        conflicts=conflicts,
    )


def _select_producer(
    attribute: str,
    firings: dict[str, Firing],
    pack_order: dict[str, int],
) -> Firing | None:
    """Among fired rules concluding `attribute`, the one whose conclusion
    currently survives overrides + priority."""
    suppressed: set[str] = set()
    for f in firings.values():
        for target in f.rule.get("overrides") or []:
            if target in firings:
                suppressed.add(target)
    candidates = [
        f for f in firings.values()
        if f.attribute == attribute and f.rule_id not in suppressed
    ]
    if not candidates:
        return None
    top = max(f.rule["priority"] for f in candidates)
    winners = sorted(
        (f for f in candidates if f.rule["priority"] == top),
        key=lambda f: pack_order[f.rule_id],
    )
    if len(winners) > 1:
        raise AdjudicationError(
            f"ambiguous conclusions for {attribute!r} at priority {top}: "
            + ", ".join(f.rule_id for f in winners)
        )
    return winners[0]


def _try_fire(
    rule: dict,
    facts_by_attr: dict[str, list[dict]],
    entities_by_type: dict[str, list[str]],
    conflicted_attrs: set[str],
    firings: dict[str, Firing],
    pack_order: dict[str, int],
) -> Firing | None:
    env: dict[str, Value] = {}
    entity_vars: dict[str, str] = {}
    premises: list[Premise] = []

    for name, binding in rule["given"].items():
        (kind, ref), = binding.items()
        if kind == "attribute":
            if ref in conflicted_attrs:
                return None
            group = facts_by_attr.get(ref, [])
            if len(group) != 1:
                return None  # missing (or cross-entity duplicate): inapplicable
            fact = group[0]
            env[name] = value_from_fact(fact["value"])
            premises.append(("fact", fact["id"]))
        elif kind == "entityType":
            ids = entities_by_type.get(ref, [])
            if len(ids) != 1:
                return None
            entity_vars[name] = ids[0]
            env[name] = EntityRefV(ids[0])
        elif kind == "derived":
            producer = _select_producer(ref, firings, pack_order)
            if producer is None:
                return None
            env[name] = producer.value
            premises.append(("derived", ref, producer.rule_id))
        else:  # pragma: no cover - validation rejects unknown kinds
            return None

    for cond in rule.get("when") or []:
        result = evaluate(parse(cond), env)
        if not isinstance(result, BoolV):
            raise ExprTypeError(
                f"rule {rule['id']!r}: 'when' expression {cond!r} is not boolean"
            )
        if not result.value:
            return None

    entity_var = rule["then"]["entity"]
    if entity_var not in entity_vars:
        raise AdjudicationError(
            f"rule {rule['id']!r}: then.entity {entity_var!r} is not an entityType binding"
        )
    value = _conclude_value(rule, env)
    return Firing(
        rule=rule,
        entity_id=entity_vars[entity_var],
        attribute=rule["then"]["attribute"],
        value=value,
        premises=premises,
    )


def _conclude_value(rule: dict, env: dict[str, Value]) -> Value:
    spec = rule["then"]["value"]
    declared = spec["kind"]
    if "expr" in spec:
        result = evaluate(parse(spec["expr"]), env)
        actual = value_to_fact(result)["kind"]
        if actual != declared:
            raise ExprTypeError(
                f"rule {rule['id']!r}: then.value declares kind {declared!r} "
                f"but expression produced {actual!r}"
            )
        if declared == "money" and result.currency != spec["currency"]:  # type: ignore[union-attr]
            raise ExprTypeError(
                f"rule {rule['id']!r}: then.value declares currency {spec['currency']!r} "
                f"but expression produced {result.currency!r}"  # type: ignore[union-attr]
            )
        return result
    return value_from_fact(spec)


def _apply_defeat(firings: dict[str, Firing], pack_order: dict[str, int]) -> list[Firing]:
    """Apply overrides then priority tiebreak; return surviving firings in
    pack order with `defeated` lists populated on the winners."""
    ordered = sorted(firings.values(), key=lambda f: pack_order[f.rule_id])

    suppressed: set[str] = set()
    for f in ordered:
        for target in f.rule.get("overrides") or []:
            if target in firings:
                f.defeated.append(target)
                suppressed.add(target)

    alive = [f for f in ordered if f.rule_id not in suppressed]

    # Priority tiebreak among same-(entity, attribute) survivors.
    groups: dict[tuple[str, str], list[Firing]] = {}
    for f in alive:
        groups.setdefault((f.entity_id, f.attribute), []).append(f)
    losers: set[str] = set()
    for key in sorted(groups):
        group = groups[key]
        if len(group) < 2:
            continue
        top = max(f.rule["priority"] for f in group)
        winners = [f for f in group if f.rule["priority"] == top]
        if len(winners) > 1:
            raise AdjudicationError(
                f"ambiguous conclusions for {key[1]!r} on {key[0]!r} at priority {top}: "
                + ", ".join(f.rule_id for f in winners)
            )
        winner = winners[0]
        for f in group:
            if f is not winner:
                winner.defeated.append(f.rule_id)
                losers.add(f.rule_id)

    return [f for f in alive if f.rule_id not in losers]
