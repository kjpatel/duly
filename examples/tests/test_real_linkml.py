"""PROOF the committed ontologies are genuine LinkML — with real tooling.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as

    uv run --with linkml --with pyshacl pytest examples/tests -q -m linkml

Their subject is the two committed ontologies under `examples/ontologies/` and
a committed starter fact projected into RDF — all teaching content. What the
*conformance gate* enforces is asserted in `conformance/tests/` and stays
there; this file proves that what the gate's pure-Python subset accepts is
also what real LinkML tooling reads.

Marker-gated like the docling tests: the runtime gate (duly_conformance)
is deliberately pure Python, so linkml/pyshacl are not project
dependencies. Run these explicitly:

    uv run --with linkml --with pyshacl pytest examples/tests -m linkml

Two legs:

- linkml-runtime loads both schemas, resolves every class/slot/enum the
  subset validator enforces, and expands the CURIEs.
- LinkML's SHACL generator compiles the mortgage schema to shapes, and
  pyshacl validates instance data against them: an RDF projection of a
  committed fact conforms, an out-of-enum mutation is rejected, and the
  PROV-O JSON-LD export coexists with the shapes (fact attributes stay
  duly: literals — grounded-facts D10 keeps term resolution out of PROV —
  so the shapes' class targets don't fire on the export graph; the
  projection is what exercises them).
"""

import importlib.util
import json

import pytest

from exampletest_helpers import EXAMPLES, ONTOLOGIES, REPO_ROOT

MORTGAGE = ONTOLOGIES / "duly-mortgage-closing" / "0.1.0.yaml"
NOTICE = ONTOLOGIES / "duly-starter-notice" / "0.1.0.yaml"

pytestmark = [
    pytest.mark.linkml,
    pytest.mark.skipif(
        importlib.util.find_spec("linkml_runtime") is None,
        reason="linkml tooling not installed (uv run --with linkml --with pyshacl)",
    ),
]


def _schema_view(path):
    from linkml_runtime import SchemaView

    return SchemaView(str(path))


def test_notice_schema_loads_under_linkml_runtime():
    view = _schema_view(NOTICE)
    assert view.schema.name == "duly-starter-notice"
    assert view.schema.version == "0.1.0"
    cls = view.get_class("TerminationNotice")
    assert cls.class_uri == "nc:TerminationNotice"
    attrs = view.class_induced_slots("TerminationNotice")
    by_name = {s.name: s for s in attrs}
    assert by_name["noticeMailedDate"].range == "date"
    assert view.get_enum("NoticeType").permissible_values.keys() == {"Nonrenewal"}


def test_mortgage_schema_loads_under_linkml_runtime():
    view = _schema_view(MORTGAGE)
    assert view.schema.name == "duly-mortgage-closing"
    for class_name, curie in [
        ("Fee", "trid:Fee"),
        ("Notarization", "ron:Notarization"),
        ("Closing", "ron:Closing"),
        ("SigningTask", "pkg:SigningTask"),
        ("Loan", "resc:Loan"),
        ("RecordingSubmission", "rec:RecordingSubmission"),
    ]:
        cls = view.get_class(class_name)
        assert cls is not None and cls.class_uri == curie
    slots = {s.name: s for s in view.class_induced_slots("Fee")}
    assert slots["disclosedAmountAtBaseline"].range == "Money"
    assert view.get_type("Money").uri == "duly:money"
    # CURIEs expand under the declared prefixes.
    assert str(view.namespaces().uri_for("trid:Fee")) == (
        "https://duly.dev/ontologies/duly-mortgage-closing/trid#Fee"
    )
    # The FIBO crosswalk mappings are real CURIEs under declared prefixes.
    loan = view.get_class("Loan")
    expanded = [str(view.namespaces().uri_for(m)) for m in loan.close_mappings]
    assert "https://spec.edmcouncil.org/fibo/ontology/LOAN/LoansGeneral/Loans/Loan" in expanded


@pytest.fixture(scope="module")
def mortgage_shapes():
    if importlib.util.find_spec("linkml") is None or importlib.util.find_spec("pyshacl") is None:
        pytest.skip("SHACL leg needs linkml generators + pyshacl")
    from linkml.generators.shaclgen import ShaclGenerator
    from rdflib import Graph

    shapes = Graph()
    shapes.parse(data=ShaclGenerator(str(MORTGAGE)).serialize(), format="turtle")
    assert len(shapes) > 0
    return shapes


def _projection_graph(fact: dict):
    """A minimal RDF projection of a fact — entity node typed with the
    ontology class, attribute as predicate, value as literal — i.e. the
    instance shape LinkML-generated SHACL targets."""
    from linkml_runtime import SchemaView
    from rdflib import Graph, Literal, RDF, URIRef

    view = _schema_view(MORTGAGE)
    ns = view.namespaces()
    graph = Graph()
    entity = URIRef("urn:example:" + fact["entity"]["id"])
    graph.add((entity, RDF.type, URIRef(ns.uri_for(fact["entity"]["type"]))))
    predicate = URIRef(ns.uri_for(fact["attribute"]))
    value = fact["value"]
    literal = Literal(value.get("value", value.get("amount")))
    graph.add((entity, predicate, literal))
    return graph


def _committed_fee_type_fact() -> dict:
    return json.loads(
        (EXAMPLES / "starters/trid/facts/fact-cd-fee-type.json").read_text(encoding="utf-8")
    )


def test_shacl_accepts_a_committed_fact_projection(mortgage_shapes):
    import pyshacl

    conforms, _, report = pyshacl.validate(
        _projection_graph(_committed_fee_type_fact()), shacl_graph=mortgage_shapes
    )
    assert conforms, report


def test_shacl_rejects_an_out_of_enum_code(mortgage_shapes):
    import pyshacl

    fact = _committed_fee_type_fact()
    fact["value"]["value"] = "Chartreuse"  # not a FeeType permissible value
    conforms, _, report = pyshacl.validate(
        _projection_graph(fact), shacl_graph=mortgage_shapes
    )
    assert not conforms
    assert "Chartreuse" in report


def test_shacl_coexists_with_the_provo_export(mortgage_shapes):
    """The PROV-O JSON-LD export of the same fact parses to RDF and
    validates against the generated shapes. Conformance here is expected
    and unexciting — the export deliberately keeps attribute CURIEs as
    duly: literals (prov-o.md P8), so no shape target fires; the
    projection tests above are the ones that exercise the shapes. This
    test pins that the two standards artifacts do not conflict."""
    import pyshacl
    from pyld import jsonld
    from rdflib import Graph

    from duly_kernel.provo import CONTEXT_URL, as_jsonld

    local = {
        url: REPO_ROOT / "spec" / "contexts" / url.rsplit("/", 1)[-1]
        for url in CONTEXT_URL.values()
    }

    def loader(url, options=None):
        if url in local:
            return {
                "contentType": "application/ld+json",
                "contextUrl": None,
                "documentUrl": url,
                "document": json.loads(local[url].read_text(encoding="utf-8")),
            }
        raise RuntimeError(f"network fetch refused: {url}")

    jsonld.set_document_loader(loader)
    nquads = jsonld.to_rdf(
        as_jsonld(_committed_fee_type_fact(), "fact"), {"format": "application/n-quads"}
    )
    export_graph = Graph()
    export_graph.parse(data=nquads, format="nquads")
    assert len(export_graph) > 0
    conforms, _, report = pyshacl.validate(export_graph, shacl_graph=mortgage_shapes)
    assert conforms, report
