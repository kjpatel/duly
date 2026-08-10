"""Shared helpers for the extraction tests.

Deliberately NOT a conftest.py, for the same reason as
store/tests/storetest_helpers.py: these test dirs have no __init__.py, so a
second module named `conftest` would collide in sys.modules when the suites
run together.

Two corpora, and the distinction is load-bearing (CLAUDE.md, "a test that would
still pass with its subject deleted"):

* **`fixtures/`** — the toolkit corpus. Everything asserting *adapter or
  envelope* behaviour runs on the fixture scenario: one PDF, its committed
  rendition, and the targets file the committed facts were emitted from. It
  survives `git rm -r examples/`, so those suites keep failing loudly when the
  toolkit breaks rather than quietly ceasing to exist.
* **`starters/`** — example content, relocating under `examples/`. Only tests
  whose *subject* is that content (the committed starter facts are still what
  the adapter emits) may reach for the helpers below it; they move with it.
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


# --- EXAMPLE CONTENT (moves with examples/) ----------------------------------
#
# Used only by the tests whose subject is the committed starter content. When
# `starters/` relocates, these helpers and those tests go with it.

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
