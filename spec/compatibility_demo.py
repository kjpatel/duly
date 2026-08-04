#!/usr/bin/env python3
"""The two claims in the compatibility policy that are executable.

[compatibility.md](compatibility.md) is mostly a set of promises about what
will not change. Two of its claims are not promises but behaviour, and this
script runs both on a committed receipt.

**C4 — two receipts agree when their decision digests match.** `receiptSha256`
identifies an artifact, so the same adjudication run twice on different
machines, under a different evaluation backend, or against a pack fetched from
a different URL produces different receipts. Every mutation below leaves the
adjudication untouched and changes the receipt hash; the digest does not move.
Then two that genuinely decide differently, where it does.

**C3 — replay is scoped to a semantics version.** A receipt claiming semantics
this kernel does not implement is refused rather than replayed. The receipt is
re-sealed first, so its hash and its facts verify: the interesting case is not
a broken document but a perfectly good one this kernel has no standing to
check.

Run from the repo root:

    uv run python spec/compatibility_demo.py

Deterministic: same committed receipt, same mutations, same digests, forever.
"""
from __future__ import annotations

import copy
import json
import pathlib

from duly_core import content_hash
from duly_kernel import UnsupportedSemantics, check_replayable, decision_digest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECEIPT_PATH = ROOT / "golden" / "receipts" / "notice-ny-0007.json"


def _reseal(receipt: dict) -> dict:
    """What a producer does after changing anything: re-address the document."""
    receipt["receiptSha256"] = content_hash(receipt, "receiptSha256")
    receipt["id"] = f"urn:duly:receipt:sha256:{receipt['receiptSha256']}"
    return receipt


def _mutated(receipt: dict, mutate) -> dict:
    other = copy.deepcopy(receipt)
    mutate(other)
    return _reseal(other)


SAME_DECISION = [
    (
        "filed under a different case id",
        lambda r: r.__setitem__("caseId", "case:acme:loan-4471"),
    ),
    (
        "pack fetched from a different place",
        lambda r: r["rulePack"].update(
            {"gitCommit": "9f1c0b2", "url": "https://example.invalid/packs/notice"}
        ),
    ),
    (
        "evaluated by a Soufflé backend",
        lambda r: r["engine"].__setitem__("backend", "souffle"),
    ),
    (
        "evaluated by somebody else's kernel entirely",
        lambda r: r["engine"].__setitem__("kernel", "acme-kernel"),
    ),
]

DIFFERENT_DECISION = [
    (
        "a later version of the same pack",
        lambda r: r["rulePack"].__setitem__("version", "2026.4.0"),
    ),
    (
        "different decision semantics",
        lambda r: r["engine"].__setitem__("version", "0.0.2"),
    ),
]


def main() -> int:
    receipt = json.loads(RECEIPT_PATH.read_text())
    base_hash = receipt["receiptSha256"]
    base_digest = decision_digest(receipt)

    print(f"receipt   {RECEIPT_PATH.relative_to(ROOT)}")
    print(f"  decision  {receipt['decision']['attribute']} = "
          f"{receipt['decision']['value']['value']}")
    print(f"  hash      {base_hash[:16]}…")
    print(f"  digest    {base_digest[:16]}…")

    print("\nC4 — same adjudication, different run: the artifact moves, the "
          "decision does not")
    print(f"  {'':52} {'receiptSha256':16}  {'decisionDigest':16}")
    for label, mutate in SAME_DECISION:
        other = _mutated(receipt, mutate)
        digest = decision_digest(other)
        assert other["receiptSha256"] != base_hash
        assert digest == base_digest
        print(f"  {label:52} {other['receiptSha256'][:14]}…  {digest[:14]}…  ==")

    print("\n  ...and where the adjudication itself differs, so does the digest")
    for label, mutate in DIFFERENT_DECISION:
        other = _mutated(receipt, mutate)
        digest = decision_digest(other)
        assert digest != base_digest
        print(f"  {label:52} {other['receiptSha256'][:14]}…  {digest[:14]}…  !=")

    print("\n  So: byte equality is agreement PLUS having been the same run.")
    print("  A second backend cannot produce identical bytes by construction —")
    print("  engine.backend is inside the hashed body — which is why agreement")
    print("  is defined as digest equality and not as a relaxed comparison.")

    print("\nC3 — replay is scoped to a semantics version")
    foreign = _mutated(receipt, lambda r: r["engine"].__setitem__("version", "0.0.2"))
    recomputed = content_hash(foreign, "receiptSha256")
    print(f"  the receipt is internally perfect: recomputed hash matches "
          f"({recomputed[:14]}… == {foreign['receiptSha256'][:14]}…)")
    assert recomputed == foreign["receiptSha256"]

    check_replayable(receipt)
    print("  this kernel replays its own semantics:      ok")
    try:
        check_replayable(foreign)
    except UnsupportedSemantics as exc:
        print(f"  and refuses semantics it does not implement:\n    {exc}")
    else:  # pragma: no cover - the guard is the point of the script
        raise SystemExit("FAILED: a foreign semantics version was accepted")

    print("\n  A kernel implementing 0.0.2 would agree with this receipt on most")
    print("  inputs — which is exactly why it must not answer for it at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
