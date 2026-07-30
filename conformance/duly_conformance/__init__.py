"""Ontology conformance gate (spec/ontology-conformance.md).

The enforcement half of bring-your-own-ontology (grounded-facts D10): a
fact's ``schemaRef`` names an ontology + version; this package resolves
that reference against a registry of committed LinkML artifacts and checks
the fact's entity type, attribute, value kind, and code values against
what the ontology declares. A misspelled attribute or wrong value kind
becomes a loud, attributable rejection at the contract line instead of a
rule that silently fails to bind.

Deliberately pure Python (stdlib + yaml): the sample ontologies are
genuine LinkML — proven by marker-gated tests running real LinkML tooling
— but the enforcing validator interprets only the constrained subset duly
consumes, documented in spec/ontology-conformance.md, so the runtime gains
no rdflib/linkml dependency.
"""

from .gate import ConformanceIssue, FactNonconformantError, assert_conformant, check_fact
from .linkml_subset import Ontology, OntologySubsetError, parse_ontology
from .registry import OntologyRegistry, load_repo_registry

__all__ = [
    "ConformanceIssue",
    "FactNonconformantError",
    "assert_conformant",
    "check_fact",
    "Ontology",
    "OntologySubsetError",
    "parse_ontology",
    "OntologyRegistry",
    "load_repo_registry",
]
