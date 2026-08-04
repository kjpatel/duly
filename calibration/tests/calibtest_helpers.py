"""Shared helpers for the calibration tests.

Deliberately NOT a conftest.py, for the same reason as
store/tests/storetest_helpers.py: these test dirs have no __init__.py, so a
second module named `conftest` would collide with kernel/tests/conftest.py
in sys.modules when the suites run together.

Synthetic data with KNOWN miscalibration
----------------------------------------
`overconfident_pairs` draws a true correctness probability p for each
example, a Bernoulli(p) label, and reports the *inflated* score
sigmoid(inflate * logit(p)). The reported scores are therefore
systematically overconfident by construction (for inflate > 1), and the
miscalibration is exactly a temperature miscalibration with T = inflate —
so temperature fitting should recover T ~= inflate, Platt should recover
a ~= 1/inflate, b ~= 0, and both should cut held-out ECE. All randomness
comes from a seeded random.Random; the tests are deterministic.
"""

from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path

from duly_calibration.base import Pair
from duly_calibration.facts import content_hash
from duly_core import schema_path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_EXAMPLES = REPO_ROOT / "spec" / "examples"
FACT_SCHEMA = schema_path("grounded-fact")


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def overconfident_pairs(n: int, *, seed: int, inflate: float = 2.5) -> list[Pair]:
    """n (score, correct) pairs whose scores are overconfident by a known
    temperature `inflate`. See module docstring."""
    rng = random.Random(seed)
    pairs: list[Pair] = []
    for _ in range(n):
        p_true = rng.uniform(0.2, 0.98)
        label = 1 if rng.random() < p_true else 0
        score = sigmoid(inflate * logit(p_true))
        pairs.append((score, label))
    return pairs


def load_raw_spec_fact() -> dict:
    """A GroundedFact example from spec/examples, rewritten to
    confidence.method == "raw" (and rehashed so it stays self-consistent),
    as recalibrate_fact requires."""
    for path in sorted(SPEC_EXAMPLES.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" not in doc and "confidence" in doc:
            fact = copy.deepcopy(doc)
            fact["confidence"] = {"score": fact["confidence"]["score"], "method": "raw"}
            return rehash(fact)
    raise AssertionError("no GroundedFact example with confidence found in spec/examples")


def rehash(fact: dict) -> dict:
    """Copy of `fact` with contentHash and id recomputed, keeping modified
    test facts consistent with the content-address rule (spec D8)."""
    fact = copy.deepcopy(fact)
    digest = content_hash(fact)
    fact["contentHash"] = digest
    fact["id"] = f"urn:duly:fact:sha256:{digest}"
    return fact
