"""Where the demo's content lives — one answer, given by the deployment.

The four demo surfaces are **toolkit, not teaching content**. Each reads
whatever packs, scenarios, cases and receipts exist rather than any particular
ones, which is why deleting `examples/` has to leave them booting and honestly
reporting that they found none, rather than leave them deleted (M5 plan, D2).

That only works if the directories they read are configuration. Each module
used to compute `REPO_ROOT = Path(__file__).resolve().parent.parent` for
itself — four copies of an assumption that duly's own checkout is the content,
which is true exactly once: here. Now there is one `CONTENT`, it defaults to
this repository so `uvicorn duly_demo.app:app` is unchanged, and a deployment
pointing at its own corpus sets `DULY_DEMO_CONTENT`.

**A missing directory is not an error.** Every root below may be absent, and
the surfaces are expected to say so rather than fail: a fresh adopter has no
`golden/` and no `starters/`, and a demo that refuses to start until they do
would be answering a question nobody asked. `exists()` is provided so callers
can report the absence in the shape their page wants.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ContentRoots", "CONTENT", "REPO_ROOT"]

# This repository, as a default. Not "the content" — the default value of it.
REPO_ROOT = Path(__file__).resolve().parent.parent

# Where this repository keeps its own teaching content. The *contract* for a
# content root did not move when the content did: a deployment's root still
# holds `starters/`, `golden/`, `rulepacks/`, `ontologies/`, `dmn/` directly —
# nobody adopting duly should have to mirror this repository's `examples/`
# nesting. What changed is only which directory this repo offers as the
# default root.
DEFAULT_ROOT = REPO_ROOT / "examples"

ENV_VAR = "DULY_DEMO_CONTENT"


@dataclass(frozen=True)
class ContentRoots:
    """The directories the demo reads, all relative to one root."""

    root: Path

    @property
    def starters(self) -> Path:
        return self.root / "starters"

    @property
    def golden(self) -> Path:
        return self.root / "golden"

    @property
    def rulepacks(self) -> Path:
        return self.root / "rulepacks"

    @property
    def ontologies(self) -> Path:
        return self.root / "ontologies"

    @property
    def spec_examples(self) -> Path:
        """The demo's built-in fixture scenario — NOT deployment content.

        Pinned to this repository's `spec/examples` rather than derived from
        `root`: it is the committed contract example the demo serves when it
        has no content at all, so it ships with the demo and does not move
        when a deployment points `root` elsewhere. Deriving it from `root`
        would make the built-in disappear under any custom content root —
        which is exactly the state it exists to make honest.
        """
        return REPO_ROOT / "spec" / "examples"

    @property
    def dmn_examples(self) -> Path:
        # `<root>/dmn`, not `<root>/dmn/examples`: the old shape leaked this
        # repository's pre-move layout (the compiler package at dmn/ with its
        # examples nested inside) into the content contract.
        return self.root / "dmn"

    def contains(self, path: Path) -> bool:
        """Is `path` inside the content root?

        The containment check behind every endpoint that takes a path from a
        caller. It is deliberately a method here rather than four copies of
        `try: p.relative_to(ROOT) except ValueError:` — a guard rewritten per
        call site is a guard that will eventually be rewritten wrong.
        """
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "ContentRoots":
        env = environ if environ is not None else os.environ
        return cls(root=Path(env.get(ENV_VAR, DEFAULT_ROOT)).resolve())


CONTENT = ContentRoots.from_env()
