#!/usr/bin/env python3
"""Generate the synthetic demo documents for the starter scenarios.

For each document this script holds a single list of source lines. The PDF is
drawn from those lines and the rendition .txt is the same lines joined with
newlines, so the rendition genuinely corresponds to the PDF text. PDFs are
generated with `invariant=1` so regeneration is byte-stable.

It also (re)writes each scenario's scenario.json manifest with the actual
SHA-256 of the generated PDF bytes — by *merging* into the committed manifest
rather than replacing it; see `write_manifest`, which every starter's
generator goes through.

Usage (from the repo root):
    uv run python starters/tools/make_documents.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

STARTERS = Path(__file__).resolve().parent.parent

PAGE_W, PAGE_H = letter
MARGIN = 72
LEADING = 16

# Each line is (style, text). Styles control PDF typography only; the
# rendition is always the raw text of every line, in order.
#   "title"   - bold, larger, centered
#   "heading" - bold
#   "body"    - regular
#   ""        - blank line (vertical space in the PDF, empty line in the txt)

DEC_PAGE = [
    ("title", "HOMESTEAD MUTUAL INSURANCE COMPANY — HOMEOWNERS POLICY DECLARATIONS"),
    ("", ""),
    ("body", "Policy Number: HO-77401-NY"),
    ("body", "Named Insured: Jordan Rivera"),
    ("body", "Mailing Address: 148 Maple Crescent, Albany, NY 12203"),
    ("body", "Insured Location: Albany, New York"),
    ("", ""),
    ("heading", "POLICY PERIOD: 09/01/2025 to 09/01/2026"),
    ("body", "12:01 A.M. Standard Time at the insured location."),
    ("", ""),
    ("heading", "COVERAGES AND LIMITS OF LIABILITY"),
    ("body", "Coverage A — Dwelling                              $420,000"),
    ("body", "Coverage B — Other Structures                       $42,000"),
    ("body", "Coverage C — Personal Property                     $210,000"),
    ("body", "Coverage D — Loss of Use                            $84,000"),
    ("body", "Coverage E — Personal Liability                    $300,000"),
    ("body", "Coverage F — Medical Payments to Others              $5,000"),
    ("", ""),
    ("body", "Deductible: $2,500 (All Perils)"),
    ("body", "Total Annual Premium: $1,684.00"),
    ("", ""),
    ("body", "Forms and Endorsements: HO 00 03 (03/22), HO 04 96 (03/22), NY 01 15 (09/24)"),
    ("body", "Agent: Meridian Insurance Services, 55 State Street, Albany, NY 12207"),
    ("", ""),
    ("body", "THIS DECLARATIONS PAGE, TOGETHER WITH THE POLICY FORM AND ENDORSEMENTS,"),
    ("body", "COMPLETES THE ABOVE-NUMBERED POLICY."),
]

NONRENEWAL_NOTICE = [
    ("title", "HOMESTEAD MUTUAL INSURANCE COMPANY"),
    ("title", "NOTICE OF NONRENEWAL"),
    ("", ""),
    ("body", "Date of Mailing: July 25, 2026"),
    ("body", "Policy Number: HO-77401-NY"),
    ("body", "Named Insured: Jordan Rivera"),
    ("body", "Insured Location: Albany, New York"),
    ("", ""),
    ("body", "Dear Jordan Rivera:"),
    ("", ""),
    ("body", "In accordance with the terms and conditions of the above-referenced"),
    ("body", "homeowners policy, HOMESTEAD MUTUAL INSURANCE COMPANY hereby provides"),
    ("body", "notice that your policy will not be renewed at expiration of the current"),
    ("body", "policy period. Coverage under this policy will end on the expiration date"),
    ("body", "shown on your declarations page, and no renewal policy will be issued."),
    ("", ""),
    ("body", "Reason for nonrenewal: underwriting risk re-evaluation."),
    ("", ""),
    ("body", "You may be eligible for coverage through another insurer or through the"),
    ("body", "New York Property Insurance Underwriting Association. If you have any"),
    ("body", "questions about this notice, please contact your agent, Meridian Insurance"),
    ("body", "Services, at (518) 555-0147."),
    ("", ""),
    ("body", "Sincerely,"),
    ("body", "Dana Whitfield"),
    ("body", "Underwriting Manager, Homestead Mutual Insurance Company"),
]

LOAN_ESTIMATE = [
    ("title", "LOAN ESTIMATE"),
    ("", ""),
    ("body", "Date Issued: 02/10/2026"),
    ("body", "Loan ID # L-2026-0142"),
    ("body", "Applicants: Priya Shah and Marcus Shah"),
    ("body", "Property: 902 Birchwood Lane, Rochester, NY 14618"),
    ("body", "Sale Price: $310,000"),
    ("", ""),
    ("heading", "Loan Terms"),
    ("body", "Loan Amount: $248,000        Loan Term: 30 years"),
    ("body", "Interest Rate: 6.375%        Product: Fixed Rate"),
    ("body", "Loan Type: Conventional      Purpose: Purchase"),
    ("", ""),
    ("heading", "Closing Cost Details — Other Costs"),
    ("", ""),
    ("heading", "Section E: Taxes and Other Government Fees"),
    ("body", "Recording Fees $85.00"),
    ("body", "Transfer Taxes $1,200.00"),
    ("", ""),
    ("heading", "Section F: Prepaids"),
    ("body", "Homeowner's Insurance Premium (12 mo.) $1,150.00"),
    ("body", "Prepaid Interest ($43.32 per day for 15 days) $649.80"),
    ("", ""),
    ("body", "Estimated Closing Costs: $8,412.00    Estimated Cash to Close: $71,204.00"),
]

CLOSING_DISCLOSURE = [
    ("title", "CLOSING DISCLOSURE"),
    ("", ""),
    ("body", "Closing Date: 03/15/2026"),
    ("body", "Loan ID # L-2026-0142"),
    ("body", "Borrowers: Priya Shah and Marcus Shah"),
    ("body", "Property: 902 Birchwood Lane, Rochester, NY 14618"),
    ("body", "Sale Price: $310,000"),
    ("", ""),
    ("heading", "Loan Terms"),
    ("body", "Loan Amount: $248,000        Loan Term: 30 years"),
    ("body", "Interest Rate: 6.375%        Product: Fixed Rate"),
    ("body", "Loan Type: Conventional      Purpose: Purchase"),
    ("", ""),
    ("heading", "Closing Cost Details — Other Costs"),
    ("", ""),
    ("heading", "Section E: Taxes and Other Government Fees"),
    ("body", "Recording Fees (to County) $85.00"),
    ("body", "Transfer Taxes (to County) $1,450.00"),
    ("", ""),
    ("heading", "Section F: Prepaids"),
    ("body", "Homeowner's Insurance Premium (12 mo.) $1,150.00"),
    ("body", "Prepaid Interest ($43.32 per day for 12 days) $519.84"),
    ("", ""),
    ("body", "Final Closing Costs: $8,790.00    Cash to Close: $71,582.00"),
]

FONTS = {
    "title": ("Helvetica-Bold", 12),
    "heading": ("Helvetica-Bold", 10),
    "body": ("Helvetica", 10),
}


def render_pdf(lines: list[tuple[str, str]], out_path: Path, doc_title: str) -> None:
    c = canvas.Canvas(str(out_path), pagesize=letter, invariant=1)
    c.setTitle(doc_title)
    y = PAGE_H - MARGIN
    for style, text in lines:
        if style == "":
            y -= LEADING * 0.6
            continue
        font, size = FONTS[style]
        c.setFont(font, size)
        if style == "title":
            c.drawCentredString(PAGE_W / 2, y, text)
        else:
            c.drawString(MARGIN, y, text)
        y -= LEADING
    c.showPage()
    c.save()


def rendition_text(lines: list[tuple[str, str]]) -> str:
    return "\n".join(text for _, text in lines) + "\n"


def build_document(scenario: str, doc_id_stem: str, lines, doc_title: str) -> dict:
    pdf_path = STARTERS / scenario / "documents" / f"{doc_id_stem}.pdf"
    txt_path = STARTERS / scenario / "renditions" / f"{doc_id_stem}.txt"
    render_pdf(lines, pdf_path, doc_title)
    txt_path.write_text(rendition_text(lines), encoding="utf-8")
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    print(f"wrote {pdf_path.relative_to(STARTERS.parent)}  sha256={sha[:16]}…")
    print(f"wrote {txt_path.relative_to(STARTERS.parent)}")
    return {
        "pdf": f"documents/{doc_id_stem}.pdf",
        "rendition": f"renditions/{doc_id_stem}.txt",
        "sha256": sha,
    }


# ---------------------------------------------------------------------------
# The manifest: merged, never replaced
# ---------------------------------------------------------------------------


def merge_manifest(existing: dict, generated: dict) -> dict:
    """`generated` laid over `existing`, key by key, order from `existing`.

    The rule is one line and applies at both levels: **a key the generator
    emits is the generator's; a key it does not emit is yours.** Edit a
    generator-owned value in the script, not in the JSON — the next run wins.
    Everything else survives untouched, including keys added to a manifest
    long after its generator was written.

    Three such keys exist today, and every one of them was silently reverted
    by a re-run before this function existed: `domain` (all six scenarios),
    `demoExtractor` (county-recording — the stub pin that keeps its scripted
    below-floor confidence from being overwritten by a live Docling
    measurement), and the whole `reviewArc` block (notice-ny). The loss was
    caught, but by a demo test that reads as unrelated to the PDF someone was
    regenerating.

    `documents` is merged entry by entry, matched on `id`, so a hand-added key
    on one document survives the same way; membership and order come from the
    generated list, because the generator is what rendered the files.
    """
    merged = dict(existing)
    merged.update(generated)
    if "documents" in generated:
        merged["documents"] = _merge_documents(
            existing.get("documents", []), generated["documents"]
        )
    return merged


def _merge_documents(existing: list, generated: list) -> list:
    by_id = {d["id"]: d for d in existing if isinstance(d, dict) and "id" in d}
    out = []
    for doc in generated:
        entry = dict(by_id.get(doc.get("id"), {}))
        entry.update(doc)
        out.append(entry)
    return out


def write_manifest(path: Path, generated: dict) -> None:
    """Merge `generated` into the scenario.json at `path` and write it back.

    Prints what it preserved, so a run that quietly kept a hand-maintained
    key says so, and warns about any `facts` entry that names a file which is
    not there — the other half of the same drift, running the other way: the
    tila-rescission generator's literal went on naming two rescission-period
    facts after the pack stopped computing the deadline from them and they
    were deleted from the manifest and the disk. Only a re-run would have put
    them back.
    """
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    manifest = merge_manifest(existing, generated)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    try:
        shown = path.relative_to(STARTERS.parent)
    except ValueError:  # a scenario tree outside this one (tests copy it)
        shown = path
    preserved = sorted(set(existing) - set(generated))
    note = f"  (preserved {', '.join(preserved)})" if preserved else ""
    print(f"wrote {shown}{note}")

    missing = [f for f in manifest.get("facts", ()) if not (path.parent / f).is_file()]
    if missing:
        print(
            f"warning: {shown} names {len(missing)} fact file(s) that do not exist: "
            f"{', '.join(missing)}",
            file=sys.stderr,
        )


def main() -> None:
    dec = build_document(
        "notice-ny", "dec-page", DEC_PAGE, "Homeowners Policy Declarations HO-77401-NY"
    )
    notice = build_document(
        "notice-ny", "nonrenewal-notice", NONRENEWAL_NOTICE, "Notice of Nonrenewal HO-77401-NY"
    )
    le = build_document(
        "trid", "loan-estimate", LOAN_ESTIMATE, "Loan Estimate L-2026-0142"
    )
    cd = build_document(
        "trid", "closing-disclosure", CLOSING_DISCLOSURE, "Closing Disclosure L-2026-0142"
    )

    notice_manifest = {
        "id": "notice-ny",
        "title": "New York homeowners nonrenewal notice timing",
        "caseId": "case:policy:HO-77401-NY",
        "ontology": {"ontology": "duly-starter-notice", "version": "0.1.0"},
        "documents": [
            {
                "id": "doc:dec-page:HO-77401-NY:2025-09-01",
                "title": "Homeowners Policy Declarations",
                **dec,
            },
            {
                "id": "doc:nonrenewal-notice:HO-77401-NY:2026-07-25",
                "title": "Notice of Nonrenewal",
                **notice,
            },
        ],
        "facts": [
            "facts/fact-decpage-expiration.json",
            "facts/fact-decpage-state.json",
            "facts/fact-notice-mailed.json",
            "facts/fact-notice-type.json",
        ],
        "rulePack": "rulepacks/termination-notice-us-states/pack.yaml",
    }

    trid_manifest = {
        "id": "trid",
        "title": "TRID transfer-tax tolerance between Loan Estimate and Closing Disclosure",
        "caseId": "case:loan:L-2026-0142",
        "ontology": {"ontology": "duly-mortgage-closing", "version": "0.1.0"},
        "documents": [
            {
                "id": "doc:loan-estimate:L-2026-0142:2026-02-10",
                "title": "Loan Estimate",
                **le,
            },
            {
                "id": "doc:closing-disclosure:L-2026-0142:2026-03-15",
                "title": "Closing Disclosure",
                **cd,
            },
        ],
        "facts": [
            "facts/fact-le-transfer-tax-baseline.json",
            "facts/fact-cd-transfer-tax-actual.json",
            "facts/fact-cd-fee-type.json",
        ],
        "rulePack": "rulepacks/trid-fee-tolerance-us-federal/pack.yaml",
    }

    for scenario, manifest in (("notice-ny", notice_manifest), ("trid", trid_manifest)):
        write_manifest(STARTERS / scenario / "scenario.json", manifest)


if __name__ == "__main__":
    main()
