"""duly reference kernel: rule IR loading, deterministic evaluation, receipt emission."""

# The kernel package's own version, and nothing else's. Bumping it does NOT
# change a single receipt byte: the receipt's `engine.version` is a
# *decision-semantics* version pinned as receipt.SEMANTICS_VERSION and
# deliberately decoupled from this one. They read the same today; that is a
# coincidence, not a link. Read the comment on SEMANTICS_VERSION before
# touching either.
__version__ = "0.0.1"

from .api import adjudicate  # noqa: E402,F401

# Content addressing is the first thing an integration touches — a fact must
# be sealed before anything can consume it — so it belongs at the package
# root, not behind `duly_kernel.receipt`, which reads private and was where
# every adopter had to reach (docs/m5-plan.md, Appendix A finding A1).
from .receipt import content_hash, seal_fact  # noqa: E402,F401

__all__ = ["adjudicate", "content_hash", "seal_fact"]
