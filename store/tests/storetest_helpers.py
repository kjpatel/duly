"""Shared helpers for the store tests.

Deliberately NOT a conftest.py: these test dirs have no __init__.py, so a
second module named `conftest` would shadow kernel/tests/conftest.py (whose
tests import from it by name) when the suites run together. A distinctive
module name sidesteps the sys.modules collision entirely.
"""

import copy
import json
from pathlib import Path

from duly_store.store import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_EXAMPLES = REPO_ROOT / "spec" / "examples"
NY_PACK = REPO_ROOT / "kernel" / "tests" / "fixtures" / "ny-pack.yaml"

CASE_ID = "case:policy:HO-77401-NY"


def load_spec_facts() -> list[dict]:
    """The GroundedFact examples from spec/examples (read in place)."""
    facts = []
    for path in sorted(SPEC_EXAMPLES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" not in doc:
            facts.append(doc)
    assert len(facts) == 4
    return facts


def load_expected_receipt() -> dict:
    return json.loads(
        (SPEC_EXAMPLES / "receipt-ny-nonrenewal-notice.json").read_text(encoding="utf-8")
    )


def rehash(fact: dict) -> dict:
    """Copy of `fact` with contentHash and id recomputed, so modified test
    facts stay self-consistent with the content-address rule (D8)."""
    fact = copy.deepcopy(fact)
    digest = content_hash(fact)
    fact["contentHash"] = digest
    fact["id"] = f"urn:duly:fact:sha256:{digest}"
    return fact


def correction(base: dict, *, value: dict, recorded_at: str, supersedes: str) -> dict:
    """A superseding correction of `base`: new value, new recordedAt,
    `supersedes` pointing at the corrected fact (D7)."""
    fact = copy.deepcopy(base)
    fact["value"] = value
    fact["recordedAt"] = recorded_at
    fact["assertion"]["at"] = recorded_at
    fact["supersedes"] = supersedes
    return rehash(fact)
