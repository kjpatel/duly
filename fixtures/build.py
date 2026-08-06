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

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "kernel"))
sys.path.insert(0, str(REPO / "core"))

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
# So one scenario, built the way `starters/tools/make_documents.py` builds the
# teaching ones: the rendition is the join of the document's lines, spans are
# computed from that text rather than typed by hand, and the builder asserts
# each quote equals the slice it claims. A hand-counted offset is a fact that
# lies about its own evidence.

DOC_LINES = [
    ("title", "WIDGET INSPECTION REPORT"),
    ("", ""),
    ("label", "Report reference: FX-INSPECTION-0005"),
    ("label", "Inspected under: fixture regime (fictional)"),
    ("", ""),
    ("body", "Measured score: 12"),
    ("body", "Assigned category: restricted"),
    ("", ""),
    ("body", "This document is a fixture. It describes nothing real."),
]

SCENARIO_CASE = "fx-0005"


def _rendition_text(lines: list[tuple[str, str]]) -> str:
    return "\n".join(text for _, text in lines) + "\n"


def _span(text: str, quote: str) -> dict:
    """The span of `quote` in `text`, found rather than asserted."""
    start = text.index(quote)
    if text.count(quote) != 1:
        raise ValueError(f"quote is not unique in the rendition: {quote!r}")
    return {"start": start, "end": start + len(quote)}


def _grounded_fact(
    attribute: str, value: dict, quote: str, score: float, doc: dict, rendition: str
) -> dict:
    return seal_fact(
        {
            "caseId": f"case:fixture:{SCENARIO_CASE}",
            "entity": {"id": f"widget:{SCENARIO_CASE}", "type": "fx:Widget"},
            "attribute": attribute,
            "value": value,
            "grounding": {
                "kind": "document",
                "documentId": doc["id"],
                "documentSha256": doc["sha256"],
                "renditionId": doc["renditionId"],
                "locator": {"kind": "charSpan", **_span(rendition, quote)},
                "quote": quote,
            },
            "assertion": {"kind": "machine", "at": ASSERTED_AT, "extractor": EXTRACTOR},
            "confidence": {"score": score, "method": "raw"},
            "recordedAt": ASSERTED_AT,
            "status": "asserted",
            "schemaRef": dict(ONTOLOGY),
        }
    )


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

    doc = {
        "id": "doc:widget-report:FX-INSPECTION-0005",
        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "renditionId": "rendition:widget-report:0.1.0",
    }

    facts = [
        # Below the pack's 0.80 floor, so the scenario carries a live
        # abstention the demo's review arc has something to resolve.
        _grounded_fact(
            "fx:score", {"kind": "decimal", "value": "12"},
            "Measured score: 12", 0.62, doc, rendition,
        ),
        _grounded_fact(
            "fx:category",
            {
                "kind": "code",
                "value": "restricted",
                "codeSystem": "duly-fixture/widget-categories",
                "codeSystemVersion": "0.1.0",
            },
            "Assigned category: restricted", 0.97, doc, rendition,
        ),
    ]
    for fact in facts:
        _dump(root / "facts" / f'{fact["attribute"].replace(":", "-")}.json', fact)

    _dump(
        root / "scenario.json",
        {
            "id": SCENARIO_CASE,
            "title": "Widget inspection (fixture)",
            "domain": "fixture",
            "caseId": f"case:fixture:{SCENARIO_CASE}",
            "ontology": dict(ONTOLOGY),
            "demoExtractor": "stub",
            "documents": [
                {
                    "id": doc["id"],
                    "title": "Widget Inspection Report",
                    "pdf": "documents/widget-report.pdf",
                    "rendition": "renditions/widget-report.txt",
                    "sha256": doc["sha256"],
                }
            ],
            "facts": [f'facts/{f["attribute"].replace(":", "-")}.json' for f in facts],
            "rulePack": "fixtures/pack.yaml",
        },
    )
    print(f"{SCENARIO_CASE}  scenario: 1 document, {len(facts)} span-grounded facts")


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
    print(f"wrote {written} fixture cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
