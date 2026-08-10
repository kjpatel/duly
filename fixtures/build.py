#!/usr/bin/env python3
"""Regenerate the toolkit fixture corpus. See fixtures/README.md.

    uv run python fixtures/build.py

Deterministic by construction: every timestamp is a constant in this file, no
wall clock is read, and nothing is random. Running it twice writes the same
bytes, which is what `git diff -- fixtures/` checks.

This is the fixture-corpus twin of `duly_assurance.generate`, and deliberately
*not* that: the golden generator draws cases from weighted templates to produce
a corpus with distribution. Three hand-placed cases need none of that, and
reusing the generator would point the toolkit's own fixtures back at the
example content whose templates it carries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "kernel"))
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(REPO / "store"))
sys.path.insert(0, str(REPO / "extraction"))

from duly_extraction.adapter import SourceDocument  # noqa: E402
from duly_extraction.stub import StubAdapter  # noqa: E402
from duly_kernel import adjudicate, seal_fact  # noqa: E402

ONTOLOGY = {"ontology": "duly-fixture", "version": "0.1.0"}
EXTRACTOR = {"name": "duly-fixture-builder", "version": "0.1.0"}

# One fixed instant for everything asserted, and one for every evaluation.
# Constants rather than parameters: a fixture whose bytes depend on when it was
# built is not a fixture.
ASSERTED_AT = "2026-03-01T00:00:00Z"
KNOWLEDGE = "2026-03-02T12:00:00Z"

CASES = [
    {
        "id": "fx-0001",
        "effective": "2026-06-01",
        "note": "the exception fires and defeats the default; the threshold is derived",
        "score": ("12", 1.0),
        "category": "restricted",
    },
    {
        "id": "fx-0002",
        "effective": "2026-06-01",
        "note": "nothing overrides, so the default presumption stands",
        "score": ("80", 1.0),
        "category": "ordinary",
    },
    {
        "id": "fx-0003",
        "effective": "2026-06-01",
        "note": "one fact is below the pack's floor: a low_confidence abstention",
        "score": ("12", 0.62),  # below minConfidence 0.80, on purpose
        "category": "restricted",
    },
    # 0005 is the scenario, not a corpus case; the gap is deliberate.
    {
        "id": "fx-0006",
        "effective": "2026-06-01",
        "note": "restricted but above the threshold — the category matches and "
                "the score still clears, so the exception does not fire",
        # 60 sits *between* the two thresholds this pack has ever declared (50
        # from 2026, 10 before it) and above both. That is the point of the
        # case: it is the only one an edit to the threshold can move on its
        # own. Every other corpus case scores 12 or 80, so a threshold change
        # either flips all three restricted cases together or none — and a
        # corpus that can only answer "everything moved" cannot demonstrate
        # what impact analysis is for, which is a pack whose *meaning* moved
        # while its declared outcomes stayed green.
        "score": ("60", 1.0),
        "category": "restricted",
    },
]


def _fact(case_id: str, attribute: str, value: dict, score: float) -> dict:
    return seal_fact(
        {
            "caseId": f"case:fixture:{case_id}",
            "entity": {"id": f"widget:{case_id}", "type": "fx:Widget"},
            "attribute": attribute,
            "value": value,
            "grounding": {
                "kind": "attestation",
                "actor": "duly-fixture-builder",
                "channel": "synthetic",
                "at": ASSERTED_AT,
            },
            "assertion": {"kind": "machine", "at": ASSERTED_AT, "extractor": EXTRACTOR},
            "confidence": {"score": score, "method": "raw"},
            "recordedAt": ASSERTED_AT,
            "status": "asserted",
            "schemaRef": dict(ONTOLOGY),
        }
    )


REVIEWER = {"id": "reviewer:fx-demo", "role": "fixture-review"}
CORRECTED_AT = "2026-03-03T09:00:00Z"


def _correction(case_id: str, supersedes: str, value: dict) -> dict:
    """A human-asserted fact that supersedes a below-floor machine one.

    The fixture corpus needs one because several toolkit behaviours are only
    reachable through it — PROV-O's `wasAttributedTo`/`wasRevisionOf` mapping,
    the review queue's resolution rule, and the shape of a receipt whose
    abstention has been answered.
    """
    return seal_fact(
        {
            "caseId": f"case:fixture:{case_id}",
            "entity": {"id": f"widget:{case_id}", "type": "fx:Widget"},
            "attribute": "fx:score",
            "value": value,
            "grounding": {
                "kind": "attestation",
                "actor": REVIEWER["id"],
                "channel": "fixture-review",
                "at": CORRECTED_AT,
            },
            "assertion": {"kind": "human", "at": CORRECTED_AT, "actor": dict(REVIEWER)},
            "supersedes": supersedes,
            "recordedAt": CORRECTED_AT,
            "status": "asserted",
            "schemaRef": dict(ONTOLOGY),
        }
    )


# --- the scenario -----------------------------------------------------------
#
# The demo surfaces read *scenarios*, not corpora: a document, the extractor's
# rendition of it, and facts grounded in character spans of that rendition. The
# corpus cases above use attestation grounding, which is honest for synthetic
# data but leaves the span machinery — the evidence browser's highlighting, the
# report's quotes, span verification itself — with nothing to exercise.
#
# So one scenario, built the way the teaching starters are built and by the
# same code: this file writes a **targets file** (the adapter's fact-proposal
# seam — see extraction/duly_extraction/adapter.py) and the committed facts are
# whatever `StubAdapter.extract` emits from it. Nothing here assembles a fact
# by hand.
#
# That is not tidiness. A demo deployment ingests a scenario by running the
# targets through the adapter into a session store, so a scenario whose
# committed facts were built by some *other* code is a scenario whose store
# projection and disk projection can silently disagree — and the fixture
# scenario's did: its hand-built grounding used a `renditionId` + `locator`
# pair that the schema's DocumentGrounding (`additionalProperties: false`,
# `rendition` required, charSpan-or-bbox) does not admit at all. Nothing
# caught it, because the only checker that reads these facts is the ontology
# conformance gate, which validates attributes and values rather than the
# envelope around them. One producer, one shape.

DOC_LINES = [
    ("title", "WIDGET INSPECTION REPORT"),
    ("", ""),
    ("label", "Report reference: FX-INSPECTION-0005"),
    ("label", "Inspected under: fixture regime (fictional)"),
    ("", ""),
    ("body", "Measured score: 12"),
    ("body", "Assigned category: restricted"),
    ("body", "Inspector of record: Dana Okafor, 41 Alder Row"),
    ("", ""),
    ("body", "This document is a fixture. It describes nothing real."),
]

SCENARIO_CASE = "fx-0005"
SCENARIO_DOC = "doc:widget-report:FX-INSPECTION-0005"

#: The extraction run this scenario's facts come from. Named rather than
#: derived (`derive_run_id` would do) so the id is legible in an envelope and
#: in `assertion.extractor.runId`, and so the review arc's own run id —
#: `duly_demo/app.py` rewrites it to `run:<scenario>:review-demo` — is visibly a
#: *different* run over the same document rather than an unlabeled second one.
SCENARIO_RUN = "run:fixture:0005"

#: The fact proposals the adapter is asked to ground, in the shape
#: `extraction/duly_extraction/adapter.py` documents. This list is the source
#: of truth for the scenario: `fixtures/targets/` commits it verbatim, the
#: committed facts are what the stub emits from it, and a demo deployment
#: ingests the same file. Confidences are scripted demo values passed through
#: verbatim by the stub — they are not calibration output.
SCENARIO_TARGETS = [
    {
        "file": "fx-score.json",
        "entity": {"id": f"widget:{SCENARIO_CASE}", "type": "fx:Widget"},
        "attribute": "fx:score",
        "value": {"kind": "decimal", "value": "12"},
        "quote": "Measured score: 12",
        # Below the pack's 0.80 floor, so the scenario carries a live
        # abstention the demo's review arc has something to resolve.
        "confidence": {"score": 0.62, "method": "raw"},
    },
    {
        "file": "fx-category.json",
        "entity": {"id": f"widget:{SCENARIO_CASE}", "type": "fx:Widget"},
        "attribute": "fx:category",
        "value": {
            "kind": "code",
            "value": "restricted",
            "codeSystem": "duly-fixture/widget-categories",
            "codeSystemVersion": "0.1.0",
        },
        "quote": "Assigned category: restricted",
        "confidence": {"score": 0.97, "method": "raw"},
    },
    {
        "file": "fx-inspector.json",
        "entity": {"id": f"widget:{SCENARIO_CASE}", "type": "fx:Widget"},
        "attribute": "fx:inspector",
        "value": {"kind": "string", "value": "Dana Okafor"},
        "quote": "Inspector of record: Dana Okafor, 41 Alder Row",
        "confidence": {"score": 0.99, "method": "raw"},
        # `sensitivity: pii` so the report renderer's redaction path has
        # something to redact. The quote is invented and names nobody; a
        # fixture that carried real personal data to test PII handling would
        # be the joke that writes itself.
        "sensitivity": "pii",
    },
]


def _rendition_text(lines: list[tuple[str, str]]) -> str:
    return "\n".join(text for _, text in lines) + "\n"


def _build_scenario() -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    root = ROOT / "scenario"
    (root / "documents").mkdir(parents=True, exist_ok=True)
    (root / "renditions").mkdir(parents=True, exist_ok=True)
    (root / "facts").mkdir(parents=True, exist_ok=True)

    pdf_path = root / "documents" / "widget-report.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter, invariant=1)
    c.setTitle("Widget Inspection Report FX-INSPECTION-0005")
    y = letter[1] - 72
    for style, text in DOC_LINES:
        if style == "":
            y -= 9
            continue
        c.setFont("Helvetica-Bold" if style == "title" else "Helvetica", 12)
        c.drawString(72, y, text)
        y -= 15
    c.showPage()
    c.save()

    rendition = _rendition_text(DOC_LINES)
    (root / "renditions" / "widget-report.txt").write_text(rendition, encoding="utf-8")

    document = SourceDocument.from_bytes(SCENARIO_DOC, pdf_path.read_bytes())

    # The targets file lives beside the corpus rather than inside `scenario/`,
    # because that is where it lives in a deployment: the demo indexes
    # `starters/tools/targets/*.json` by the `documentId` *field*, one shared
    # directory for every scenario, and the filename is a human convention
    # (`<scenario>-<document>.json`). `duly_demo/tests/demotest_helpers.py` maps
    # this directory onto that one.
    targets = {
        "documentId": SCENARIO_DOC,
        "caseId": f"case:fixture:{SCENARIO_CASE}",
        "schemaRef": dict(ONTOLOGY),
        "assertedAt": ASSERTED_AT,
        "runId": SCENARIO_RUN,
        "page": 1,
        "notes": [
            "Confidence scores in this file are scripted demo values (the stub "
            "adapter passes them through verbatim); they are not calibration output.",
            "fx:score is scripted below the pack's 0.80 floor so the scenario "
            "carries a live low_confidence abstention.",
        ],
        "facts": SCENARIO_TARGETS,
    }
    _dump(ROOT / "targets" / f"{SCENARIO_CASE}-widget-report.json", targets)

    # The committed facts are the adapter's output, not this file's. The stub
    # locates every quote by exact substring search and re-checks
    # `quote == rendition[start:end]` on each emission, so a hand-counted
    # offset — a fact that lies about its own evidence — is unrepresentable
    # here rather than merely discouraged.
    result = StubAdapter(rendition).extract(document, targets)
    if result.notes:
        # The stub's only note is "quote occurs more than once, using first
        # occurrence", which for authored fixture targets is an authoring bug:
        # the span would be correct and the *evidence* ambiguous.
        raise ValueError(f"ambiguous scenario targets: {result.notes}")
    facts = result.facts
    for target, fact in zip(SCENARIO_TARGETS, facts):
        _dump(root / "facts" / target["file"], fact)

    doc = {"id": document.document_id, "sha256": document.sha256}
    _dump(
        root / "scenario.json",
        {
            "id": SCENARIO_CASE,
            "title": "Widget inspection (fixture)",
            "domain": "fixture",
            "caseId": f"case:fixture:{SCENARIO_CASE}",
            "ontology": dict(ONTOLOGY),
            "demoExtractor": "stub",
            # Opt into the demo's review arc. The arc is content, not code:
            # a scenario names the attribute to script below the pack's floor
            # and the demo derives the rest (see duly_demo/app.py `_review_spec`).
            "reviewArc": {
                "attribute": "fx:score",
                "confidence": {"score": 0.55, "method": "platt"},
                "title": "Widget inspection — review arc (fixture)",
                "caseId": f"case:fixture:{SCENARIO_CASE}:review-demo",
                "defaultAsOf": "2026-06-01",
            },
            "documents": [
                {
                    "id": doc["id"],
                    "title": "Widget Inspection Report",
                    "pdf": "documents/widget-report.pdf",
                    "rendition": "renditions/widget-report.txt",
                    "sha256": doc["sha256"],
                }
            ],
            "facts": [f'facts/{t["file"]}' for t in SCENARIO_TARGETS],
            "rulePack": "fixtures/pack.yaml",
        },
    )
    print(
        f"{SCENARIO_CASE}  scenario: 1 document, {len(facts)} span-grounded facts "
        f"(extracted by {result.rendition.extractor} {result.rendition.extractor_version})"
    )


def _dump(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    pack = yaml.safe_load((ROOT / "pack.yaml").read_text())
    written = 0

    for spec in CASES:
        case_id = spec["id"]
        amount, score = spec["score"]
        facts = [
            _fact(case_id, "fx:score", {"kind": "decimal", "value": amount}, score),
            _fact(
                case_id,
                "fx:category",
                {
                    "kind": "code",
                    "value": spec["category"],
                    "codeSystem": "duly-fixture/widget-categories",
                    "codeSystemVersion": "0.1.0",
                },
                1.0,
            ),
        ]

        case_dir = ROOT / "cases" / case_id
        for fact in facts:
            _dump(case_dir / "facts" / f'{fact["attribute"].replace(":", "-")}.json', fact)

        (case_dir / "case.yaml").write_text(
            f"# {spec['note']}\n"
            f"id: {case_id}\n"
            f"pack: fixtures/pack.yaml\n"
            f"question: fx:permitted\n"
            f'asOfEffective: "{spec["effective"]}"\n'
            f'asOfKnowledge: "{KNOWLEDGE}"\n'
        )

        # fx-0004 is fx-0003 after review: the same below-floor fact, plus the
        # human correction that supersedes it. Built from fx-0003's facts so the
        # supersession chain is real rather than asserted.
        if case_id == "fx-0003":
            # The *post-correction projection*, which is what a store's `as_of`
            # returns and what `golden/cases/review-0001` commits: the
            # superseded machine fact is not in the set. Supersession is a
            # store-level projection, and `adjudicate` is handed a fact list
            # rather than a store — pass both and the kernel correctly reports
            # a live below-floor fact nobody had retired.
            corrected = [f for f in facts if f["attribute"] != "fx:score"] + [
                _correction(
                    "fx-0003",
                    facts[0]["id"],
                    {"kind": "decimal", "value": "12"},
                )
            ]
            arc_dir = ROOT / "cases" / "fx-0004"
            for fact in corrected:
                name = fact["attribute"].replace(":", "-")
                if fact["assertion"]["kind"] == "human":
                    name += "-corrected"
                _dump(arc_dir / "facts" / f"{name}.json", fact)
            (arc_dir / "case.yaml").write_text(
                "# fx-0003 after review: the correction supersedes the below-floor fact\n"
                "id: fx-0004\n"
                "pack: fixtures/pack.yaml\n"
                "question: fx:permitted\n"
                f'asOfEffective: "{spec["effective"]}"\n'
                f'asOfKnowledge: "{CORRECTED_AT}"\n'
            )
            arc = adjudicate(corrected, pack, spec["effective"], CORRECTED_AT, "fx:permitted")
            _dump(ROOT / "receipts" / "fx-0004.json", arc)

        receipt = adjudicate(facts, pack, spec["effective"], KNOWLEDGE, "fx:permitted")
        _dump(ROOT / "receipts" / f"{case_id}.json", receipt)
        written += 1
        print(
            f'{case_id}  permitted={str(receipt["decision"]["value"]["value"]):5} '
            f'abstentions={len(receipt["abstentions"])} '
            f'receipt {receipt["receiptSha256"][:12]}…'
        )

    _build_scenario()
    # Receipts, not `CASES` entries: fx-0004 is derived from fx-0003 rather
    # than declared, so counting the loop under-reports by one — and this
    # number is what the corpus-size pins in the toolkit suites are checked
    # against.
    receipts = len(list((ROOT / "receipts").glob("*.json")))
    print(f"wrote {written} declared cases, {receipts} receipts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
