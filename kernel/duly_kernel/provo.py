"""PROV-O JSON-LD export for stored duly documents.

Wraps a stored GroundedFact, DecisionReceipt, or ExtractionRunEnvelope so it
is valid JSON-LD 1.1 that expands to PROV-O triples under the versioned
contexts in spec/contexts/. Lives next to report.py deliberately: both are
deterministic renderers of stored artifacts into a consumer-facing format,
and neither adds a runtime dependency (the context is referenced by URL; the
JSON-LD processor is the consumer's).

CRITICAL PROPERTY — stored documents never change. Facts, receipts, and
envelopes are content-addressed (spec D8); adding an ``@context`` key into a
stored document would change every hash and break replay. ``as_jsonld``
therefore returns a NEW dict and never mutates its input. Consumers who
cannot call this wrapper can instead apply the same context out-of-band
(JSON-LD 1.1 ``expandContext``) to the raw stored document and get the same
entity-level triples; the wrapper additionally materializes the derived
PROV nodes listed below, which a bare context cannot mint.

Derived nodes (all ids computed deterministically from the document):

- fact (machine-asserted): ``prov:wasAttributedTo`` a ``prov:SoftwareAgent``
  ``urn:duly:agent:<extractor.name>:<extractor.version>``. Human-asserted
  facts need nothing extra — the actor id is already an IRI and the context
  maps it to ``prov:wasAttributedTo``.
- receipt: the adjudication ``prov:Activity``
  ``urn:duly:adjudication:sha256:<receiptSha256>``, which ``prov:used`` every
  input fact and carries a ``prov:qualifiedAssociation`` binding the engine
  agent to the rule pack as its ``prov:Plan``
  (``urn:duly:rulepack:<name>:<version>``).
- envelope: types the run id (already in the document) as the generating
  ``prov:Activity``, ``prov:wasAssociatedWith`` the adapter agent.

Determinism: pure construction from the input document — no wall clock, no
randomness, no dict-order dependence (output key order is fixed:
``@context``, ``@id``, ``@type``, the stored fields in stored order, then
the derived ``prov:*`` keys).
"""

from __future__ import annotations

import copy
from urllib.parse import quote

CONTEXT_BASE = "https://duly.dev/spec/v0/contexts/"

CONTEXT_URL = {
    "fact": CONTEXT_BASE + "grounded-fact.context.jsonld",
    "receipt": CONTEXT_BASE + "decision-receipt.context.jsonld",
    "envelope": CONTEXT_BASE + "extraction-run.context.jsonld",
}

_TYPES = {
    "fact": ("prov:Entity", "duly:GroundedFact"),
    "receipt": ("prov:Entity", "duly:DecisionReceipt"),
    "envelope": ("prov:Entity", "prov:Collection", "duly:ExtractionRunEnvelope"),
}


def _agent_urn(name: str, version: str) -> str:
    """Deterministic IRI for a software agent identified by name + version."""
    return f"urn:duly:agent:{quote(name, safe='')}:{quote(version, safe='')}"


def _software_agent(name: str, version: str) -> dict:
    return {
        "@id": _agent_urn(name, version),
        "@type": "prov:SoftwareAgent",
        "duly:name": name,
        "duly:version": version,
    }


def _derived_fact(doc: dict) -> dict:
    assertion = doc.get("assertion", {})
    if assertion.get("kind") != "machine":
        return {}
    extractor = assertion["extractor"]
    return {
        "prov:wasAttributedTo": _software_agent(extractor["name"], extractor["version"])
    }


def _derived_receipt(doc: dict) -> dict:
    pack = doc["rulePack"]
    engine = doc["engine"]
    activity = {
        "@id": f"urn:duly:adjudication:sha256:{doc['receiptSha256']}",
        "@type": "prov:Activity",
        "prov:used": [{"@id": f["id"]} for f in doc["inputFacts"]],
        "prov:wasAssociatedWith": {"@id": _agent_urn(engine["kernel"], engine["version"])},
        "prov:qualifiedAssociation": {
            "@type": "prov:Association",
            "prov:agent": _software_agent(engine["kernel"], engine["version"]),
            "prov:hadPlan": {
                "@id": "urn:duly:rulepack:"
                f"{quote(pack['name'], safe='')}:{quote(pack['version'], safe='')}",
                "@type": "prov:Plan",
                "duly:name": pack["name"],
                "duly:version": pack["version"],
            },
        },
    }
    return {"prov:wasGeneratedBy": activity}


def _derived_envelope(doc: dict) -> dict:
    adapter = doc["adapter"]
    return {
        "prov:wasGeneratedBy": {
            "@id": doc["runId"],
            "@type": "prov:Activity",
            "prov:wasAssociatedWith": _software_agent(adapter["name"], adapter["version"]),
        }
    }


_DERIVED = {
    "fact": _derived_fact,
    "receipt": _derived_receipt,
    "envelope": _derived_envelope,
}


def as_jsonld(doc: dict, kind: str) -> dict:
    """Wrap a stored document as JSON-LD without mutating the input.

    ``kind`` is one of ``"fact"``, ``"receipt"``, ``"envelope"``. The stored
    ``id`` field is carried as ``@id`` (the context aliases ``id`` to ``@id``,
    so keeping both keys would collide); every other stored field is copied
    unchanged, in stored order, followed by the derived ``prov:*`` nodes.
    """
    if kind not in CONTEXT_URL:
        raise ValueError(f"unknown kind {kind!r}: expected one of {sorted(CONTEXT_URL)}")
    out: dict = {
        "@context": CONTEXT_URL[kind],
        "@id": doc["id"],
        "@type": list(_TYPES[kind]),
    }
    body = copy.deepcopy(doc)
    body.pop("id", None)
    out.update(body)
    out.update(_DERIVED[kind](doc))
    return out
