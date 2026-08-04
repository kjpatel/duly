"""`engine.version` is decision semantics, not a package version.

The receipt's `engine` block sits inside the hashed body, so every value in it
is sealed into artifacts that cannot be edited. `engine.version` therefore
tracks what the kernel *means*, not what the wheel is called this month —
otherwise a routine release invalidates the whole golden corpus without a rule,
a fact, or a decision having moved.

These tests exist to fail loudly on the tidying-up edit that would re-couple
them, which is the natural thing to do while packaging the toolkit for release.
"""

from __future__ import annotations

import json
from pathlib import Path

import duly_kernel
from duly_kernel.api import adjudicate
from duly_kernel.receipt import SEMANTICS_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_RECEIPTS = REPO_ROOT / "golden" / "receipts"

AS_OF_EFFECTIVE = "2026-07-25"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"
QUESTION = "nc:noticeCompliant"


def test_the_pinned_semantics_version_is_the_one_the_corpus_carries():
    """Changing this is a semantics change that rewrites golden/, not a chore.

    If this fails, the fix is *not* to relax the assertion: restore the value
    the committed receipts carry and leave the package versions wherever the
    release put them.
    """
    assert SEMANTICS_VERSION == "0.0.1"


def test_bumping_the_package_version_moves_no_receipt_byte(monkeypatch, spec_facts, ny_pack):
    """The decoupling, proved behaviourally rather than by reading the source.

    Release the kernel at 1.0.0 and the same inputs must still produce the same
    bytes — including the same `receiptSha256`, which is the property all 351
    golden receipts depend on.
    """
    before = adjudicate(spec_facts, ny_pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, QUESTION)

    monkeypatch.setattr(duly_kernel, "__version__", "1.0.0")
    after = adjudicate(spec_facts, ny_pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, QUESTION)

    assert after["engine"]["version"] == SEMANTICS_VERSION
    assert after == before, (
        "the kernel package version has been re-coupled to engine.version; "
        "releasing would invalidate every committed receipt"
    )


def test_the_kernels_is_the_only_package_version_in_the_repository():
    """C8: six reader-less `__version__` strings were deleted at the freeze.

    They had no reader and no rule forcing them to move, and three packages had
    already skipped the convention without anyone noticing — which is the
    diagnosis, not an inconsistency to tidy up. A number nobody reads becomes a
    lie the first time its package changes.

    This pins the count at one so the convention cannot quietly regrow: the
    natural instinct, on adding a package, is to give it a version too.
    """
    packages = sorted(
        p
        for p in REPO_ROOT.glob("*/duly_*/__init__.py")
        if "__pycache__" not in str(p)
    )
    assert packages, "no duly packages found"
    declaring = sorted(
        p.parent.name for p in packages if "\n__version__" in "\n" + p.read_text()
    )
    assert declaring == ["duly_kernel"], (
        f"{declaring} declare __version__; only duly_kernel may. A package "
        "version with no reader is a claim nothing keeps true — see "
        "spec/compatibility.md C8."
    )


def test_the_committed_corpus_carries_the_pinned_semantics_version():
    """Whatever the packages are versioned at, the corpus says 0.0.1."""
    receipts = sorted(GOLDEN_RECEIPTS.glob("*.json"))
    assert receipts, "no golden receipts found"
    versions = {json.loads(p.read_text())["engine"]["version"] for p in receipts}
    assert versions == {SEMANTICS_VERSION}, (
        f"golden receipts carry {sorted(versions)}, kernel emits "
        f"{SEMANTICS_VERSION!r}; replay cannot survive this"
    )
