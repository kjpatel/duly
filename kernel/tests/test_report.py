"""Audit-report renderer tests (kernel/duly_kernel/report.py).

Toolkit behaviour is asserted against the fixture corpus (`fixtures/`): the
committed fx-0001 case and its receipt, and the fixture scenario's three
document-grounded facts. That is deliberate — the renderer is toolkit, so a
suite that proved it worked only against `starters/`+`rulepacks/` would stop
being collected the day that teaching content moves under `examples/`, which
reads exactly like success (fixtures/README.md).

Three tests below keep their teaching-content subject and say so: what the NY
notice and TRID reports *say* is a claim about those packs, and deleting them
should take those tests with them rather than leave them passing vacuously.
"""

import copy
import json

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.ir import load_pack
from duly_kernel.report import (
    PII_REDACTION,
    render_report_blocks,
    render_report_markdown,
    render_report_pdf,
)

from conftest import REPO_ROOT, FIXTURE_CORPUS, fixture_case, fixture_pack, rehash_fact

AS_OF_EFFECTIVE = "2026-07-25"
AS_OF_KNOWLEDGE = "2026-07-30T16:00:00Z"

# The fixture corpus's committed bitemporal point (fixtures/cases/fx-0001/
# case.yaml). Passed explicitly everywhere: the scenario facts carry no
# `effectiveFrom`, and a wall clock reaching an assertion would make these
# tests fail on a date rather than on a defect.
FX_AS_OF_EFFECTIVE = "2026-06-01"
FX_AS_OF_KNOWLEDGE = "2026-03-02T12:00:00Z"


def _load_facts(directory) -> list[dict]:
    facts = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" not in doc:
            facts.append(doc)
    return facts


# ---------------------------------------------------------------------------
# Fixture corpus (toolkit)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fx() -> tuple[dict, list[dict], dict]:
    """fx-0001 as committed: the stored receipt, its facts, and the pack.

    The exception fires here and defeats the default, so the receipt carries a
    non-empty `defeated` list and a two-level derivation — the shapes the
    narrative sections exist to render.
    """
    facts, _case, receipt = fixture_case("fx-0001")
    assert facts, "fx-0001 has no facts"
    return receipt, facts, fixture_pack()


@pytest.fixture(scope="module")
def fx_scenario() -> tuple[dict, list[dict], dict]:
    """The fixture scenario's document-grounded facts, adjudicated.

    fixtures/scenario is the only committed fixture content whose facts carry
    document grounding (rendition, page, charSpan, quote), which the evidence
    lines, the Evidence section and the PII redaction all render. Its score
    fact is *deliberately* below the pack's confidence floor — that is the
    review arc the scenario exists to drive — so as committed the decision
    abstains, consumes no fact, and renders an empty Evidence section. Every
    assertion here would then hold vacuously, so the score is re-asserted at
    full confidence and re-hashed (it stays a self-consistent content-addressed
    document; only this process ever sees it).
    """
    pack = fixture_pack()
    facts = []
    for path in sorted((FIXTURE_CORPUS / "scenario" / "facts").glob("*.json")):
        fact = json.loads(path.read_text(encoding="utf-8"))
        if fact["attribute"] == "fx:score":
            fact = copy.deepcopy(fact)
            fact["confidence"] = {"score": 1.0, "method": "raw"}
            fact = rehash_fact(fact)
        facts.append(fact)
    assert facts, "the fixture scenario has no facts"
    receipt = adjudicate(
        facts, pack, FX_AS_OF_EFFECTIVE, FX_AS_OF_KNOWLEDGE, "fx:permitted"
    )
    assert receipt["inputFacts"], "the scenario decision consumed no fact"
    return receipt, facts, pack


# ---------------------------------------------------------------------------
# Example content (moves with `examples/`)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ny() -> tuple[dict, list[dict], dict]:
    """EXAMPLE CONTENT (moves with `starters/` + `rulepacks/`)."""
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
    """EXAMPLE CONTENT (moves with `starters/` + `rulepacks/`)."""
    facts = _load_facts(REPO_ROOT / "starters" / "trid" / "facts")
    pack = load_pack(
        REPO_ROOT / "rulepacks" / "trid-fee-tolerance-us-federal" / "pack.yaml"
    )
    receipt = adjudicate(
        facts, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, "trid:toleranceCureAmount"
    )
    return receipt, facts, pack


class TestDeterminism:
    def test_markdown_byte_identical(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        a = render_report_markdown(receipt, facts, pack).encode("utf-8")
        b = render_report_markdown(receipt, facts, pack).encode("utf-8")
        assert a == b

    def test_pdf_byte_identical(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        a = render_report_pdf(receipt, facts, pack)
        b = render_report_pdf(receipt, facts, pack)
        assert a == b

    def test_trid_pdf_byte_identical(self, trid):
        """EXAMPLE CONTENT (moves with `starters/` + `rulepacks/`): the TRID
        report is the renderer's second shape — a money decision over a
        multi-fee starter — and the reason to render it twice is that *this*
        content, not a fixture, is what an adopter downloads. The toolkit's
        determinism claim is carried by the two tests above, which survive the
        move; this one goes with the pack it renders.
        """
        receipt, facts, pack = trid
        assert render_report_pdf(receipt, facts, pack) == render_report_pdf(
            receipt, facts, pack
        )

    def test_blocks_identical(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        assert render_report_blocks(receipt, facts, pack) == render_report_blocks(
            receipt, facts, pack
        )


class TestBlocks:
    """The block renderer is the section structure made transportable.

    Its value is that it is a third *walk* of one structure rather than a
    third report: these tests exist to catch the day someone gives it its own
    content, at which point the Markdown and the browser would start saying
    different things about the same decision.
    """

    def test_sections_match_the_markdown_headings(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        blocks = render_report_blocks(receipt, facts, pack)
        md = render_report_markdown(receipt, facts, pack)
        titled = [s["title"] for s in blocks if s["title"]]
        assert titled, "the report rendered no titled section"
        assert titled == [line[3:] for line in md.splitlines() if line.startswith("## ")]

    def test_every_block_carries_a_tag_this_repo_renders(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        tags = {b["tag"] for s in render_report_blocks(receipt, facts, pack) for b in s["blocks"]}
        assert tags, "the report rendered no block"
        assert tags <= {"para", "kv", "steps", "subhead", "code"}

    def test_output_is_json_serializable(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        blocks = render_report_blocks(receipt, facts, pack)
        assert blocks
        assert json.loads(json.dumps(blocks)) == blocks

    def test_evidence_lines_survive_into_steps(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        blocks = render_report_blocks(receipt, facts, pack)
        reasoning = next(s for s in blocks if s["title"] == "Reasoning")
        steps = [step for b in reasoning["blocks"] for step in b["steps"]]
        assert steps and any(step["evidence"] for step in steps)
        # A grounded premise renders as its document and its quote, not as a
        # bare fact id — the line an auditor reads.
        lines = [line for step in steps for line in step["evidence"]]
        assert any(
            "doc:widget-report:FX-INSPECTION-0005" in line
            and '"Measured score: 12"' in line
            for line in lines
        ), lines

    def test_pii_redaction_holds_in_blocks_too(self, fx_scenario):
        # The redaction lives in the shared section builder, so it applies to
        # every renderer — but a viewer leaking a quote the PDF redacts would
        # be a bad way to find that out.
        receipt, facts, pack = fx_scenario
        quotes = [f["grounding"]["quote"] for f in facts if "quote" in f["grounding"]]
        assert quotes, "no fixture scenario fact carries a quote"
        plain = json.dumps(render_report_blocks(receipt, facts, pack), ensure_ascii=False)
        rendered_quotes = [q for q in quotes if q in plain]
        assert rendered_quotes, "no quote reached the blocks to begin with"

        redacted = copy.deepcopy(facts)
        for fact in redacted:
            fact["sensitivity"] = "pii"
        rendered = json.dumps(render_report_blocks(receipt, redacted, pack), ensure_ascii=False)
        assert PII_REDACTION in rendered
        for quote in rendered_quotes:
            assert quote not in rendered


class TestMarkdownContent:
    """What the Markdown report says, asserted on the fixture corpus."""

    def test_defeat_is_narrated_in_conclusion_and_in_rules_applied(self, fx):
        # The capability this covers — an overriding rule's defeat of the one
        # it displaced, named in prose, with what the defeated rule *would*
        # have concluded — is the argued part of the report. The fixture pack
        # carries the shape on purpose: FX-EXCEPTION-01 overrides
        # FX-DEFAULT-00, so every fx-0001 receipt has a non-empty `defeated`.
        receipt, facts, pack = fx
        md = render_report_markdown(receipt, facts, pack)
        assert "Fixture exception (fictional)" in md
        assert "https://example.invalid/fixture/exception-01" in md
        assert "**Verdict:** permitted: no" in md
        # Conclusion: the narrative sentence.
        assert (
            "In reaching it, FX-EXCEPTION-01 overrode the default presumption "
            "(FX-DEFAULT-00, which would otherwise have concluded "
            "fx:permitted = true)." in md
        )
        # Rules applied: the same defeat, per-rule.
        assert (
            "This rule overrode FX-DEFAULT-00, which would otherwise have "
            "concluded fx:permitted = true." in md
        )
        assert "- **Defeated:** FX-DEFAULT-00" in md

    def test_money_verdict_carries_its_currency(self, fx):
        # A non-boolean decision: the report renders the amount *and* the
        # currency, in the header verdict and in the conclusion sentence. (The
        # pack's `phrasing:` block is the demo's presentation layer and never
        # reaches this renderer — the report says what the value is.)
        _receipt, facts, pack = fx
        fee = adjudicate(
            facts, pack, FX_AS_OF_EFFECTIVE, FX_AS_OF_KNOWLEDGE, "fx:assessedFee"
        )
        md = render_report_markdown(fee, facts, pack)
        assert "**Verdict:** 250.00 USD" in md
        assert 'the question "What fee is assessed?" was answered: 250.00 USD.' in md
        assert (
            "which would otherwise have concluded fx:assessedFee = 0.00 USD" in md
        )

    def test_pack_none_still_renders(self, fx):
        receipt, facts, _pack = fx
        md = render_report_markdown(receipt, facts, None)
        # Without the pack, the question falls back to the attribute...
        assert "- **Question:** fx:permitted" in md
        # ...and the verdict to the kernel's own boolean phrasing.
        assert "**Verdict:** permitted: no" in md
        # The defeat is still named, but what the defeated rule would have
        # concluded is not knowable without the pack.
        assert "FX-DEFAULT-00, which would otherwise have concluded its own conclusion" in md


class TestNyMarkdownContent:
    def test_citation_quote_defeat_and_verdict(self, ny):
        """EXAMPLE CONTENT (moves with `starters/` + `rulepacks/`): every
        string here is a claim about the NY non-renewal starter and the
        termination-notice pack — the statutory citation, the quote the
        extractor grounded, that pack's own rule ids. Deleting the starter
        should take this test with it; the renderer capability it exercises
        (defeat narration, citation, verdict) is covered on the fixture
        corpus by TestMarkdownContent above.
        """
        receipt, facts, pack = ny
        md = render_report_markdown(receipt, facts, pack)
        assert "N.Y. Ins. Law § 3425(d)(1)" in md
        assert "Date of Mailing: July 25, 2026" in md
        # The exception rule's defeat of the default presumption is narrated.
        assert "NC-DEF-00" in md
        assert "overrode NC-DEF-00" in md
        assert "Not compliant" in md


class TestTridMarkdownContent:
    def test_cure_amount_and_citation(self, trid):
        """EXAMPLE CONTENT (moves with `starters/` + `rulepacks/`): the cure
        amount and the CFR citation are facts about the TRID pack, not about
        the renderer. Money rendering itself is asserted on the fixture pack's
        fx:assessedFee decision in TestMarkdownContent.
        """
        receipt, facts, pack = trid
        md = render_report_markdown(receipt, facts, pack)
        assert "250.00" in md
        assert "12 CFR 1026.19(e)(3)(i)" in md


class TestPdfShape:
    def test_pdf_header_and_size(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        pdf = render_report_pdf(receipt, facts, pack)
        assert pdf.startswith(b"%PDF")
        # The floor is unchanged from the starter-backed version of this test:
        # the fixture report is a full six-section document (~5.8 kB), so it
        # clears 2048 with the same margin the starter did. A byte count is a
        # smoke test — the assertion that matters is that a report with an
        # empty Evidence section (the shape an abstaining case renders) does
        # not quietly become the thing under test, which fx_scenario prevents.
        assert len(pdf) > 2048


class TestPiiRedaction:
    def test_pii_quote_redacted_in_markdown(self, fx_scenario):
        receipt, facts, pack = fx_scenario
        # The scenario's fx:inspector fact ships `sensitivity: pii` and a quote
        # carrying a name and a street address — but no rule reads
        # fx:inspector, so it is never a decision input and never reaches the
        # report. Redaction has to be asserted on a fact the decision actually
        # consumed, so the category fact is marked here (committed bytes
        # otherwise untouched).
        target_quote = "Assigned category: restricted"
        assert target_quote in render_report_markdown(receipt, facts, pack), (
            "the quote is not rendered unredacted, so its absence proves nothing"
        )

        redacted_facts = copy.deepcopy(facts)
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
        marked_fact = next(
            f for f in redacted_facts
            if f.get("grounding", {}).get("quote") == target_quote
        )
        assert marked_fact["grounding"]["documentId"] in md
        assert marked_fact["contentHash"] in md
