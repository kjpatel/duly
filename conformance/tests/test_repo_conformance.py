"""Every committed fact conforms to the committed ontologies.

This is the standing guarantee the gate adds to the repo: starters, golden
cases (all 351, including the preserved review-* series), rule-pack
fixtures, and spec examples all resolve against ontologies/ with no issue.
A new fact-bearing artifact that steps outside the vocabulary fails here,
loudly, at test time — not as a rule silently failing to bind.
"""

import json

import pytest
from conformancetest_helpers import ONTOLOGIES_DIR, REPO

from duly_conformance import check_fact, load_repo_registry

FACT_GLOBS = [
    "examples/starters/*/facts/*.json",
    "examples/golden/cases/*/facts/*.json",
    "examples/rulepacks/*/fixtures/*/facts/*.json",
    "spec/examples/*.json",
]


def _fact_paths():
    for pattern in FACT_GLOBS:
        yield from sorted(REPO.glob(pattern))


@pytest.fixture(scope="module")
def registry():
    return load_repo_registry(ONTOLOGIES_DIR)


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
            failures.append(f"{path.relative_to(REPO)}: {issue}")
    assert not failures, "\n".join(failures)
    assert checked > 1000


def test_review_case_still_cites_the_insurance_ontology(registry):
    # golden/cases/review-0001 is preserved forever (no seed regenerates
    # it); the consolidation deliberately kept the name its facts pin.
    for path in sorted((REPO / "examples/golden/cases/review-0001/facts").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schemaRef"] == {"ontology": "duly-starter-notice", "version": "0.1.0"}
        assert check_fact(doc, registry) == []


def test_mortgage_cases_cite_the_consolidated_ontology(registry):
    seen = set()
    for prefix in ("trid", "ron", "esign", "resc", "rec"):
        for path in sorted(REPO.glob(f"examples/golden/cases/{prefix}-*/facts/*.json"))[:3]:
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc["schemaRef"] == {"ontology": "duly-mortgage-closing", "version": "0.1.0"}
            seen.add(prefix)
    assert seen == {"trid", "ron", "esign", "resc", "rec"}
