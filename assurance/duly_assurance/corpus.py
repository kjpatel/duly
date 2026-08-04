"""Where a golden case's rule pack lives.

A case records its pack as a path (`rulepacks/<name>/pack.yaml`) because a
receipt pins the pack's *name and version*, never its location — so something
has to say what that path is relative to, and the three commands over the
corpus used to each answer differently:

- `verify` and `generate` resolved against `parents[2]` of the *installed
  package*, falling back to the working directory. That is the repository only
  while duly runs from a checkout; from a wheel it is a directory inside
  site-packages (the same shape as finding A8, where the review queue read a
  schema that no wheel carries).
- `impact` resolved against the working directory, then the corpus's parent —
  which is right, and is what this module now does for all three.

The rule: a caller's path is relative to the caller. duly does not know where
an adopter keeps their packs, and guessing its own layout is correct exactly
once — in this repository, which is the one place the mistake cannot show up.
"""

from __future__ import annotations

from pathlib import Path


class PackNotFound(Exception):
    """A case's pack reference did not resolve against any candidate root."""


def resolve_pack_path(pack_ref: str, golden_root: Path) -> Path:
    """Resolve a case's pack reference to a file.

    Absolute paths are taken as given. A relative path is tried against the
    working directory first — what the author of the path meant — and then
    against the corpus root's parent, so a corpus that sits beside its packs
    resolves without the caller having to `cd` anywhere.

    Raises `PackNotFound` naming every candidate tried, because "pack not
    found" without the paths is the least actionable error in a corpus run.
    """
    ref = Path(pack_ref)
    if ref.is_absolute():
        candidates = [ref]
    else:
        candidates = [Path.cwd() / ref, golden_root.parent / ref]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PackNotFound(
        f"pack not found: {pack_ref} (tried {', '.join(str(c) for c in candidates)})"
    )
