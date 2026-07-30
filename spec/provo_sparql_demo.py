#!/usr/bin/env python3
"""The auditor's questions, answered with off-the-shelf RDF tooling.

Demonstrates what the PROV-O contexts (spec/prov-o.md) buy: duly's stored
JSON — unchanged bytes — becomes a provenance graph any SPARQL engine can
query. This script adjudicates the two span-grounded starters live, adds
the committed human-correction case (golden/cases/review-0001), exports
everything through ``duly_kernel.provo.as_jsonld``, expands with the
repo's own context files (offline — network fetches are refused), and
runs three queries an auditor would actually ask.

Run from the repo root:

    uv run --with rdflib python spec/provo_sparql_demo.py

``rdflib`` is deliberately NOT a project dependency — it stands in for
"whatever RDF tooling your organization already runs", which is the
point. ``pyld`` comes from the dev dependency group.

A note on grounding: the synthetic golden corpus is attestation-grounded
(those cases have no documents), so document-lineage queries only return
rows for span-grounded facts — the starters here, or any real deployment.
Query silence over attestation facts is correct behavior, not a bug.
"""
from __future__ import annotations

import json
import pathlib

import yaml
from pyld import jsonld
from rdflib import Graph

from duly_kernel.api import adjudicate
from duly_kernel.provo import CONTEXT_URL, as_jsonld

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Offline loader: the published context URLs resolve to spec/contexts/;
# anything else is refused so this demo can never depend on the network.
_LOCAL = {
    url: ROOT / "spec" / "contexts" / url.rsplit("/", 1)[-1]
    for url in CONTEXT_URL.values()
}


def _loader(url: str, options=None):
    if url in _LOCAL:
        return {
            "contentType": "application/ld+json",
            "contextUrl": None,
            "documentUrl": url,
            "document": json.loads(_LOCAL[url].read_text(encoding="utf-8")),
        }
    raise RuntimeError(f"network fetch refused: {url}")


jsonld.set_document_loader(_loader)


def main() -> int:
    graph = Graph()

    def add(doc: dict, kind: str) -> None:
        nquads = jsonld.to_rdf(as_jsonld(doc, kind), {"format": "application/n-quads"})
        graph.parse(data=nquads, format="nquads")

    # Two live adjudications over span-grounded starter facts.
    for facts_dir, pack_path, question in [
        ("starters/notice-ny/facts", "rulepacks/termination-notice-us-states/pack.yaml", "nc:noticeCompliant"),
        ("starters/trid/facts", "rulepacks/trid-fee-tolerance-us-federal/pack.yaml", "trid:toleranceCureAmount"),
    ]:
        facts = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / facts_dir).glob("*.json"))]
        pack = yaml.safe_load((ROOT / pack_path).read_text(encoding="utf-8"))
        receipt = adjudicate(facts, pack, "2026-07-29T00:00:00Z", "2026-07-29T23:59:59Z", question)
        add(receipt, "receipt")
        for fact in facts:
            add(fact, "fact")

    # Plus the committed human-correction case.
    add(json.loads((ROOT / "golden/receipts/review-0001.json").read_text(encoding="utf-8")), "receipt")
    for path in sorted((ROOT / "golden/cases/review-0001/facts").glob("*.json")):
        add(json.loads(path.read_text(encoding="utf-8")), "fact")

    print(f"graph: {len(graph)} triples (2 live adjudications + 1 committed correction case)\n")

    print("Q1 — which decisions used a fact grounded in THIS document?")
    print("     (target: doc:dec-page:HO-77401-NY:2025-09-01)")
    q1 = """
    PREFIX prov: <http://www.w3.org/ns/prov#>
    SELECT DISTINCT ?receipt WHERE {
      ?activity prov:used ?fact . ?receipt prov:wasGeneratedBy ?activity .
      ?fact prov:wasDerivedFrom <doc:dec-page:HO-77401-NY:2025-09-01> .
    }"""
    for row in graph.query(q1):
        print(f"     {row.receipt}")

    print("\nQ2 — which decisions relied on a human-asserted fact, and what did it supersede?")
    q2 = """
    PREFIX prov: <http://www.w3.org/ns/prov#>
    SELECT ?receipt ?agent ?superseded WHERE {
      ?activity prov:used ?fact . ?receipt prov:wasGeneratedBy ?activity .
      ?fact prov:wasAttributedTo ?agent . FILTER(CONTAINS(STR(?agent), "reviewer:"))
      OPTIONAL { ?fact prov:wasRevisionOf ?superseded }
    }"""
    for row in graph.query(q2):
        print(f"     {row.receipt}")
        print(f"       human: {row.agent}")
        print(f"       supersedes machine fact: {row.superseded}")

    print("\nQ3 — under which rule-pack version was each decision made?")
    q3 = """
    PREFIX prov: <http://www.w3.org/ns/prov#>
    SELECT ?receipt ?plan WHERE {
      ?receipt prov:wasGeneratedBy ?a .
      ?a prov:qualifiedAssociation ?qa . ?qa prov:hadPlan ?plan .
    } ORDER BY ?plan"""
    for row in graph.query(q3):
        print(f"     {row.plan}\n       decided: {row.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
