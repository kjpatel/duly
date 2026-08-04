#!/usr/bin/env python3
"""Regenerate spec/decision-digest-vectors.json.

The vectors are **self-contained**: each carries a whole receipt and the digest
it must produce, so an implementation in another language can be held to them
without duly's corpus, its kernel, or this repository. Two of them are real
committed receipts (asserted byte-identical by
`kernel/tests/test_decision_digest.py`, so a vector cannot drift into being a
plausible fabrication); the rest are derived from one of those by changing
exactly one thing, which is how they demonstrate the equivalence relation
rather than merely asserting it.

Run after changing the determinant set — which is a breaking change to the
digest and wants arguing in spec/compatibility.md C4 first, not regenerating.

    uv run spec/make_decision_digest_vectors.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "kernel"))
sys.path.insert(0, str(REPO / "core"))

from duly_kernel.digest import (  # noqa: E402
    DETERMINANT_FIELDS,
    decision_digest,
)

GOLDEN = REPO / "golden" / "receipts"
OUT = REPO / "spec" / "decision-digest-vectors.json"

# A minimal real receipt (no input facts, no abstentions) and a fuller one
# (nested derivation, four input facts, a live abstention). Between them the
# determinant set is exercised whole.
BASE_CASE = "esign-0005"
FULL_CASE = "notice-ny-0007"


def _load(case: str) -> dict:
    return json.loads((GOLDEN / f"{case}.json").read_text())


def _variant(base: dict, description: str, cls: str, mutate) -> dict:
    receipt = copy.deepcopy(base)
    mutate(receipt)
    return {
        "description": description,
        "equivalenceClass": cls,
        "receipt": receipt,
        "decisionDigest": decision_digest(receipt),
    }


def build() -> dict:
    base = _load(BASE_CASE)
    full = _load(FULL_CASE)
    cls = f"{BASE_CASE}-as-decided"

    def _rebrand(receipt: dict) -> None:
        receipt["engine"]["kernel"] = "acme-kernel"
        receipt["id"] = "urn:duly:receipt:sha256:" + "0" * 64
        receipt["receiptSha256"] = "0" * 64

    def _flip(receipt: dict) -> None:
        receipt["decision"]["value"]["value"] = True
        receipt["derivation"]["conclusion"]["value"]["value"] = True

    vectors = [
        {
            "description": (
                f"the committed golden receipt {BASE_CASE}, unmodified"
            ),
            "equivalenceClass": cls,
            "receipt": base,
            "decisionDigest": decision_digest(base),
        },
        _variant(
            base,
            "same adjudication, different case id — caseId is bookkeeping",
            cls,
            lambda r: r.__setitem__("caseId", "case:acme:loan-4471"),
        ),
        _variant(
            base,
            "same adjudication, pack provenance added — where a pack was "
            "fetched from is not what it says",
            cls,
            lambda r: r["rulePack"].update(
                {
                    "gitCommit": "9f1c0b2",
                    "url": "https://example.invalid/packs/esign-closing-package",
                }
            ),
        ),
        _variant(
            base,
            "same adjudication, different evaluation backend — this is the "
            "cross-backend agreement claim, executable",
            cls,
            lambda r: r["engine"].__setitem__("backend", "souffle"),
        ),
        _variant(
            base,
            "same adjudication, different kernel implementation, and the "
            "artifact identity fields deliberately wrong — the digest is over "
            "what was decided, not over a correctly sealed document",
            cls,
            _rebrand,
        ),
        _variant(
            base,
            "different decision semantics — engine.version is determinant "
            "because different semantics can mean different decisions",
            f"{BASE_CASE}-under-other-semantics",
            lambda r: r["engine"].__setitem__("version", "0.0.2"),
        ),
        _variant(
            base,
            "different pack version — a pack's identity is its name and version",
            f"{BASE_CASE}-under-later-pack",
            lambda r: r["rulePack"].__setitem__("version", "2026.2.0"),
        ),
        _variant(
            base,
            "the opposite conclusion (synthetic: the value flipped in both the "
            "decision and the derivation)",
            f"{BASE_CASE}-flipped",
            _flip,
        ),
        {
            "description": (
                f"the committed golden receipt {FULL_CASE}, unmodified — "
                "nested derivation, four input facts, one abstention"
            ),
            "equivalenceClass": f"{FULL_CASE}-as-decided",
            "receipt": full,
            "decisionDigest": decision_digest(full),
        },
    ]

    return {
        "$comment": (
            "Decision-digest test vectors for duly. Any implementation must "
            "reproduce every `decisionDigest` exactly; vectors sharing an "
            "`equivalenceClass` must have equal digests, and vectors in "
            "different classes must have different ones. See "
            "spec/compatibility.md C4 and kernel/duly_kernel/digest.py. "
            "Generated by spec/make_decision_digest_vectors.py."
        ),
        "digest": {
            "input": (
                "the receipt's determinant fields, projected into one object: "
                "the fields below whole, plus rulePack.{name,version} and "
                "engine.version"
            ),
            "determinantFields": list(DETERMINANT_FIELDS),
            "rulePackFields": ["name", "version"],
            "engineFields": ["version"],
            "excluded": [
                "id",
                "receiptSha256",
                "caseId",
                "rulePack.gitCommit",
                "rulePack.url",
                "engine.kernel",
                "engine.backend",
            ],
            "canonicalForm": (
                "as spec/canonical-vectors.json — RFC 8785 key order, minimal "
                "separators, non-ASCII raw, UTF-8"
            ),
            "hash": "SHA-256, lowercase hex, over the projection's canonical bytes",
        },
        "vectors": vectors,
    }


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
