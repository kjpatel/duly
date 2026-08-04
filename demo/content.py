"""Where the demo's content lives — one answer, given by the deployment.

The four demo surfaces are **toolkit, not teaching content**. Each reads
whatever packs, scenarios, cases and receipts exist rather than any particular
ones, which is why deleting `examples/` has to leave them booting and honestly
reporting that they found none, rather than leave them deleted (M5 plan, D2).

That only works if the directories they read are configuration. Each module
used to compute `REPO_ROOT = Path(__file__).resolve().parent.parent` for
itself — four copies of an assumption that duly's own checkout is the content,
which is true exactly once: here. Now there is one `CONTENT`, it defaults to
this repository so `uvicorn demo.app:app` is unchanged, and a deployment
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
        return self.root / "spec" / "examples"

    @property
    def dmn_examples(self) -> Path:
        return self.root / "dmn" / "examples"

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
        return cls(root=Path(env.get(ENV_VAR, REPO_ROOT)).resolve())


CONTENT = ContentRoots.from_env()
