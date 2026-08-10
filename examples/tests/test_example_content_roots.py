"""The demo's default content root is this repository's example content.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `demo/tests/test_content_roots.py`, which asserts M5 decision
D2 — that the four surfaces read *whatever* corpus they are pointed at, and
say so honestly when pointed at nothing. That is toolkit, and it stays there.

This is the other half, and it is not the same claim: that `uvicorn
demo.app:app` with no configuration at all serves six packs and a golden
corpus, because that is what this repository ships under `examples/`. After
`git rm -r examples/` the default root is an empty directory and the surfaces
are expected to say so — which is exactly what the file this came from
asserts, and why a count of six could not stay beside it.
"""

from __future__ import annotations

import sys

from exampletest_helpers import EXAMPLES, REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import demo.content  # noqa: E402


def test_the_repo_default_still_finds_everything():
    # Read through the module rather than binding `CONTENT` at import: another
    # suite in a combined run may have reloaded `demo.content` under a temp
    # root and reloaded it back, and a name bound here would still be pointing
    # at whichever object happened to exist when this file was collected.
    content = demo.content.CONTENT
    assert content.root == EXAMPLES
    assert content.rulepacks.is_dir()
    assert content.golden.is_dir()
    assert len(list(content.rulepacks.glob("*/pack.yaml"))) == 6
