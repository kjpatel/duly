import copy
import json
from pathlib import Path

import pytest

from duly_kernel.ir import load_pack
from duly_kernel.receipt import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_EXAMPLES = REPO_ROOT / "spec" / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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
