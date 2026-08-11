"""Which attributes a decision can consult, read off the rule pack.

A receipt's `abstentions` are **case-wide**. The kernel filters the live-fact
universe once, before any rule runs (spec/rule-ir.md, "Abstention policy"), so
every receipt produced for a case carries every exclusion that case had —
including exclusions of attributes the decided question's rules never look at.
That is deliberate and it is inside the receipt hash, so it is not going to
change: a decision made over evidence with a known deficiency should say so.

What it leaves open is a *presentation* question with one correct answer per
reader: is this particular exclusion relevant to this particular question? A
surface that cannot tell shows a `low_confidence` entry beside a decision whose
rules never wanted the attribute, and the entry reads as a bug. A surface that
answers it differently from the next surface is worse — that is the defect
[`phrasing`](phrasing.py) exists to prevent, one decision coming out worded two
ways.

So the relationship is computed once, here, from the pack, and never stored.
Nothing in this module can reach a receipt.
"""

from __future__ import annotations

from typing import Any

__all__ = ["consulted_attributes"]


def consulted_attributes(pack: Any, attribute: str | None) -> set[str] | None:
    """The fact attributes the rules concluding `attribute` can read.

    Returns the transitive closure over `given` bindings — an `attribute:`
    binding is a fact the rule reads, a `derived:` binding is another decision
    whose own rules are then followed — and includes `attribute` itself.
    Returns `None` when there is no pack or no attribute to ask about, which
    callers must treat as *unknown* rather than as an empty set: "we cannot
    tell" and "consults nothing" are different answers, and only the second one
    licenses hiding something from a reader.

    Static and deliberately over-broad. It reports what the *rules* could
    consult, not what this run did: a guard that short-circuits, a rule outside
    its effective window, and a binding that never resolved are all still
    reported. Over-broad is the safe direction — the cost is showing a reader
    something they did not need, where under-reporting would hide an exclusion
    that actually shaped their answer.
    """
    if not isinstance(pack, dict) or not attribute:
        return None

    by_conclusion: dict[str, list[dict[str, Any]]] = {}
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        conclusion = (rule.get("then") or {}).get("attribute")
        if conclusion:
            by_conclusion.setdefault(conclusion, []).append(rule)

    consulted: set[str] = set()
    pending = [attribute]
    while pending:
        current = pending.pop()
        if current in consulted:
            continue
        consulted.add(current)
        for rule in by_conclusion.get(current, []):
            for binding in (rule.get("given") or {}).values():
                if not isinstance(binding, dict):
                    continue
                if binding.get("attribute"):
                    consulted.add(str(binding["attribute"]))
                elif binding.get("derived"):
                    pending.append(str(binding["derived"]))
    return consulted
