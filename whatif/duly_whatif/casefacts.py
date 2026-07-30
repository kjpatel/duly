"""Reconstructing a case with one input changed, and running the kernel on it.

This is the "kernel disposes" half of the contract. The solver proposes a
value for the freed input; everything here turns that value back into a real
case — a schema-valid `GroundedFact` set, or a different evaluation point —
and asks `duly_kernel.api.adjudicate` what it decides.

Two rules govern the reconstruction, both of them repo invariants rather than
local choices:

- **A changed fact is a new fact.** Facts are content-addressed (CLAUDE.md,
  "Content addressing"), so a hypothetical value produces a new `contentHash`
  and a new `id`. Nothing is mutated in place; the caller's fact list is left
  untouched.
- **Liveness is the kernel's own.** Which facts actually bind — after
  supersession, effective windows, the pack's abstention policy and conflict
  resolution — is decided by importing the kernel's own helpers rather than
  by reimplementing them here. A second implementation of liveness would be
  the same latent defect as a second SMT encoder: two things that agree until
  they don't.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
from decimal import Decimal

from duly_kernel.api import adjudicate

# Private, deliberately: these ARE the kernel's liveness semantics. Mirroring
# them locally would let the encoding's view of "which facts bind" drift away
# from the kernel's, which is exactly the divergence this package exists to
# make impossible. If a kernel refactor moves them, this import fails loudly
# at collection time rather than producing quietly wrong pins.
from duly_kernel.engine import (  # noqa: PLC2701
    _apply_abstention_policy,
    _live_facts,
)
from duly_kernel.engine import normalize_point

__all__ = [
    "canonical",
    "content_hash",
    "live_by_attribute",
    "substitute",
    "decide",
    "normalize_point",
    "parse_date",
    "render_value",
    "values_equal",
    "KernelOutcome",
]


def canonical(obj) -> bytes:
    """Canonical JSON, byte-identical to `spec/validate.py` and the kernel."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(doc: dict, hash_field: str = "contentHash") -> str:
    body = {k: v for k, v in doc.items() if k not in ("id", hash_field)}
    return hashlib.sha256(canonical(body)).hexdigest()


def _readdress(fact: dict) -> dict:
    """`fact` with its content hash and id recomputed from its body."""
    body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
    digest = content_hash(body)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **body}


def live_by_attribute(facts: list[dict], pack: dict, as_of_effective: str) -> dict[str, dict]:
    """The facts that actually bind, keyed by attribute CURIE.

    Exactly the kernel's own notion: asserted, inside its effective window at
    the evaluation point, surviving the pack's abstention policy, and the
    unique live fact for its attribute. An attribute with two live facts is
    *unbindable* (the kernel abstains), so it is absent from the result — the
    encoding must pin its `exists` to false, not to true.
    """
    effective = normalize_point(as_of_effective)
    live = _live_facts(facts, effective)
    live, _excluded = _apply_abstention_policy(live, pack)

    groups: dict[str, list[dict]] = {}
    for fact in live:
        groups.setdefault(fact["attribute"], []).append(fact)

    out: dict[str, dict] = {}
    for attribute, group in groups.items():
        if len(group) == 1:
            out[attribute] = group[0]
            continue
        # Conflict resolution (spec/grounded-facts.md): a lone human assertion
        # outranks machine ones; anything else leaves the attribute unbindable.
        human = [f for f in group if f["assertion"]["kind"] == "human"]
        if len(human) == 1:
            out[attribute] = human[0]
    return out


def substitute(facts: list[dict], attribute: str, value: dict) -> list[dict]:
    """`facts` with `attribute`'s value replaced, re-addressed, order preserved.

    The caller's list and dicts are untouched: a what-if run must not leave a
    fingerprint on the case it reasoned about.
    """
    out: list[dict] = []
    for fact in facts:
        if fact["attribute"] != attribute:
            out.append(fact)
            continue
        changed = copy.deepcopy(fact)
        changed["value"] = value
        out.append(_readdress(changed))
    return out


# There is deliberately no `mint`: what-if varies a value the case already
# carries, and never fabricates the fact, the entity, or the grounding a new
# one would need. duly's premise is that a fact is *grounded* — it points at a
# document span or a named attestation — and a value a solver proposed is
# grounded in nothing. Freeing an attribute the case does not assert is a
# named refusal in `query.solve`, not a synthesised fact.


# ---------------------------------------------------------------------------
# Running the kernel
# ---------------------------------------------------------------------------


class KernelOutcome:
    """What the kernel said about one hypothetical case.

    A run that reaches no conclusion is an *outcome*, not an exception to
    swallow: "no rule concludes" is frequently the honest answer to a what-if,
    and it has to be distinguishable from "the decision was False".
    """

    __slots__ = ("value", "error", "receipt")

    def __init__(self, value: dict | None, error: str | None, receipt: dict | None):
        self.value = value
        self.error = error
        self.receipt = receipt

    @property
    def decided(self) -> bool:
        return self.value is not None

    def matches(self, target: dict | None) -> bool:
        """Whether this outcome is the target one.

        `target is None` means "no decision" — the target of a flip away from
        a pack that currently concludes something.
        """
        if target is None:
            return not self.decided
        if not self.decided:
            return False
        return values_equal(self.value, target)

    def render(self) -> str:
        if self.error is not None:
            return f"(no decision: {self.error})"
        return render_value(self.value)


def decide(
    facts: list[dict],
    pack: dict,
    as_of_effective: str,
    as_of_knowledge: str,
    decision: str,
) -> KernelOutcome:
    """Adjudicate, turning a no-conclusion run into an outcome rather than a raise."""
    try:
        receipt = adjudicate(facts, pack, as_of_effective, as_of_knowledge, decision)
    except Exception as exc:  # noqa: BLE001 - every failure mode is "no decision"
        return KernelOutcome(None, f"{type(exc).__name__}: {exc}", None)
    return KernelOutcome(receipt["decision"]["value"], None, receipt)


# ---------------------------------------------------------------------------
# Value comparison and rendering
# ---------------------------------------------------------------------------


def values_equal(a: dict, b: dict) -> bool:
    """Kernel-semantics equality between two fact value dicts.

    Money and decimal compare *numerically*: `0.1` and `0.10` are one value to
    the kernel's comparison operators even though they are two receipt byte
    strings (spec/pack-verification.md, "Decimals are not reals"). Comparing
    them as strings here would make a target of `0.00` miss a decision of
    `0.0` — a spurious contradiction, which is the one failure this package
    must never manufacture.
    """
    if a.get("kind") != b.get("kind"):
        return False
    kind = a["kind"]
    if kind == "money":
        if a.get("currency") != b.get("currency"):
            return False
        return Decimal(str(a["amount"])) == Decimal(str(b["amount"]))
    if kind == "decimal":
        return Decimal(str(a["value"])) == Decimal(str(b["value"]))
    if kind == "code":
        return str(a["value"]) == str(b["value"])
    return a["value"] == b["value"]


def render_value(value: dict) -> str:
    kind = value["kind"]
    if kind == "boolean":
        return "true" if value["value"] else "false"
    if kind == "money":
        return f"{value['amount']} {value['currency']}"
    if kind in ("decimal", "date", "datetime"):
        return str(value["value"])
    return f'"{value["value"]}"'


def parse_date(text: str) -> _dt.date:
    return _dt.date.fromisoformat(text)
