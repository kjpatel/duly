#!/usr/bin/env python3
"""Generate the synthetic documents for the county-recording starter scenario.

Reuses the shared helpers (render_pdf / rendition_text / build_document) from
starters/tools/make_documents.py — loaded by file path because both modules
are named make_documents.py — and merges this scenario's own scenario.json
(via write_manifest) with the actual SHA-256 of the generated PDF bytes.

The scenario: a Los Angeles County deed of trust package headed to the
recorder. Two documents —

  1. the first page of the deed of trust itself (grantor/grantee, APN, the
     documentary-transfer-tax block that grounds the SB 2 exemption); and
  2. the submitter's own pre-recording transmittal worksheet, which carries
     the measured layout facts (first-page top space, cover page yes/no).

HONESTY NOTE on the measurement: the "2.1 inches" top-space figure on the
transmittal is scripted narrative, like every value in these synthetic
documents — it is what the story's post-closing desk wrote down, not a
measurement of this PDF's actual geometry (the shared renderer draws all
pages with a fixed 1-inch margin). The below-floor confidence that makes
this scenario's review arc run is likewise scripted, in
starters/tools/targets/county-recording-transmittal.json, and is labeled
there too.

Usage (from the repo root):
    uv run python starters/county-recording/make_documents.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

STARTERS = Path(__file__).resolve().parent.parent
SCENARIO = "county-recording"

_spec = importlib.util.spec_from_file_location(
    "duly_shared_make_documents", STARTERS / "tools" / "make_documents.py"
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
build_document = _shared.build_document
write_manifest = _shared.write_manifest

# Line styles per the shared renderer: "title" | "heading" | "body" | "".
# The rendition text is exactly these lines joined with newlines, so every
# extraction quote below must appear verbatim (and exactly once) in one line.

DEED_OF_TRUST = [
    ("body", "RECORDING REQUESTED BY: Pacific Coast Title Company"),
    ("body", "WHEN RECORDED MAIL TO: Harborline Mortgage, LLC, 400 Spring Street, Los Angeles, CA 90013"),
    ("body", "Escrow No. PCT-48812        Title Order No. 55-104-221"),
    ("body", "APN: 5551-002-013"),
    ("body", "SPACE ABOVE THIS LINE RESERVED FOR RECORDER'S USE"),
    ("", ""),
    ("title", "DEED OF TRUST"),
    ("body", "(With Assignment of Rents)"),
    ("", ""),
    ("body", "Recording jurisdiction: County of Los Angeles, State of California"),
    ("body", "DOCUMENTARY TRANSFER TAX: NONE — this Deed of Trust secures a debt and is"),
    ("body", "recorded concurrently with a Grant Deed on which documentary transfer tax is paid (R&T 11911)."),
    ("", ""),
    ("body", "This Deed of Trust, made July 24, 2026, between"),
    ("body", "  Trustor:      Avery L. Nakamura and Sam D. Nakamura, as joint tenants"),
    ("body", "  Trustee:      Pacific Coast Title Company, a California corporation"),
    ("body", "  Beneficiary:  Harborline Mortgage, LLC, a Delaware limited liability company"),
    ("", ""),
    ("body", "covers that real property in the City of Torrance, County of Los Angeles, described as:"),
    ("body", "  Lot 14 of Tract No. 30712, as per map recorded in Book 741, Pages 18-19 of Maps,"),
    ("body", "  in the office of the County Recorder of said county."),
    ("", ""),
    ("body", "Trustor irrevocably grants, transfers, and assigns to Trustee, in trust, with power"),
    ("body", "of sale, the above-described property, to secure payment of a promissory note of even"),
    ("body", "date herewith in the principal sum of $612,000.00, payable to Beneficiary or order."),
]

TRANSMITTAL_SHEET = [
    ("title", "HARBORLINE MORTGAGE, LLC — RECORDING TRANSMITTAL"),
    ("body", "(Pre-recording quality-control worksheet. This transmittal is NOT a"),
    ("body", "Gov. Code 27361.6 cover page and will not be submitted for recording.)"),
    ("", ""),
    ("body", "Package: DOT-2026-081512"),
    ("body", "Instrument: Deed of Trust (Nakamura), executed July 24, 2026"),
    ("body", "Destination: Los Angeles County Registrar-Recorder/County Clerk"),
    ("body", "Submission channel: electronic recording (Level 2)"),
    ("", ""),
    ("heading", "PRE-RECORDING FORMAT CHECKS"),
    ("body", "First-page top recording space (measured): 2.1 inches"),
    ("body", "Side margins, left/right (measured): 0.55 inches"),
    ("body", "Gov. Code 27361.6 cover page attached: NO"),
    ("body", "Concurrent documents: Grant Deed (documentary transfer tax declared and paid)"),
    ("", ""),
    ("body", "Prepared by: R. Okafor, post-closing desk, July 27, 2026"),
]

DEED_DOC_ID = "doc:deed-of-trust:DOT-2026-081512:2026-07-24"
TRANSMITTAL_DOC_ID = "doc:transmittal:DOT-2026-081512:2026-07-27"


def main() -> None:
    deed = build_document(
        SCENARIO, "deed-of-trust", DEED_OF_TRUST, "Deed of Trust DOT-2026-081512 (first page)"
    )
    transmittal = build_document(
        SCENARIO, "transmittal-sheet", TRANSMITTAL_SHEET, "Recording Transmittal DOT-2026-081512"
    )

    manifest = {
        "id": "county-recording",
        "title": "LA County deed of trust — recording readiness",
        "caseId": "case:recording:DOT-2026-081512",
        "ontology": {"ontology": "duly-mortgage-closing", "version": "0.1.0"},
        "documents": [
            {
                "id": DEED_DOC_ID,
                "title": "Deed of Trust (first page)",
                **deed,
            },
            {
                "id": TRANSMITTAL_DOC_ID,
                "title": "Recording Transmittal",
                **transmittal,
            },
        ],
        "facts": [
            "facts/fact-deed-instrument-type.json",
            "facts/fact-deed-state.json",
            "facts/fact-deed-apn.json",
            "facts/fact-deed-concurrent-taxed-transfer.json",
            "facts/fact-transmittal-top-space.json",
            "facts/fact-transmittal-cover-page.json",
        ],
        "rulePack": "rulepacks/county-recording-us/pack.yaml",
    }

    # Merged, not replaced: this scenario's `demoExtractor: stub` pin lives
    # only in the manifest, and a plain write reverts it (write_manifest).
    write_manifest(STARTERS / SCENARIO / "scenario.json", manifest)


if __name__ == "__main__":
    main()
