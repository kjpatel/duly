#!/usr/bin/env python3
"""Generate the synthetic documents for the tila-rescission starter scenario.

Reuses the shared line-based PDF/rendition helpers from
starters/tools/make_documents.py (render via `build_document`), so the
rendition .txt genuinely corresponds to the PDF text and regeneration is
byte-stable (`invariant=1`).

Scenario: a refinance of the borrowers' principal dwelling consummated on
Friday, May 22, 2026. Under 12 CFR § 1026.23(a)(3)(i) the consumers may
rescind until midnight of the THIRD business day following the latest of
consummation, delivery of the notice of the right to rescind, and delivery
of all material disclosures — here all three occur on May 22, 2026. Using
the PRECISE business-day definition of 12 CFR § 1026.2(a)(6) (all calendar
days except Sundays and the legal public holidays specified in
5 U.S.C. 6103(a)):

    Sat May 23  business day 1   (Saturdays COUNT under the precise definition)
    Sun May 24  excluded         (Sunday)
    Mon May 25  excluded         (Memorial Day, 5 U.S.C. 6103(a) — last Monday
                                  in May; 2026 date verified by calendar)
    Tue May 26  business day 2
    Wed May 27  business day 3   -> rescission deadline: midnight of May 27
    Thu May 28  funds may be disbursed (12 CFR § 1026.23(c))

The notice document prints that deadline, exactly as the H-8 model form's
"final date to cancel" blank would. The extraction targets derive the
rescission-period window facts from the printed date; the rule pack
(rulepacks/tila-rescission-us-federal/pack.yaml) documents why the
business-day arithmetic itself lives outside the rule IR.

Usage (from the repo root):
    uv run python starters/tila-rescission/make_documents.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from make_documents import build_document  # noqa: E402  (shared helpers)

LOAN_ID = "RF-2026-3117"
CASE_ID = f"case:loan:{LOAN_ID}"

CANCEL_NOTICE = [
    ("title", "GRANITE STATE HOME LENDING, LLC"),
    ("title", "NOTICE OF RIGHT TO CANCEL"),
    ("", ""),
    ("body", f"Loan ID # {LOAN_ID}"),
    ("body", "Borrowers: Alex Morgan and Casey Morgan"),
    ("body", "Property: 41 Juniper Court, Concord, NH 03301"),
    ("body", "Date of Transaction (Consummation): May 22, 2026"),
    ("", ""),
    ("heading", "YOUR RIGHT TO CANCEL"),
    ("body", "You are entering into a transaction that will result in a mortgage, lien, or"),
    ("body", "security interest on or in your home. You have a legal right under federal law"),
    ("body", "(Truth in Lending Act, 12 CFR 1026.23) to cancel this transaction, without"),
    ("body", "cost, within THREE BUSINESS DAYS from whichever of the following events"),
    ("body", "occurs last:"),
    ("", ""),
    ("body", "  (1) the date of the transaction, which is May 22, 2026; or"),
    ("body", "  (2) the date you received your Truth in Lending disclosures; or"),
    ("body", "  (3) the date you received this notice of your right to cancel."),
    ("", ""),
    ("heading", "HOW TO CANCEL"),
    ("body", "If you decide to cancel this transaction, you may do so by notifying us in"),
    ("body", "writing at 200 Commercial Street, Suite 40, Manchester, NH 03101. If you"),
    ("body", "cancel by mail or telegram, you must send the notice no later than"),
    ("body", "MIDNIGHT of May 27, 2026 (or midnight of the third business day following"),
    ("body", "the latest of the three events listed above)."),
    ("", ""),
    ("body", "For this notice, \"business day\" means every calendar day except Sundays and"),
    ("body", "Federal holidays (12 CFR 1026.2(a)(6)). Saturday, May 23, 2026 counts as a"),
    ("body", "business day; Sunday, May 24 and the Memorial Day holiday on Monday, May 25"),
    ("body", "do not."),
    ("", ""),
    ("heading", "ACKNOWLEDGMENT OF RECEIPT"),
    ("body", "Each of the undersigned acknowledges receipt of two copies of this Notice of"),
    ("body", "Right to Cancel on May 22, 2026."),
    ("", ""),
    ("body", "Alex Morgan                                     Casey Morgan"),
]

SETTLEMENT_STATEMENT = [
    ("title", "BEACON TITLE & ESCROW, LLC"),
    ("title", "SETTLEMENT STATEMENT — REFINANCE"),
    ("", ""),
    ("body", "Settlement Agent File # BT-88214"),
    ("body", f"Loan ID # {LOAN_ID}"),
    ("body", "Lender (New Creditor): Granite State Home Lending, LLC"),
    ("body", "Payoff Lender (Existing First Lien): Meridian Savings Bank"),
    ("body", "Borrowers: Alex Morgan and Casey Morgan"),
    ("body", "Property: 41 Juniper Court, Concord, NH 03301"),
    ("body", "Occupancy: Property is the Borrowers' principal dwelling"),
    ("body", "Loan Purpose: Refinance"),
    ("", ""),
    ("heading", "DATES"),
    ("body", "Date of Consummation (Settlement): May 22, 2026"),
    ("body", "Closing Disclosure and all material TILA disclosures delivered: May 22, 2026"),
    ("body", "Rescission period ends: midnight of May 27, 2026"),
    ("body", "Scheduled Disbursement Date: May 28, 2026"),
    ("", ""),
    ("heading", "LOAN TERMS"),
    ("body", "New Loan Amount: $324,000        Loan Term: 30 years"),
    ("body", "Interest Rate: 5.875%            Product: Fixed Rate"),
    ("", ""),
    ("heading", "DISBURSEMENTS"),
    ("body", "Payoff of Meridian Savings Bank first lien: $301,462.18"),
    ("body", "Recording fees (Merrimack County): $186.00"),
    ("body", "Title and settlement charges: $2,340.00"),
    ("body", "Cash to Borrowers at disbursement: $18,904.55"),
    ("", ""),
    ("body", "Funds will not be disbursed before the rescission period has expired"),
    ("body", "(12 CFR 1026.23(c))."),
]


def main() -> None:
    notice = build_document(
        "tila-rescission",
        "cancel-notice",
        CANCEL_NOTICE,
        f"Notice of Right to Cancel {LOAN_ID}",
    )
    settlement = build_document(
        "tila-rescission",
        "settlement",
        SETTLEMENT_STATEMENT,
        f"Settlement Statement {LOAN_ID}",
    )

    manifest = {
        "id": "tila-rescission",
        "title": "TILA right of rescission: refinance funding timing",
        "caseId": CASE_ID,
        "ontology": {"ontology": "duly-starter-resc", "version": "0.1.0"},
        "documents": [
            {
                "id": f"doc:cancel-notice:{LOAN_ID}:2026-05-22",
                "title": "Notice of Right to Cancel",
                **notice,
            },
            {
                "id": f"doc:settlement:{LOAN_ID}:2026-05-22",
                "title": "Settlement Statement",
                **settlement,
            },
        ],
        "facts": [
            "facts/fact-notice-delivered.json",
            "facts/fact-notice-deadline.json",
            "facts/fact-rescission-period-in-force.json",
            "facts/fact-rescission-period-expired.json",
            "facts/fact-settlement-consummation.json",
            "facts/fact-settlement-disclosures-delivered.json",
            "facts/fact-settlement-principal-dwelling.json",
            "facts/fact-settlement-loan-purpose.json",
        ],
        "rulePack": "rulepacks/tila-rescission-us-federal/pack.yaml",
    }

    path = HERE / "scenario.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
