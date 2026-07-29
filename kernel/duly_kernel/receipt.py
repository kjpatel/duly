"""DecisionReceipt emission (spec/schemas/decision-receipt.schema.json).

Content addressing follows spec/validate.py: SHA-256 over the JCS-style
canonical JSON (sorted keys, minimal separators, UTF-8, ensure_ascii=False)
of the receipt excluding `id` and `receiptSha256`.
"""

from __future__ import annotations

import hashlib
import json

from . import __version__
from .engine import AdjudicationError, EvalResult, Firing
from .expr import format_datetime, value_to_fact


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(doc: dict, hash_field: str) -> str:
    body = {k: v for k, v in doc.items() if k not in ("id", hash_field)}
    return hashlib.sha256(canonical(body)).hexdigest()


def _rule_ref(firing: Firing) -> dict:
    rule = firing.rule
    citation = {"text": rule["citation"]["text"]}
    if rule["citation"].get("url"):
        citation["url"] = rule["citation"]["url"]
    ref = {
        "ruleId": rule["id"],
        "version": rule["version"],
        "citation": citation,
        "priority": rule["priority"],
        "effectiveFrom": _datestamp(rule["effectiveFrom"]),
    }
    if rule.get("effectiveTo") is not None:
        ref["effectiveTo"] = _datestamp(rule["effectiveTo"])
    ref["defeated"] = list(firing.defeated)
    return ref


def _datestamp(v) -> str:
    """Render a rule effective bound (date or datetime) as an RFC3339 UTC stamp."""
    from .engine import normalize_point

    return format_datetime(normalize_point(str(v)))


def _derivation_node(firing: Firing, result: EvalResult) -> dict:
    """Build a derivation node from a firing's binding provenance.

    Fact premises are listed sorted by fact id (matching the committed
    example receipt), followed by nested derivation nodes for `derived`
    bindings in `given` order.
    """
    fact_ids = sorted(p[1] for p in firing.premises if p[0] == "fact")
    premises: list[dict] = [{"factId": fid} for fid in fact_ids]
    for p in firing.premises:
        if p[0] == "derived":
            producer = result.firings[p[2]]
            premises.append(_derivation_node(producer, result))
    return {
        "conclusion": {
            "entity": firing.entity_id,
            "attribute": firing.attribute,
            "value": value_to_fact(firing.value),
        },
        "rule": firing.rule_id,
        "premises": premises,
    }


def _input_facts(derivation: dict, result: EvalResult) -> list[dict]:
    """Every fact cited in the derivation, id + contentHash, first-use order."""
    seen: list[str] = []

    def walk(node: dict) -> None:
        for p in node.get("premises", []):
            if "factId" in p:
                if p["factId"] not in seen:
                    seen.append(p["factId"])
            else:
                walk(p)

    walk(derivation)
    out = []
    for fid in seen:
        fact = result.fact_by_id[fid]
        out.append({"id": fact["id"], "contentHash": fact["contentHash"]})
    return out


def build_receipt(result: EvalResult, pack: dict, decision_attribute: str) -> dict:
    decision_firing = result.surviving_for(decision_attribute)
    if decision_firing is None:
        raise AdjudicationError(
            f"no surviving conclusion for decision attribute {decision_attribute!r}"
        )

    derivation = _derivation_node(decision_firing, result)
    receipt = {
        "caseId": result.case_id,
        "decision": {
            "entity": decision_firing.entity_id,
            "attribute": decision_firing.attribute,
            "value": value_to_fact(decision_firing.value),
        },
        "asOf": {
            "effective": format_datetime(result.effective),
            "knowledge": format_datetime(result.knowledge),
        },
        "rulePack": {
            "name": pack["pack"]["name"],
            "version": pack["pack"]["version"],
        },
        "rulesFired": [_rule_ref(f) for f in result.surviving],
        "derivation": derivation,
        "inputFacts": _input_facts(derivation, result),
        "abstentions": list(result.conflicts),
        "engine": {
            "kernel": "duly-kernel",
            "version": __version__,
            "backend": "reference",
        },
    }
    digest = content_hash(receipt, "receiptSha256")
    return {
        "id": f"urn:duly:receipt:sha256:{digest}",
        "receiptSha256": digest,
        **receipt,
    }
