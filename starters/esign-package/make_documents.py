#!/usr/bin/env python3
"""Generate the synthetic documents for the esign-package starter scenario.

Reuses the shared helpers (render_pdf / rendition_text / build_document) from
starters/tools/make_documents.py without modifying that script: the PDF is
drawn from a single list of source lines and the rendition .txt is the same
lines joined with newlines, so the rendition genuinely corresponds to the PDF
text; PDFs are generated with invariant=1 so regeneration is byte-stable.

Also (re)writes starters/esign-package/scenario.json with the actual SHA-256
of the generated PDF bytes.

Usage (from the repo root):
    uv run python starters/esign-package/make_documents.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent
STARTERS = SCENARIO_DIR.parent
sys.path.insert(0, str(STARTERS / "tools"))

from make_documents import build_document  # noqa: E402  (shared helpers)

SCENARIO = "esign-package"
CASE_ID = "case:closing-package:CP-2026-0847"

CLOSING_MANIFEST = [
    ("title", "COBALT TITLE & SETTLEMENT — CLOSING PACKAGE MANIFEST"),
    ("", ""),
    ("body", "Closing Package: CP-2026-0847"),
    ("body", "Loan Number: BL-2026-11402"),
    ("body", "Borrower: Alexis Nguyen"),
    ("body", "Property: 2214 Saguaro Vista Drive, Phoenix, AZ 85018"),
    ("body", "Lender: Bluestone Home Lending, LLC"),
    ("body", "Scheduled Closing Date: 07/17/2026"),
    ("", ""),
    ("heading", "ELECTRONIC SIGNING STATUS"),
    ("body", "eSign Consent Status: OBTAINED (07/10/2026, borrower portal)"),
    ("body", "Consent covers electronic records and disclosures under 15 U.S.C. § 7001(c)."),
    ("body", "MERS eRegistry Registration: CONFIRMED (MIN 1000990-0726000847-5)"),
    ("body", "Authoritative copy custody: Bluestone eVault (vault ID EV-2214-0847)"),
    ("", ""),
    ("heading", "DOCUMENTS IN THIS PACKAGE"),
    ("body", "1. Promissory Note (eNote) — routed for signing by this manifest"),
    ("body", "2. Deed of Trust — routed separately (county recording workflow)"),
    ("body", "3. Closing Disclosure — routed separately"),
    ("body", "4. Notice of Right to Cancel — routed separately"),
    ("", ""),
    ("body", "Document under review in this package: Promissory Note"),
    ("body", "Prepared by: Cobalt Title & Settlement, 400 N Central Ave, Phoenix, AZ 85004"),
]

PROMISSORY_NOTE = [
    ("title", "PROMISSORY NOTE"),
    ("", ""),
    ("body", "July 17, 2026                                   Phoenix, Arizona"),
    ("body", "Property Address: 2214 Saguaro Vista Drive, Phoenix, AZ 85018"),
    ("", ""),
    ("heading", "1. BORROWER'S PROMISE TO PAY"),
    ("body", "In return for a loan that I have received, I promise to pay U.S. $412,500.00"),
    ("body", "(this amount is called \"Principal\"), plus interest, to the order of the Lender."),
    ("body", "The Lender is Bluestone Home Lending, LLC."),
    ("", ""),
    ("heading", "2. INTEREST"),
    ("body", "Interest will be charged on unpaid principal until the full amount of Principal"),
    ("body", "has been paid. I will pay interest at a yearly rate of 6.625%."),
    ("", ""),
    ("heading", "3. PAYMENTS"),
    ("body", "I will pay principal and interest by making a payment every month on the first"),
    ("body", "day of each month, beginning September 1, 2026, until I have paid all of the"),
    ("body", "principal and interest and any other charges described in this Note."),
    ("", ""),
    ("heading", "11. ELECTRONIC NOTE; TRANSFERABLE RECORD"),
    ("body", "This Note is a transferable record within the meaning of 15 U.S.C. § 7021. The"),
    ("body", "authoritative copy of this Note is the copy identified as such by the registry"),
    ("body", "operated by MERSCORP Holdings, Inc. (the MERS eRegistry) and held in the"),
    ("body", "Lender's designated electronic vault."),
    ("", ""),
    ("body", "[FIRST PAGE ONLY — SIGNATURE PAGE FOLLOWS IN THE EXECUTION COPY]"),
]


def main() -> None:
    for sub in ("documents", "renditions", "facts"):
        (SCENARIO_DIR / sub).mkdir(exist_ok=True)

    manifest_doc = build_document(
        SCENARIO, "closing-manifest", CLOSING_MANIFEST,
        "Closing Package Manifest CP-2026-0847",
    )
    note_doc = build_document(
        SCENARIO, "promissory-note", PROMISSORY_NOTE,
        "Promissory Note BL-2026-11402 (first page)",
    )

    manifest = {
        "id": SCENARIO,
        "title": "eSign routing: closing-package promissory note as a registered eNote",
        "caseId": CASE_ID,
        "ontology": {"ontology": "duly-starter-esign", "version": "0.1.0"},
        "documents": [
            {
                "id": "doc:closing-manifest:CP-2026-0847:2026-07-12",
                "title": "Closing Package Manifest",
                **manifest_doc,
            },
            {
                "id": "doc:promissory-note:CP-2026-0847:2026-07-12",
                "title": "Promissory Note (first page)",
                **note_doc,
            },
        ],
        "facts": [
            "facts/fact-note-document-type.json",
            "facts/fact-manifest-esign-consent.json",
            "facts/fact-manifest-enote-registered.json",
        ],
        "rulePack": "rulepacks/esign-closing-package/pack.yaml",
    }

    path = SCENARIO_DIR / "scenario.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(STARTERS.parent)}")


if __name__ == "__main__":
    main()
