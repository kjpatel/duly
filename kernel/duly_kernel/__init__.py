"""duly reference kernel: rule IR loading, deterministic evaluation, receipt emission."""

# The kernel package's own version, and nothing else's. Bumping it does NOT
# change a single receipt byte: the receipt's `engine.version` is a
# *decision-semantics* version pinned as receipt.SEMANTICS_VERSION and
# deliberately decoupled from this one. They read the same today; that is a
# coincidence, not a link. Read the comment on SEMANTICS_VERSION before
# touching either.
__version__ = "0.0.1"

from .api import adjudicate  # noqa: E402,F401
