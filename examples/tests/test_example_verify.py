"""The committed teaching corpus replays, byte for byte, all 351 of it.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `assurance/tests/test_verify.py`, which had already converted
every other corpus it builds to a copy of `fixtures/`. This is the one whose
subject is not the verifier but the *corpus*: the claim is that these committed
receipts — this pack set, these facts, this semantics version — still reproduce
under `duly_assurance.verify`. The verifier's own contract (tampered bodies,
tampered hashes, a missing pack, an empty corpus) stays there and survives the
deletion.

The count is asserted rather than inferred. `verify` exits 0 on an empty corpus
by design (`assurance/tests/test_empty_corpus.py` pins that), so a run over a
`golden/` that had lost its cases would pass in silence.
"""

from __future__ import annotations

from exampletest_helpers import GOLDEN

from duly_assurance import verify


def test_verify_passes_on_the_committed_golden_corpus(capsys):
    assert (GOLDEN / "cases").is_dir(), f"no committed corpus at {GOLDEN}"
    assert verify.main(["--golden", str(GOLDEN)]) == 0
    assert "verified 351 cases" in capsys.readouterr().out
