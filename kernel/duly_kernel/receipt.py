"""DecisionReceipt emission (duly_core schemas, `decision-receipt`).

Content addressing follows spec/validate.py: SHA-256 over the JCS-style
canonical JSON (sorted keys, minimal separators, UTF-8, ensure_ascii=False)
of the receipt excluding `id` and `receiptSha256`.
"""

from __future__ import annotations

from duly_core import canonical, content_hash  # noqa: F401

from .engine import AdjudicationError, EvalResult, Firing
from .expr import format_datetime, value_to_fact

# The value of `engine.version` in every emitted receipt, and therefore inside
# every receipt hash. It is the version of the kernel's **decision semantics**,
# not of the `duly_kernel` package and not of the `duly` distribution.
#
# Three scopes, nested one way only, and each needs its own number:
#
#   duly (distribution)      moves on any release of anything in the wheel
#   duly_kernel.__version__  moves when the kernel's *code* changes
#   SEMANTICS_VERSION        moves when the kernel's *meaning* changes
#
# A semantics change implies a code change implies a release. Never the
# reverse: a release can be a demo fix with the kernel byte-identical, and a
# kernel refactor can leave every decision exactly as it was.
#
# All three read `0.0.1` today. That agreement is a coincidence, and this
# constant is what keeps it a harmless one. It used to be
# `duly_kernel.__version__` — which made the golden corpus a hostage to the
# release cadence, since publishing under any new number would have
# invalidated all 351 receipts without a rule, a fact, or a decision having
# changed.
#
# When they do diverge, this value stays put for the same reason `NY-NR-45`
# keeps its name: it is sealed into artifacts that are not editable, so it is a
# handle, not a claim. What a package version is for has a correctable home in
# the wheel metadata; what this is for does not.
#
# Pinned by kernel/tests/test_engine_identity.py, which proves the decoupling
# behaviourally — while the two values agree, nothing else can see a re-coupling.
SEMANTICS_VERSION = "0.0.1"


# Re-exported, not reimplemented. `duly_core` owns the canonical form so that
# no two packages can disagree about what a document's bytes are; the kernel
# keeps the names because sealing a fact is the first thing an integration
# does and it should not have to learn a second package to do it.


def seal_fact(fact: dict) -> dict:
    """Return ``fact`` with its ``contentHash`` and content-derived ``id``.

    The first thing any integration has to do, and the last place it should
    be writing its own code: a fact's identity *is* its bytes, so a private
    variant of this produces facts nobody else can verify. Three lines that
    are easy to get subtly wrong — the canonical form excludes ``id`` and
    ``contentHash``, sorts keys, uses minimal separators, and does not escape
    non-ASCII — and every consumer everywhere recomputes them.

    Idempotent: sealing an already-sealed fact recomputes the same digest,
    because both fields are excluded from the body being hashed.

    >>> sealed = seal_fact({"caseId": "c1"})
    >>> sealed["id"] == f"urn:duly:fact:sha256:{sealed['contentHash']}"
    True
    """
    digest = content_hash(fact, "contentHash")
    body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **body}


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
        "abstentions": list(result.conflicts) + list(result.exclusions),
        "engine": {
            "kernel": "duly-kernel",
            "version": SEMANTICS_VERSION,
            "backend": "reference",
        },
    }
    digest = content_hash(receipt, "receiptSha256")
    return {
        "id": f"urn:duly:receipt:sha256:{digest}",
        "receiptSha256": digest,
        **receipt,
    }
