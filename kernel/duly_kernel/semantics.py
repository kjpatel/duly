"""Which decision semantics this kernel implements, and what it does with a
receipt that claims another.

The replay guarantee ([spec/compatibility.md](../../spec/compatibility.md) C3)
is scoped to a semantics version, not to a kernel:

    A receipt sealed under semantics version V replays byte-identically under
    any kernel implementing V. A kernel MAY implement more than one V.

That sentence has a consequence with teeth: a kernel that meets a receipt
whose ``engine.version`` it does not implement must **refuse**, naming the
version. Not attempt and fail with a confusing byte diff, and — the case that
matters — not attempt and *succeed by coincidence* on the cases where two
semantics happen to agree. A coincidental pass is the worst outcome available:
it licenses a claim ("this receipt replays") that the kernel is not entitled
to make about receipts in general.

Before this module nothing anywhere read ``engine.version``. `verify`
re-adjudicated all 351 golden receipts without once checking whose semantics
they claimed, which was harmless while exactly one version has ever existed and
would have become a silent lie on the first rev — the moment the check is worth
having is the moment it is hardest to add, because by then a corpus already
depends on it.

Adding a version to ``IMPLEMENTED`` is not a chore. It asserts that this
kernel reproduces that version's decisions byte-for-byte, and the corpus is
what proves it: cases at every implemented version, replayed in CI.
"""

from __future__ import annotations

from .receipt import SEMANTICS_VERSION

__all__ = [
    "IMPLEMENTED",
    "UnsupportedSemantics",
    "implements",
    "receipt_semantics",
    "check_replayable",
]


#: Every decision-semantics version this kernel can reproduce. One today, and
#: the singleton is the point: a second entry is a promise that this code
#: reproduces both, which only the corpus can substantiate.
IMPLEMENTED: frozenset[str] = frozenset({SEMANTICS_VERSION})


class UnsupportedSemantics(Exception):
    """A receipt claims decision semantics this kernel does not implement."""

    def __init__(self, claimed: str | None) -> None:
        self.claimed = claimed
        implemented = ", ".join(sorted(IMPLEMENTED))
        if claimed is None:
            message = (
                "receipt does not name its decision semantics (engine.version); "
                "replay is scoped to a semantics version, so a receipt that "
                "does not claim one cannot be replayed"
            )
        else:
            message = (
                f"receipt claims decision semantics {claimed!r}, which this "
                f"kernel does not implement (implements: {implemented}). "
                "Replaying it here would answer a question about different "
                "semantics than the ones it was sealed under."
            )
        super().__init__(message)


def implements(version: str | None) -> bool:
    """Can this kernel reproduce decisions sealed under `version`?"""
    return version is not None and version in IMPLEMENTED


def receipt_semantics(receipt: dict) -> str | None:
    """The semantics version a receipt claims, or None if it names none."""
    engine = receipt.get("engine")
    if not isinstance(engine, dict):
        return None
    version = engine.get("version")
    return version if isinstance(version, str) else None


def check_replayable(receipt: dict) -> None:
    """Raise `UnsupportedSemantics` unless this kernel implements the receipt's.

    The guard every replay path calls before re-adjudicating. It says nothing
    about whether the receipt is *correct* — only that this kernel is entitled
    to have an opinion about it.
    """
    version = receipt_semantics(receipt)
    if not implements(version):
        raise UnsupportedSemantics(version)
