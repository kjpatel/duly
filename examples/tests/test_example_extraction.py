"""The committed starter facts are still exactly what the stub adapter emits.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `extraction/tests/test_adapters.py`, which asserts every claim
about the *adapter* — quote location, normalization, confidence, envelope
shape, byte-identical re-runs — against the fixture scenario. This one asserts
nothing the fixture twin does not already assert about the toolkit. What it
adds is a claim about the shipped starters: that the fact files committed
under `examples/starters/*/facts` are byte-for-byte what re-running extraction
over the starter targets produces, key order included.

The byte comparison is the point. A fact is content-addressed, so a
whitespace-level difference between what is committed and what the pipeline
emits today would mean the starter's `contentHash` no longer describes any
document the toolkit can produce.
"""

from __future__ import annotations

import json

import pytest

from duly_extraction.adapter import SourceDocument
from duly_extraction.stub import StubAdapter

from exampletest_helpers import STARTERS

TARGETS = STARTERS / "tools" / "targets"

#: targets file -> (scenario directory, committed rendition/document stem)
STARTER_RUNS = {
    "notice-ny-dec-page.json": ("notice-ny", "dec-page"),
    "notice-ny-nonrenewal-notice.json": ("notice-ny", "nonrenewal-notice"),
    "trid-loan-estimate.json": ("trid", "loan-estimate"),
    "trid-closing-disclosure.json": ("trid", "closing-disclosure"),
}


def run_stub(targets_name: str):
    """Run the stub adapter over one committed starter document.

    Returns (ExtractionResult, targets dict, rendition text).
    """
    scenario, doc = STARTER_RUNS[targets_name]
    targets = json.loads((TARGETS / targets_name).read_text(encoding="utf-8"))
    text = (STARTERS / scenario / "renditions" / f"{doc}.txt").read_text(encoding="utf-8")
    pdf = (STARTERS / scenario / "documents" / f"{doc}.pdf").read_bytes()
    document = SourceDocument.from_bytes(targets["documentId"], pdf)
    return StubAdapter(text).extract(document, targets), targets, text


@pytest.mark.parametrize("targets_name", sorted(STARTER_RUNS))
def test_stub_reproduces_committed_facts(targets_name):
    result, targets, _text = run_stub(targets_name)
    scenario, _doc = STARTER_RUNS[targets_name]
    assert len(result.facts) == len(targets["facts"])
    for target, fact in zip(targets["facts"], result.facts):
        committed_path = STARTERS / scenario / "facts" / target["file"]
        # Byte-for-byte, including key order — the same serialization
        # examples/starters/tools/extract.py writes.
        assert json.dumps(fact, indent=2, ensure_ascii=False) + "\n" == committed_path.read_text(
            encoding="utf-8"
        )
