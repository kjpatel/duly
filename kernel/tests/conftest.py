import copy
import json
from pathlib import Path

import pytest

from duly_kernel.ir import load_pack
from duly_kernel.receipt import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_EXAMPLES = REPO_ROOT / "spec" / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The toolkit-owned corpus (fixtures/README.md). Kernel behaviour is asserted
# against this rather than against `golden/`, because `golden/` is example
# content that M5 relocates under `examples/` — and a test whose subject can be
# deleted without the test failing is not testing anything.
FIXTURE_CORPUS = REPO_ROOT / "fixtures"


def fixture_pack() -> dict:
    return load_pack(FIXTURE_CORPUS / "pack.yaml")


def fixture_case(case_id: str) -> tuple[list[dict], dict, dict]:
    """(facts, case, receipt) for one fixture case."""
    import yaml

    case_dir = FIXTURE_CORPUS / "cases" / case_id
    facts = [
        json.loads(p.read_text()) for p in sorted((case_dir / "facts").glob("*.json"))
    ]
    case = yaml.safe_load((case_dir / "case.yaml").read_text())
    receipt = json.loads((FIXTURE_CORPUS / "receipts" / f"{case_id}.json").read_text())
    return facts, case, receipt


def fixture_receipts() -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in sorted((FIXTURE_CORPUS / "receipts").glob("*.json"))
    ]


@pytest.fixture()
def spec_facts() -> list[dict]:
    """The four GroundedFact examples from spec/examples (read in place)."""
    facts = []
    for path in sorted(SPEC_EXAMPLES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" not in doc:
            facts.append(doc)
    assert len(facts) == 4
    return facts


@pytest.fixture()
def expected_receipt() -> dict:
    return json.loads(
        (SPEC_EXAMPLES / "receipt-ny-nonrenewal-notice.json").read_text(encoding="utf-8")
    )


@pytest.fixture()
def ny_pack() -> dict:
    return load_pack(FIXTURES / "ny-pack.yaml")


def rehash_fact(fact: dict) -> dict:
    """Return a copy of `fact` with contentHash and id recomputed, so
    modified test facts stay self-consistent with the content-address rule."""
    fact = copy.deepcopy(fact)
    digest = content_hash(fact, "contentHash")
    fact["contentHash"] = digest
    fact["id"] = f"urn:duly:fact:sha256:{digest}"
    return fact
