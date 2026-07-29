"""Public entry point for the duly reference kernel."""

from __future__ import annotations

from .engine import evaluate_pack, normalize_point
from .ir import validate_pack
from .receipt import build_receipt


def adjudicate(
    facts: list[dict],
    pack: dict,
    as_of_effective: str,
    as_of_knowledge: str,
    decision_attribute: str,
) -> dict:
    """Adjudicate a case: evaluate `pack` over `facts` at the given
    bitemporal point and return a DecisionReceipt dict.

    - `facts`: GroundedFact dicts (spec/schemas/grounded-fact.schema.json).
    - `pack`: a rule-IR pack dict (spec/rule-ir.md); validated before use.
    - `as_of_effective` / `as_of_knowledge`: ISO dates or datetimes. A bare
      date means midnight UTC. No wall-clock defaulting — determinism is
      the caller's contract.
    - `decision_attribute`: the CURIE of the decision to answer.
    """
    validate_pack(pack)
    effective = normalize_point(as_of_effective)
    knowledge = normalize_point(as_of_knowledge)
    result = evaluate_pack(facts, pack, effective, knowledge)
    return build_receipt(result, pack, decision_attribute)
