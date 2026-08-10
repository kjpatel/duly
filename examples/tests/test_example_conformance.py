"""Every committed fact conforms to the committed ontologies.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

This is the standing guarantee the gate adds to the *teaching* content:
starters, golden cases (all 351, including the preserved `review-*` series),
rule-pack fixtures and the spec's committed examples all resolve against
`examples/ontologies/` with no issue. A new fact-bearing artifact that steps
outside the vocabulary fails here, loudly, at test time — not as a rule
silently failing to bind.

The whole file moves, including the `spec/examples/*.json` leg, and that is
worth stating because the glob is the one thing here that lives outside
`examples/`. The facts in `spec/examples/` pin `duly-starter-notice` and
`duly-mortgage-closing` in their `schemaRef`s, and both of those ontologies are
teaching content under `examples/ontologies/` — so the sweep has no leg that
survives the deletion. What survives is `conformance/tests/`: the subset
parser, the gate's own rules, and the CLI's contract, all on synthetic schemas
and the toolkit corpus in [`fixtures/`](../../fixtures/README.md).
"""

import json

import pytest

from exampletest_helpers import EXAMPLES, GOLDEN_CASES, ONTOLOGIES, REPO_ROOT

from duly_conformance import check_fact, load_repo_registry

#: Repo-root-relative because one of the four is: the spec's worked examples
#: are not example content, but the vocabulary they cite is.
FACT_GLOBS = [
    "examples/starters/*/facts/*.json",
    "examples/golden/cases/*/facts/*.json",
    "examples/rulepacks/*/fixtures/*/facts/*.json",
    "spec/examples/*.json",
]


def _fact_paths():
    for pattern in FACT_GLOBS:
        yield from sorted(REPO_ROOT.glob(pattern))


@pytest.fixture(scope="module")
def registry():
    return load_repo_registry(ONTOLOGIES)


def test_corpus_is_nonempty():
    paths = list(_fact_paths())
    assert len(paths) > 1000  # 351 cases + starters + fixtures + examples


def test_every_committed_fact_conforms(registry):
    failures = []
    checked = 0
    for path in _fact_paths():
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" in doc or "factIds" in doc:
            continue  # spec/examples mixes receipts in with facts
        checked += 1
        for issue in check_fact(doc, registry):
            failures.append(f"{path.relative_to(REPO_ROOT)}: {issue}")
    assert not failures, "\n".join(failures)
    assert checked > 1000


def test_the_registry_holds_exactly_the_two_committed_ontologies(registry):
    """The teaching registry's shape, and the loader's exactness on it.

    From `conformance/tests/test_linkml_subset.py`, whose remaining tests are
    about the *parser* and now read the fixture registry. The names, the count
    and the five mortgage namespaces in one artifact are claims about what this
    repository ships — `duly-mortgage-closing` spans `trid`/`ron`/`pkg`/`resc`/
    `rec` because the M4 consolidation put them there, which is a fact about
    the example content and about nothing else.
    """
    assert registry.refs() == ["duly-mortgage-closing@0.1.0", "duly-starter-notice@0.1.0"]
    mortgage = registry.get("duly-mortgage-closing", "0.1.0")
    assert {c.split(":", 1)[0] for c in mortgage.classes} == {
        "trid", "ron", "pkg", "resc", "rec",
    }
    # Version pinning is exact.
    assert registry.get("duly-mortgage-closing", "0.2.0") is None


def test_review_case_still_cites_the_insurance_ontology(registry):
    # golden/cases/review-0001 is preserved forever (no seed regenerates
    # it); the consolidation deliberately kept the name its facts pin.
    paths = sorted((GOLDEN_CASES / "review-0001" / "facts").glob("*.json"))
    assert paths, f"no committed facts under {GOLDEN_CASES / 'review-0001'}"
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schemaRef"] == {"ontology": "duly-starter-notice", "version": "0.1.0"}
        assert check_fact(doc, registry) == []


def test_mortgage_cases_cite_the_consolidated_ontology(registry):
    seen = set()
    for prefix in ("trid", "ron", "esign", "resc", "rec"):
        for path in sorted(GOLDEN_CASES.glob(f"{prefix}-*/facts/*.json"))[:3]:
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc["schemaRef"] == {"ontology": "duly-mortgage-closing", "version": "0.1.0"}
            seen.add(prefix)
    assert seen == {"trid", "ron", "esign", "resc", "rec"}


def test_the_starters_are_part_of_the_sweep():
    """The globs above are four, and three of them are under `EXAMPLES`. A
    typo in any one would narrow the sweep without failing it — the corpus
    floor is 1000 facts and the golden cases alone clear that."""
    for pattern in FACT_GLOBS:
        assert sorted(REPO_ROOT.glob(pattern)), pattern
    assert EXAMPLES.is_dir()
