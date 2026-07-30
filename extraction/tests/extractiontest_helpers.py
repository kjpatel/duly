"""Shared helpers for the extraction tests.

Deliberately NOT a conftest.py, for the same reason as
store/tests/storetest_helpers.py: these test dirs have no __init__.py, so a
second module named `conftest` would collide in sys.modules when the suites
run together.

Fixtures come from the committed starters: real PDFs, their committed
renditions, and the targets files the committed facts were generated from —
so the stub adapter can be checked byte-for-byte against what is in git.
"""

import hashlib
import json
from pathlib import Path

from duly_extraction.adapter import SourceDocument
from duly_extraction.stub import StubAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTERS = REPO_ROOT / "starters"
TARGETS = STARTERS / "tools" / "targets"

# targets file -> (scenario dir, committed rendition, committed pdf)
STARTER_RUNS = {
    "notice-ny-dec-page.json": ("notice-ny", "dec-page"),
    "notice-ny-nonrenewal-notice.json": ("notice-ny", "nonrenewal-notice"),
    "trid-loan-estimate.json": ("trid", "loan-estimate"),
    "trid-closing-disclosure.json": ("trid", "closing-disclosure"),
}


def load_targets(targets_name: str) -> dict:
    return json.loads((TARGETS / targets_name).read_text(encoding="utf-8"))


def load_rendition_text(scenario: str, doc: str) -> str:
    return (STARTERS / scenario / "renditions" / f"{doc}.txt").read_text(encoding="utf-8")


def load_pdf_bytes(scenario: str, doc: str) -> bytes:
    return (STARTERS / scenario / "documents" / f"{doc}.pdf").read_bytes()


def load_committed_fact(scenario: str, filename: str) -> dict:
    return json.loads((STARTERS / scenario / "facts" / filename).read_text(encoding="utf-8"))


def run_stub(targets_name: str):
    """Run the stub adapter over one committed starter document; returns
    (ExtractionResult, targets dict, rendition text)."""
    scenario, doc = STARTER_RUNS[targets_name]
    targets = load_targets(targets_name)
    text = load_rendition_text(scenario, doc)
    document = SourceDocument.from_bytes(targets["documentId"], load_pdf_bytes(scenario, doc))
    result = StubAdapter(text).extract(document, targets)
    return result, targets, text


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
