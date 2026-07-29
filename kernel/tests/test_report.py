"""Audit-report renderer tests (kernel/duly_kernel/report.py).

Renders reports over the real starter scenarios (starters/*/facts against
rulepacks/*/pack.yaml) and asserts byte-determinism, content, and PII
redaction.
"""

import copy
import json

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.ir import load_pack
from duly_kernel.report import (
    PII_REDACTION,
    render_report_markdown,
    render_report_pdf,
)

from conftest import REPO_ROOT

AS_OF_EFFECTIVE = "2026-07-25"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"


def _load_facts(directory) -> list[dict]:
    facts = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" not in doc:
            facts.append(doc)
    return facts


@pytest.fixture(scope="module")
def ny() -> tuple[dict, list[dict], dict]:
    facts = _load_facts(REPO_ROOT / "starters" / "notice-ny" / "facts")
    pack = load_pack(
        REPO_ROOT / "rulepacks" / "termination-notice-us-states" / "pack.yaml"
    )
    receipt = adjudicate(
        facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "nc:noticeCompliant"
    )
    return receipt, facts, pack


@pytest.fixture(scope="module")
def trid() -> tuple[dict, list[dict], dict]:
    facts = _load_facts(REPO_ROOT / "starters" / "trid" / "facts")
    pack = load_pack(
        REPO_ROOT / "rulepacks" / "trid-fee-tolerance-us-federal" / "pack.yaml"
    )
    receipt = adjudicate(
        facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "trid:toleranceCureAmount"
    )
    return receipt, facts, pack


class TestDeterminism:
    def test_markdown_byte_identical(self, ny):
        receipt, facts, pack = ny
        a = render_report_markdown(receipt, facts, pack).encode("utf-8")
        b = render_report_markdown(receipt, facts, pack).encode("utf-8")
        assert a == b

    def test_pdf_byte_identical(self, ny):
        receipt, facts, pack = ny
        a = render_report_pdf(receipt, facts, pack)
        b = render_report_pdf(receipt, facts, pack)
        assert a == b

    def test_trid_pdf_byte_identical(self, trid):
        receipt, facts, pack = trid
        assert render_report_pdf(receipt, facts, pack) == render_report_pdf(
            receipt, facts, pack
        )


class TestNyMarkdownContent:
    def test_citation_quote_defeat_and_verdict(self, ny):
        receipt, facts, pack = ny
        md = render_report_markdown(receipt, facts, pack)
        assert "N.Y. Ins. Law § 3425(d)(1)" in md
        assert "Date of Mailing: July 25, 2026" in md
        # The exception rule's defeat of the default presumption is narrated.
        assert "NC-DEF-00" in md
        assert "overrode NC-DEF-00" in md
        assert "Not compliant" in md

    def test_pack_none_still_renders(self, ny):
        receipt, facts, _pack = ny
        md = render_report_markdown(receipt, facts, None)
        # Without the pack, the question falls back to the attribute.
        assert "nc:noticeCompliant" in md
        assert "Not compliant" in md


class TestTridMarkdownContent:
    def test_cure_amount_and_citation(self, trid):
        receipt, facts, pack = trid
        md = render_report_markdown(receipt, facts, pack)
        assert "250.00" in md
        assert "12 CFR 1026.19(e)(3)(i)" in md


class TestPdfShape:
    def test_pdf_header_and_size(self, ny):
        receipt, facts, pack = ny
        pdf = render_report_pdf(receipt, facts, pack)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 2048


class TestPiiRedaction:
    def test_pii_quote_redacted_in_markdown(self, ny):
        receipt, facts, pack = ny
        redacted_facts = copy.deepcopy(facts)
        target_quote = "Date of Mailing: July 25, 2026"
        marked = 0
        for fact in redacted_facts:
            if fact.get("grounding", {}).get("quote") == target_quote:
                fact["sensitivity"] = "pii"
                marked += 1
        assert marked == 1

        md = render_report_markdown(receipt, redacted_facts, pack)
        assert target_quote not in md
        assert PII_REDACTION in md
        # The document reference and hash survive redaction.
        mailed = next(
            f for f in redacted_facts
            if f.get("grounding", {}).get("quote") == target_quote
        )
        assert mailed["grounding"]["documentId"] in md
        assert mailed["contentHash"] in md
