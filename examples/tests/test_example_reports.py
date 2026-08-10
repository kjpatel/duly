"""What the audit report *says* about the NY notice and TRID starters.

The example content's own tests (see `exampletest_helpers`): they run while
`examples/` exists, they are deleted with it, and CI runs them as
`uv run pytest examples/tests -q`.

Extracted from `kernel/tests/test_report.py`, which keeps every claim about
the *renderer* — determinism, block structure, PII redaction, defeat
narration, money rendering — asserted against the fixture corpus. What moved
here is the part whose subject is the teaching content: the statutory
citation the NY starter quotes, the cure amount the TRID pack computes, and a
second determinism run over a real multi-fee starter, because that pack and
those documents are what an adopter actually downloads and renders.

The kernel suite's `conftest.py` is not importable from here, so the two
fixtures below carry their own loader rather than borrowing one.
"""

from __future__ import annotations

import json

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.ir import load_pack
from duly_kernel.report import render_report_markdown, render_report_pdf

from exampletest_helpers import RULEPACKS, STARTERS

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
    facts = _load_facts(STARTERS / "notice-ny" / "facts")
    assert facts, "the notice-ny starter ships no facts"
    pack = load_pack(RULEPACKS / "termination-notice-us-states" / "pack.yaml")
    receipt = adjudicate(
        facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "nc:noticeCompliant"
    )
    return receipt, facts, pack


@pytest.fixture(scope="module")
def trid() -> tuple[dict, list[dict], dict]:
    facts = _load_facts(STARTERS / "trid" / "facts")
    assert facts, "the trid starter ships no facts"
    pack = load_pack(RULEPACKS / "trid-fee-tolerance-us-federal" / "pack.yaml")
    receipt = adjudicate(
        facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "trid:toleranceCureAmount"
    )
    return receipt, facts, pack


def test_trid_pdf_byte_identical(trid):
    """The renderer's second shape — a money decision over a multi-fee starter.

    The toolkit's determinism claim is carried on the fixture corpus by
    `kernel/tests/test_report.py`; the reason to render *this* one twice is
    that it is the document an adopter downloads.
    """
    receipt, facts, pack = trid
    assert render_report_pdf(receipt, facts, pack) == render_report_pdf(
        receipt, facts, pack
    )


def test_ny_citation_quote_defeat_and_verdict(ny):
    """Every string here is a claim about the NY non-renewal starter and the
    termination-notice pack — the statutory citation, the quote the extractor
    grounded, that pack's own rule ids."""
    receipt, facts, pack = ny
    md = render_report_markdown(receipt, facts, pack)
    assert "N.Y. Ins. Law § 3425(d)(1)" in md
    assert "Date of Mailing: July 25, 2026" in md
    # The exception rule's defeat of the default presumption is narrated.
    assert "NC-DEF-00" in md
    assert "overrode NC-DEF-00" in md
    assert "Not compliant" in md


def test_trid_cure_amount_and_citation(trid):
    """The cure amount and the CFR citation are facts about the TRID pack, not
    about the renderer. Money rendering itself is asserted on the fixture
    pack's `fx:assessedFee` decision in the kernel suite."""
    receipt, facts, pack = trid
    md = render_report_markdown(receipt, facts, pack)
    assert "250.00" in md
    assert "12 CFR 1026.19(e)(3)(i)" in md
