"""PROV-O JSON-LD context and exporter tests (kernel/duly_kernel/provo.py, spec/contexts/).

Processor choice: pyld (dev dependency group only, like pytest/jsonschema —
never a runtime dependency). pyld is Digital Bazaar's pure-Python JSON-LD
processor with full JSON-LD 1.1 support, which these contexts need for
``@nest`` terms with property-scoped contexts and ``@json`` literals; rdflib
was the alternative but its JSON-LD 1.1 coverage of exactly those features is
weaker, and a hand-rolled expander would prove nothing about hand-written
contexts. No network at test time: contexts are resolved through a local
document loader that maps the published context URLs to spec/contexts/ files
and raises on anything else.

Two consumption paths are exercised, matching spec/prov-o.md:

- out-of-band: the raw stored document (no ``@context`` key — stored bytes
  are content-addressed and must never change) expanded with the context
  supplied externally via ``expandContext``;
- exporter: ``as_jsonld`` wraps the document (``@context`` URL, ``@id``,
  ``@type``, derived activity/agent nodes) and the result is expanded through
  the offline document loader.
"""

import copy
import json

import pytest
from pyld import jsonld

from duly_kernel.provo import CONTEXT_URL, as_jsonld

from conftest import REPO_ROOT

CONTEXTS_DIR = REPO_ROOT / "spec" / "contexts"
PROV = "http://www.w3.org/ns/prov#"
DULY = "https://duly.dev/spec/v0/vocab#"

_LOCAL = {
    CONTEXT_URL["fact"]: CONTEXTS_DIR / "grounded-fact.context.jsonld",
    CONTEXT_URL["receipt"]: CONTEXTS_DIR / "decision-receipt.context.jsonld",
    CONTEXT_URL["envelope"]: CONTEXTS_DIR / "extraction-run.context.jsonld",
}


def _offline_loader(url, options=None):
    if url not in _LOCAL:
        raise AssertionError(f"network fetch attempted at test time: {url}")
    return {
        "contentType": "application/ld+json",
        "contextUrl": None,
        "documentUrl": url,
        "document": json.loads(_LOCAL[url].read_text(encoding="utf-8")),
    }


def _context(kind: str) -> dict:
    return json.loads(_LOCAL[CONTEXT_URL[kind]].read_text(encoding="utf-8"))["@context"]


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _expand_stored(doc: dict, kind: str) -> dict:
    """Out-of-band path: context supplied externally, document untouched."""
    expanded = jsonld.expand(doc, {"expandContext": _context(kind)})
    assert len(expanded) == 1
    return expanded[0]


def _expand_exported(doc: dict, kind: str) -> list:
    """Exporter path, flattened so every node (activity, agents) is addressable."""
    return jsonld.flatten(as_jsonld(doc, kind), None, {"documentLoader": _offline_loader})


def _ids(node, prop):
    return {v["@id"] for v in node.get(prop, [])}


def _values(node, prop):
    return [v.get("@value") for v in node.get(prop, [])]


# ---------------------------------------------------------------------------
# Context files themselves
# ---------------------------------------------------------------------------


def test_contexts_parse_and_declare_1_1():
    for url, path in _LOCAL.items():
        doc = json.loads(path.read_text(encoding="utf-8"))
        ctx = doc["@context"]
        assert ctx["@version"] == 1.1, path.name
        assert ctx["prov"] == PROV, path.name
        assert ctx["duly"] == DULY, path.name
        assert ctx["id"] == "@id", path.name


# ---------------------------------------------------------------------------
# GroundedFact — document grounding (machine assertion)
# ---------------------------------------------------------------------------


@pytest.fixture()
def machine_fact():
    return _load(REPO_ROOT / "spec" / "examples" / "fact-decpage-expiration.json")


def test_machine_fact_prov_triples(machine_fact):
    node = _expand_stored(machine_fact, "fact")
    assert node["@id"] == machine_fact["id"]
    # quote/span grounding: the fact wasQuotedFrom the rendition entity
    (rendition,) = node[PROV + "wasQuotedFrom"]
    assert rendition["@id"] == "rend:docling:2.15.0:5c1e8a7b"
    assert _values(rendition, DULY + "extractorName") == ["docling"]
    # ...and wasDerivedFrom the source document
    assert _ids(node, PROV + "wasDerivedFrom") == {"doc:dec-page:HO-77401-NY:2025-09-01"}
    # the extraction run is the generating activity (lifted from assertion.extractor.runId)
    assert _ids(node, PROV + "wasGeneratedBy") == {"run:2026-07-28:003"}
    # knowledge time: store recording is the record's generation event
    (gen,) = node[PROV + "generatedAtTime"]
    assert gen == {
        "@type": "http://www.w3.org/2001/XMLSchema#dateTime",
        "@value": "2026-07-28T14:05:41Z",
    }


def test_machine_fact_duly_terms_survive_losslessly(machine_fact):
    node = _expand_stored(machine_fact, "fact")
    # typed value and span are @json literals, byte-preserved
    (value,) = node[DULY + "value"]
    assert value == {"@type": "@json", "@value": {"kind": "date", "value": "2026-09-01"}}
    (span,) = node[DULY + "charSpan"]
    assert span["@value"] == {"start": 842, "end": 878}
    assert _values(node, DULY + "assertionKind") == ["machine"]
    assert _values(node, DULY + "groundingKind") == ["document"]
    assert _values(node, DULY + "contentHash") == [machine_fact["contentHash"]]
    # effective time stays in the duly namespace (bitemporal; no PROV equivalent)
    assert (DULY + "effectiveFrom") in node


def test_machine_fact_export_attributes_software_agent(machine_fact):
    nodes = _expand_exported(machine_fact, "fact")
    fact = next(n for n in nodes if n["@id"] == machine_fact["id"])
    assert (PROV + "Entity") in fact["@type"]
    assert _ids(fact, PROV + "wasAttributedTo") == {"urn:duly:agent:duly-docling-adapter:0.1.0"}
    agent = next(n for n in nodes if n["@id"] == "urn:duly:agent:duly-docling-adapter:0.1.0")
    assert agent["@type"] == [PROV + "SoftwareAgent"]
    assert _values(agent, DULY + "name") == ["duly-docling-adapter"]


# ---------------------------------------------------------------------------
# GroundedFact — human assertion, attestation grounding, supersession
# ---------------------------------------------------------------------------


@pytest.fixture()
def human_fact():
    return _load(
        REPO_ROOT / "fixtures" / "cases" / "fx-0004" / "facts" / "fx-score-corrected.json"
    )


def test_human_fact_attribution_and_revision_direction(human_fact):
    node = _expand_stored(human_fact, "fact")
    # the asserting human is an identified agent
    assert _ids(node, PROV + "wasAttributedTo") == {"reviewer:fx-demo"}
    actor = next(
        n for n in node[PROV + "wasAttributedTo"] if (DULY + "role") in n
    )
    assert _values(actor, DULY + "role") == ["fixture-review"]
    # supersedes → wasRevisionOf: subject is the correcting (newer) fact,
    # object the corrected (older) one — same direction as the stored field
    assert _ids(node, PROV + "wasRevisionOf") == {human_fact["supersedes"]}
    assert _values(node, DULY + "assertionKind") == ["human"]
    assert _values(node, DULY + "groundingKind") == ["attestation"]
    assert _values(node, DULY + "channel") == ["fixture-review"]


def test_human_fact_export_adds_no_synthetic_agent(human_fact):
    nodes = _expand_exported(human_fact, "fact")
    fact = next(n for n in nodes if n["@id"] == human_fact["id"])
    assert _ids(fact, PROV + "wasAttributedTo") == {"reviewer:fx-demo"}


# ---------------------------------------------------------------------------
# DecisionReceipt — fixtures/receipts/fx-0001.json (nested derivation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def receipt_ny():
    return _load(REPO_ROOT / "fixtures" / "receipts" / "fx-0001.json")


def test_receipt_activity_used_the_input_facts(receipt_ny):
    nodes = _expand_exported(receipt_ny, "receipt")
    receipt = next(n for n in nodes if n["@id"] == receipt_ny["id"])
    input_ids = {f["id"] for f in receipt_ny["inputFacts"]}

    activity_id = "urn:duly:adjudication:sha256:" + receipt_ny["receiptSha256"]
    assert _ids(receipt, PROV + "wasGeneratedBy") == {activity_id}
    (activity,) = [n for n in nodes if n.get("@id") == activity_id]
    assert activity["@type"] == [PROV + "Activity"]
    assert _ids(activity, PROV + "used") == input_ids
    # entity-level derivation, available on the out-of-band path too
    assert _ids(receipt, PROV + "wasDerivedFrom") == input_ids
    # the rule pack is the activity's Plan, bound through the qualified association
    (assoc_ref,) = activity[PROV + "qualifiedAssociation"]
    assoc = next(n for n in nodes if n["@id"] == assoc_ref["@id"])
    assert assoc["@type"] == [PROV + "Association"]
    pack = receipt_ny["rulePack"]
    assert _ids(assoc, PROV + "hadPlan") == {
        f'urn:duly:rulepack:{pack["name"]}:{pack["version"]}'
    }
    plan = next(
        n for n in nodes
        if n["@id"] == f'urn:duly:rulepack:{pack["name"]}:{pack["version"]}'
    )
    assert plan["@type"] == [PROV + "Plan"]
    assert _values(plan, DULY + "version") == [pack["version"]]
    assert _ids(assoc, PROV + "agent") == {"urn:duly:agent:duly-kernel:0.0.1"}
    assert _ids(activity, PROV + "wasAssociatedWith") == {"urn:duly:agent:duly-kernel:0.0.1"}


def test_receipt_out_of_band_expansion_needs_no_exporter(receipt_ny):
    node = _expand_stored(receipt_ny, "receipt")
    assert _ids(node, PROV + "wasDerivedFrom") == {f["id"] for f in receipt_ny["inputFacts"]}
    assert _ids(node, DULY + "caseId") == {"case:fixture:fx-0001"}
    # the derivation tree rides along losslessly as a JSON literal
    (derivation,) = node[DULY + "derivation"]
    assert derivation["@type"] == "@json"
    assert derivation["@value"] == receipt_ny["derivation"]


# ---------------------------------------------------------------------------
# DecisionReceipt — fixtures/receipts/fx-0003.json (low_confidence abstention)
# ---------------------------------------------------------------------------


def test_receipt_abstention_links_considered_fact():
    receipt = _load(REPO_ROOT / "fixtures" / "receipts" / "fx-0003.json")
    node = _expand_stored(receipt, "receipt")
    (abstention,) = node[DULY + "abstention"]
    assert _values(abstention, DULY + "reason") == ["low_confidence"]
    # Pinned to the fixture corpus: fx-0003's below-floor score fact, which
    # fx-0004's correction supersedes.
    assert _ids(abstention, DULY + "consideredFact") == {
        "urn:duly:fact:sha256:2cb587ebabe1d96ea739636015d0ca13cfc8cd1535fb2466ccca4ac8cdcab4b9"
    }
    (threshold,) = abstention[DULY + "threshold"]
    assert _values(threshold, DULY + "minConfidence") == [0.8]


# ---------------------------------------------------------------------------
# ExtractionRunEnvelope — spec/examples/envelopes/envelope-decpage-run.json
# ---------------------------------------------------------------------------


@pytest.fixture()
def envelope():
    return _load(
        REPO_ROOT / "spec" / "examples" / "envelopes" / "envelope-decpage-run.json"
    )


def test_envelope_membership_and_run_join(envelope, machine_fact):
    node = _expand_stored(envelope, "envelope")
    assert _ids(node, PROV + "hadMember") == set(envelope["factIds"])
    # the same activity IRI the member facts carry as prov:wasGeneratedBy
    assert _ids(node, PROV + "wasGeneratedBy") == {"run:2026-07-28:003"}
    fact_node = _expand_stored(machine_fact, "fact")
    assert _ids(fact_node, PROV + "wasGeneratedBy") == _ids(node, PROV + "wasGeneratedBy")


def test_envelope_export_types_activity_and_adapter_agent(envelope):
    nodes = _expand_exported(envelope, "envelope")
    env = next(n for n in nodes if n["@id"] == envelope["id"])
    assert (PROV + "Collection") in env["@type"]
    (activity,) = [n for n in nodes if n.get("@id") == envelope["runId"]]
    assert activity["@type"] == [PROV + "Activity"]
    (agent,) = activity[PROV + "wasAssociatedWith"]
    assert agent["@id"] == "urn:duly:agent:duly-docling-adapter:0.1.0"


# ---------------------------------------------------------------------------
# Round-trip sanity: the exporter never mutates, output is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relpath,kind",
    [
        ("spec/examples/fact-decpage-expiration.json", "fact"),
        ("fixtures/cases/fx-0004/facts/fx-score-corrected.json", "fact"),
        ("fixtures/receipts/fx-0001.json", "receipt"),
        ("fixtures/receipts/fx-0003.json", "receipt"),
        ("spec/examples/envelopes/envelope-decpage-run.json", "envelope"),
    ],
)
def test_export_never_mutates_and_is_deterministic(relpath, kind):
    path = REPO_ROOT / relpath
    before_bytes = path.read_bytes()
    doc = json.loads(before_bytes.decode("utf-8"))
    snapshot = copy.deepcopy(doc)

    first = as_jsonld(doc, kind)
    second = as_jsonld(doc, kind)

    assert doc == snapshot, "as_jsonld mutated its input"
    assert path.read_bytes() == before_bytes, "stored document changed on disk"
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)
    # the wrapper embeds a context *reference*, never an inline context
    assert first["@context"] == CONTEXT_URL[kind]
    assert first["@id"] == doc["id"]
    # every stored field except 'id' (carried as @id) survives byte-for-byte
    for key, value in doc.items():
        if key != "id":
            assert first[key] == value


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        as_jsonld({"id": "urn:duly:fact:sha256:" + "0" * 64}, "rulepack")
