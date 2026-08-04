"""duly reference kernel: rule IR loading, deterministic evaluation, receipt emission."""

# The kernel package's own version, and nothing else's. Bumping it does NOT
# change a single receipt byte: the receipt's `engine.version` is a
# *decision-semantics* version pinned as receipt.SEMANTICS_VERSION and
# deliberately decoupled from this one. They read the same today; that is a
# coincidence, not a link. Read the comment on SEMANTICS_VERSION before
# touching either.
#
# This is also the *only* `__version__` in the repository. Six others existed,
# had no reader and no rule forcing them to move, and were deleted at the
# freeze (spec/compatibility.md C8); this one survives because it expresses a
# decision — the kernel stays 0.0.1 while the distribution goes 1.0.0 — and
# there would otherwise be nowhere to say it. Adopters read the shipped
# version with `importlib.metadata.version("duly")`.
__version__ = "0.0.1"

from .api import adjudicate  # noqa: E402,F401

# Content addressing is the first thing an integration touches — a fact must
# be sealed before anything can consume it — so it belongs at the package
# root, not behind `duly_kernel.receipt`, which reads private and was where
# every adopter had to reach (docs/m5-plan.md, Appendix A finding A1).
from .receipt import content_hash, seal_fact  # noqa: E402,F401

# The two halves of the compatibility promise (spec/compatibility.md): which
# semantics a receipt may be replayed under, and what "the same decision"
# means when two receipts are not byte-identical. Both are consumed by
# integrations, not just by duly, so both sit at the package root.
from .digest import decision_digest  # noqa: E402,F401
from .semantics import (  # noqa: E402,F401
    IMPLEMENTED,
    UnsupportedSemantics,
    check_replayable,
)

__all__ = [
    "adjudicate",
    "content_hash",
    "seal_fact",
    "decision_digest",
    "check_replayable",
    "UnsupportedSemantics",
    "IMPLEMENTED",
]
