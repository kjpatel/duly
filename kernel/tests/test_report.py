"""Audit-report renderer tests (kernel/duly_kernel/report.py).

Toolkit behaviour is asserted against the fixture corpus (`fixtures/`): the
committed fx-0001 case and its receipt, and the fixture scenario's three
document-grounded facts. That is deliberate — the renderer is toolkit, so a
suite that proved it worked only against `starters/`+`rulepacks/` would stop
being collected the day that teaching content moves under `examples/`, which
reads exactly like success (fixtures/README.md).

The three tests whose subject was the teaching content — what the NY notice and
TRID reports *say* — now live in `examples/tests/test_example_reports.py`, so
that deleting `examples/` deletes them rather than leaving them passing
vacuously.
"""

import copy
import json

import pytest

from duly_kernel.api import adjudicate
from duly_kernel.report import (
    PII_REDACTION,
    render_report_blocks,
    render_report_markdown,
    render_report_pdf,
)

from conftest import FIXTURE_CORPUS, fixture_case, fixture_pack, rehash_fact

# The fixture corpus's committed bitemporal point (fixtures/cases/fx-0001/
# case.yaml). Passed explicitly everywhere: the scenario facts carry no
# `effectiveFrom`, and a wall clock reaching an assertion would make these
# tests fail on a date rather than on a defect.
FX_AS_OF_EFFECTIVE = "2026-06-01"
FX_AS_OF_KNOWLEDGE = "2026-03-02T12:00:00Z"


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

    def test_the_headline_verdict_is_the_packs_own_wording(self, fx):
        # Verdict wording is pack data, and the report obeys it: fixtures/
        # pack.yaml phrases fx:assessedFee "Fee assessed" above zero and "No
        # fee" at zero, so those are the words, not "250.00 USD". Both guarded
        # branches are asserted — a phrasing test that only exercises the
        # matching case cannot tell a working guard from one that always fires.
        _receipt, facts, pack = fx
        fee = adjudicate(
            facts, pack, FX_AS_OF_EFFECTIVE, FX_AS_OF_KNOWLEDGE, "fx:assessedFee"
        )
        md = render_report_markdown(fee, facts, pack)
        assert "**Verdict:** Fee assessed" in md
        assert 'the question "What fee is assessed?" was answered: Fee assessed.' in md

        # Phrasing replaces the headline, not the record. The amount and its
        # currency still reach the reader, in the reasoning step that concluded
        # them and in what the defeated rule would have concluded instead — so
        # an examiner reading the report can still see the number.
        assert "fx:assessedFee was determined to be 250.00 USD" in md
        assert "which would otherwise have concluded fx:assessedFee = 0.00 USD" in md

        zero_facts, _case, _r = fixture_case("fx-0002")
        no_fee = adjudicate(
            zero_facts, pack, FX_AS_OF_EFFECTIVE, FX_AS_OF_KNOWLEDGE, "fx:assessedFee"
        )
        assert no_fee["decision"]["value"]["amount"] == "0.00"
        assert "**Verdict:** No fee" in render_report_markdown(no_fee, zero_facts, pack)

    def test_a_decision_the_pack_phrases_nowhere_names_its_attribute(self, fx):
        # fx:permitted carries no `phrasing:` block on purpose, so it exercises
        # the fallback: the report names the attribute and its value rather
        # than inventing a verdict no pack author wrote.
        receipt, facts, pack = fx
        assert "**Verdict:** permitted: no" in render_report_markdown(
            receipt, facts, pack
        )

    def test_the_renderer_carries_no_domain_heuristic(self, fx):
        """A regression pin, not a capability.

        `_verdict` used to render any boolean attribute whose local name
        contained "compliant" as "Compliant"/"Not compliant" — a guess tuned to
        one of duly's own packs, living in the kernel, and outranking whatever
        the pack said. It is gone. A pack that wants those words says so in its
        own `phrasing:` block (the termination-notice pack does); a report with
        no pack in hand says what it can defend.
        """
        _receipt, facts, _pack = fx
        borrowed = {
            "caseId": "case:fixture:heuristic",
            "decision": {
                "attribute": "nc:noticeCompliant",
                "value": {"kind": "boolean", "value": False},
            },
        }
        md = render_report_markdown(borrowed, facts, None)
        assert "**Verdict:** noticeCompliant: no" in md
        assert "Not compliant" not in md

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
