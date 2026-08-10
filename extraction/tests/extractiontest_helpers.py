"""Shared helpers for the extraction tests.

Deliberately NOT a conftest.py, for the same reason as
store/tests/storetest_helpers.py: these test dirs have no __init__.py, so a
second module named `conftest` would collide in sys.modules when the suites
run together.

One corpus, and the distinction is load-bearing (CLAUDE.md, "a test that would
still pass with its subject deleted"). **`fixtures/`** is the toolkit corpus:
everything asserting *adapter or envelope* behaviour runs on the fixture
scenario — one PDF, its committed rendition, and the targets file the
committed facts were emitted from. It survives `git rm -r examples/`, so those
suites keep failing loudly when the toolkit breaks rather than quietly ceasing
to exist.

The starter-pointed loaders that used to sit at the bottom of this module went
with the one test that used them, to
`examples/tests/test_example_extraction.py`: whether the committed starter
facts are still what the adapter emits is a claim about those starters, and it
is deleted with them.
"""

import hashlib
import json
from pathlib import Path

from duly_extraction.adapter import SourceDocument
from duly_extraction.stub import StubAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- the toolkit corpus ------------------------------------------------------

FIXTURES = REPO_ROOT / "fixtures"
FIXTURE_SCENARIO = FIXTURES / "scenario"
FIXTURE_TARGETS = FIXTURES / "targets"
FIXTURE_ONTOLOGIES = FIXTURES / "ontology"

#: The one fixture scenario document. The targets file lives beside the corpus
#: rather than inside `scenario/` because that is where a deployment keeps it —
#: one shared directory keyed by the `documentId` *field*, filename by
#: convention (fixtures/build.py, "the scenario").
FIXTURE_TARGETS_FILE = "fx-0005-widget-report.json"
FIXTURE_DOCUMENT = "widget-report"


def load_fixture_targets() -> dict:
    return json.loads((FIXTURE_TARGETS / FIXTURE_TARGETS_FILE).read_text(encoding="utf-8"))


def load_fixture_rendition_text() -> str:
    return (
        FIXTURE_SCENARIO / "renditions" / f"{FIXTURE_DOCUMENT}.txt"
    ).read_text(encoding="utf-8")


def load_fixture_pdf_bytes() -> bytes:
    return (FIXTURE_SCENARIO / "documents" / f"{FIXTURE_DOCUMENT}.pdf").read_bytes()


def load_fixture_fact(filename: str) -> str:
    """The committed fact file's *text* — byte comparison is the point."""
    return (FIXTURE_SCENARIO / "facts" / filename).read_text(encoding="utf-8")


def run_fixture_stub(targets: dict | None = None):
    """Run the stub adapter over the committed fixture document.

    Returns (ExtractionResult, targets dict, rendition text). Pass `targets` to
    script a *different* run over the same document — a second runId, a subset
    of the facts — which is how the suites get two runs without a second
    committed PDF.
    """
    targets = load_fixture_targets() if targets is None else targets
    text = load_fixture_rendition_text()
    document = SourceDocument.from_bytes(targets["documentId"], load_fixture_pdf_bytes())
    result = StubAdapter(text).extract(document, targets)
    return result, targets, text


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
