"""Audit-report rendering for DecisionReceipts.

Renders a receipt (plus the facts it consumed and, optionally, the pack that
produced it) into a layered human-readable report: a compliance-reader
narrative first, a technical integrity appendix last.

Three output formats share one intermediate section structure:

- `render_report_markdown(receipt, facts, pack)` -> str   (canonical)
- `render_report_pdf(receipt, facts, pack)`      -> bytes (reportlab, A4)
- `render_report_blocks(receipt, facts, pack)`   -> list  (JSON-serializable)

The third is the structure itself, made transportable: the same sections and
blocks the other two walk, as plain dicts, for a caller that renders them in
its own medium (the demo's receipt viewer renders them to DOM). It exists so
that a new medium is a new *walk* of the section list rather than a second
report implementation — the property that keeps the Markdown and the PDF
saying the same thing is the one that has to keep holding.

The report's headline verdict is not this module's wording. It comes from the
pack's own `phrasing:` block through `duly_kernel.phrasing.determination` —
the same implementation the demo's answer line uses — falling back to naming
the value when the pack phrases this decision nowhere. A report is the
examiner-facing artifact, so the sentence it leads with has to be the one the
rule author wrote, not one the renderer guessed from an attribute name.

CRITICAL PROPERTY — determinism. Rendering is pure templating over its
inputs: no wall clock (every date printed comes from the receipt or facts),
no randomness, no dict-order dependence. Same inputs, byte-identical output.
The PDF canvas is built with invariant=1 so reportlab emits no timestamps
or random document ids.
"""

from __future__ import annotations

from dataclasses import dataclass

from .phrasing import determination
from .phrasing import format_value as _fmt_value
from .phrasing import local_name as _local

# ---------------------------------------------------------------------------
# Intermediate representation: a report is a list of sections; each section
# is a title plus typed blocks. Both renderers walk this same structure.
# ---------------------------------------------------------------------------

# Block shapes (plain tuples, first element is the tag):
#   ("para", text)
#   ("kv", ((label, value, mono), ...))          key-value rows
#   ("steps", ((lead, (evidence, ...)), ...))    numbered reasoning steps
#   ("subhead", text)                            sub-heading within a section
#   ("code", text)                               monospace block (verbatim)

PII_REDACTION = "[quote redacted — PII]"


@dataclass(frozen=True)
class _Section:
    title: str | None
    blocks: tuple


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _verdict(receipt: dict, facts: list[dict], pack: dict | None) -> str:
    """The decision phrased for the report header.

    Wording is **pack data**. When the pack declares a `phrasing:` case that
    applies to this decision, that case's verdict is the verdict — the same
    selection this repo's UIs use, because it is the same implementation
    (`duly_kernel.phrasing.determination`).

    Without a pack, or with a pack that phrases this decision nowhere, the
    report falls back to naming the value: `permitted: no` for a boolean,
    `250.00 USD` for money. That fallback is deliberately flat. It used to
    special-case any attribute whose local name contained "compliant" and
    render it "Compliant"/"Not compliant" — a domain heuristic tuned to one of
    duly's own packs, sitting in the kernel, quietly outranking whatever the
    pack said. Every pack that wanted those words can and does say so in its
    own `phrasing:` block; a pack that says nothing gets its attribute named
    back, which is the honest answer.
    """
    decision = receipt.get("decision", {})
    phrased = determination(receipt, facts, pack)
    if phrased is not None:
        return phrased["verdict"]
    value = decision.get("value", {})
    if value.get("kind") == "boolean":
        name = _local(decision.get("attribute", ""))
        return f"{name}: yes" if value.get("value") else f"{name}: no"
    return _fmt_value(value)


def _short_hash(hex_or_urn: str) -> str:
    """First 12 hex chars of a fact hash or urn:duly:fact:sha256:<hex> id."""
    hex_part = hex_or_urn.rsplit(":", 1)[-1]
    return hex_part[:12] + "…"


def _question_for(receipt: dict, pack: dict | None) -> str:
    attribute = receipt.get("decision", {}).get("attribute", "")
    if isinstance(pack, dict):
        for decision in pack.get("decisions", []) or []:
            if isinstance(decision, dict) and decision.get("attribute") == attribute:
                return str(decision.get("question", attribute))
    return attribute


def _pack_rule(pack: dict | None, rule_id: str) -> dict | None:
    if not isinstance(pack, dict):
        return None
    for rule in pack.get("rules", []) or []:
        if isinstance(rule, dict) and rule.get("id") == rule_id:
            return rule
    return None


def _rule_ref(receipt: dict, rule_id: str) -> dict | None:
    for ref in receipt.get("rulesFired", []) or []:
        if ref.get("ruleId") == rule_id:
            return ref
    return None


def _then_phrase(rule: dict | None) -> str:
    """What a (defeated) rule would have concluded, from its pack `then`."""
    if not isinstance(rule, dict) or not isinstance(rule.get("then"), dict):
        return "its own conclusion"
    then = rule["then"]
    attribute = then.get("attribute", "?")
    value = then.get("value")
    if isinstance(value, dict):
        if "expr" in value:
            return f"{attribute} = ({value['expr']})"
        return f"{attribute} = {_fmt_value(value)}"
    return str(attribute)


def _day(iso: str | None) -> str:
    return (iso or "")[:10]


def _quote_text(fact: dict | None) -> str | None:
    """The renderable quote for a fact, honoring PII sensitivity."""
    if fact is None:
        return None
    grounding = fact.get("grounding", {})
    if grounding.get("kind") != "document":
        return None
    quote = grounding.get("quote")
    if quote is None:
        return None
    if fact.get("sensitivity") == "pii":
        return PII_REDACTION
    return f'"{quote}"'


def _evidence_line(fact_id: str, facts_by_id: dict[str, dict]) -> str:
    fact = facts_by_id.get(fact_id)
    if fact is None:
        return f"— fact {_short_hash(fact_id)}: pinned by hash; body not supplied"
    grounding = fact.get("grounding", {})
    ref = f"(fact {_short_hash(fact.get('contentHash', fact_id))})"
    if grounding.get("kind") == "document":
        doc = grounding.get("documentId", "unknown document")
        quoted = _quote_text(fact)
        if quoted is None:
            quoted = "(no quote captured)"
        return f"— {doc}: {quoted} {ref}"
    if grounding.get("kind") == "attestation":
        actor = grounding.get("actor", "unknown actor")
        channel = grounding.get("channel")
        via = f" via {channel}" if channel else ""
        return f"— attested by {actor}{via} at {grounding.get('at', '?')} {ref}"
    return f"— ungrounded assertion {ref}"


def _walk_postorder(node: dict, out: list[dict]) -> None:
    """Derivation nodes, deepest sub-derivations first (premises before use)."""
    for premise in node.get("premises", []) or []:
        if isinstance(premise, dict) and "conclusion" in premise:
            _walk_postorder(premise, out)
    out.append(node)


# ---------------------------------------------------------------------------
# Section building
# ---------------------------------------------------------------------------


def _build_header(receipt: dict, facts: list[dict], pack: dict | None) -> _Section:
    as_of = receipt.get("asOf", {})
    rule_pack = receipt.get("rulePack", {})
    engine = receipt.get("engine", {})
    rows = (
        ("Case", receipt.get("caseId", ""), False),
        ("Question", _question_for(receipt, pack), False),
        ("Verdict", _verdict(receipt, facts, pack), False),
        ("As of (effective)", as_of.get("effective", ""), False),
        ("As of (knowledge)", as_of.get("knowledge", ""), False),
        (
            "Rule pack",
            f"{rule_pack.get('name', '?')} v{rule_pack.get('version', '?')}",
            False,
        ),
        (
            "Engine",
            f"{engine.get('kernel', '?')} v{engine.get('version', '?')} "
            f"({engine.get('backend', '?')} backend)",
            False,
        ),
        ("Receipt", receipt.get("id", ""), True),
    )
    return _Section(None, (("kv", rows),))


def _build_conclusion(
    receipt: dict, facts: list[dict], pack: dict | None
) -> _Section:
    decision = receipt.get("decision", {})
    root = receipt.get("derivation", {})
    question = _question_for(receipt, pack)
    verdict = _verdict(receipt, facts, pack)
    if decision.get("value", {}).get("kind") == "boolean":
        verdict = verdict.lower()
    sentences = [
        f'For case {receipt.get("caseId", "?")}, the question '
        f'"{question}" was answered: {verdict}.'
    ]
    root_rule_id = root.get("rule")
    if root_rule_id:
        ref = _rule_ref(receipt, root_rule_id) or {}
        citation = (ref.get("citation") or {}).get("text", "uncited")
        sentences.append(
            f"This conclusion was produced by rule {root_rule_id} "
            f"v{ref.get('version', '?')} under {citation}."
        )
        defeated = ref.get("defeated") or []
        if defeated:
            phrases = []
            for did in defeated:
                phrases.append(
                    f"{did}, which would otherwise have concluded "
                    f"{_then_phrase(_pack_rule(pack, did))}"
                )
            sentences.append(
                f"In reaching it, {root_rule_id} overrode the default "
                f"presumption ({'; '.join(phrases)})."
            )
    return _Section("Conclusion", (("para", " ".join(sentences)),))


def _build_reasoning(
    receipt: dict, facts_by_id: dict[str, dict], pack: dict | None
) -> _Section:
    nodes: list[dict] = []
    derivation = receipt.get("derivation")
    if isinstance(derivation, dict):
        _walk_postorder(derivation, nodes)

    steps = []
    for node in nodes:
        rule_id = node.get("rule")
        conclusion = node.get("conclusion", {})
        attribute = conclusion.get("attribute", "?")
        value = _fmt_value(conclusion.get("value", {}))
        ref = _rule_ref(receipt, rule_id) or {} if rule_id else {}
        citation = (ref.get("citation") or {}).get("text", "uncited")
        version = ref.get("version", "?")
        pack_rule = _pack_rule(pack, rule_id) if rule_id else None
        description = (pack_rule or {}).get("description")
        if description:
            lead = (
                f"{description} ({citation}). Under {rule_id} v{version}, "
                f"{attribute} was determined to be {value}."
            )
        else:
            lead = (
                f"Under {rule_id} v{version} ({citation}), "
                f"{attribute} was determined to be {value}."
            )
        evidence = tuple(
            _evidence_line(p["factId"], facts_by_id)
            for p in node.get("premises", []) or []
            if isinstance(p, dict) and "factId" in p
        )
        steps.append((lead, evidence))
    return _Section("Reasoning", (("steps", tuple(steps)),))


def _build_rules_applied(receipt: dict, pack: dict | None) -> _Section:
    blocks: list = []
    any_defeated = False
    for ref in receipt.get("rulesFired", []) or []:
        citation = ref.get("citation") or {}
        cite_text = citation.get("text", "uncited")
        if citation.get("url"):
            cite_text = f"{cite_text} — {citation['url']}"
        window = _day(ref.get("effectiveFrom")) + " → " + (
            _day(ref.get("effectiveTo")) if ref.get("effectiveTo") else "open-ended"
        )
        blocks.append(
            (
                "subhead",
                f"{ref.get('ruleId', '?')} v{ref.get('version', '?')} "
                f"(priority {ref.get('priority', '?')})",
            )
        )
        rows = [
            ("Citation", cite_text, False),
            ("Effective", window, False),
        ]
        defeated = ref.get("defeated") or []
        if defeated:
            any_defeated = True
            rows.append(("Defeated", ", ".join(defeated), False))
        blocks.append(("kv", tuple(rows)))
        for did in defeated:
            blocks.append(
                (
                    "para",
                    f"This rule overrode {did}, which would otherwise have "
                    f"concluded {_then_phrase(_pack_rule(pack, did))}.",
                )
            )
    if not any_defeated:
        blocks.append(
            (
                "para",
                "No rule was defeated in this adjudication: the decision "
                "rests on the default presumption undisturbed.",
            )
        )
    return _Section("Rules applied", tuple(blocks))


def _build_evidence(receipt: dict, facts_by_id: dict[str, dict]) -> _Section:
    blocks: list = []
    for pin in receipt.get("inputFacts", []) or []:
        fact_id = pin.get("id", "")
        fact = facts_by_id.get(fact_id)
        if fact is None:
            blocks.append(("subhead", f"Fact {_short_hash(fact_id)}"))
            blocks.append(
                (
                    "para",
                    "Pinned in the receipt by content hash, but the fact body "
                    "— where the value and its source quote live — was not "
                    "supplied for rendering.",
                )
            )
            continue
        attribute = fact.get("attribute", "?")
        blocks.append(("subhead", f"{attribute} — fact {_short_hash(fact_id)}"))
        rows: list = [
            ("Attribute", attribute, False),
            ("Value", _fmt_value(fact.get("value", {})), False),
        ]
        grounding = fact.get("grounding", {})
        if grounding.get("kind") == "document":
            rows.append(("Document", grounding.get("documentId", "?"), False))
            if grounding.get("page") is not None:
                rows.append(("Page", str(grounding["page"]), False))
            span = grounding.get("charSpan")
            if isinstance(span, dict):
                rows.append(
                    ("Character span", f"{span.get('start')}–{span.get('end')}", False)
                )
            quoted = _quote_text(fact)
            if quoted is not None:
                rows.append(("Quote", quoted, False))
        elif grounding.get("kind") == "attestation":
            actor = grounding.get("actor", "?")
            channel = grounding.get("channel")
            via = f" via {channel}" if channel else ""
            rows.append(
                ("Attestation", f"{actor}{via} at {grounding.get('at', '?')}", False)
            )
        assertion = fact.get("assertion", {})
        if assertion.get("kind") == "machine":
            extractor = assertion.get("extractor", {})
            rows.append(
                (
                    "Extractor",
                    f"{extractor.get('name', '?')} v{extractor.get('version', '?')}",
                    False,
                )
            )
        elif assertion.get("kind") == "human":
            actor = assertion.get("actor", {})
            role = f" ({actor.get('role')})" if actor.get("role") else ""
            rows.append(("Asserted by", f"{actor.get('id', '?')}{role}", False))
        rows.append(("Assertion kind", assertion.get("kind", "?"), False))
        confidence = fact.get("confidence")
        if isinstance(confidence, dict):
            rows.append(
                (
                    "Confidence",
                    f"{confidence.get('score')} ({confidence.get('method')})",
                    False,
                )
            )
        rows.append(("Content hash", fact.get("contentHash", "?"), True))
        blocks.append(("kv", tuple(rows)))
    return _Section("Evidence", tuple(blocks))


def _build_integrity(receipt: dict) -> _Section:
    as_of = receipt.get("asOf", {})
    engine = receipt.get("engine", {})
    rule_pack = receipt.get("rulePack", {})
    pack_path = f"rulepacks/{rule_pack.get('name', '<pack-name>')}/pack.yaml"
    attribute = receipt.get("decision", {}).get("attribute", "<attribute>")
    command = (
        "uv run python -m duly_kernel \\\n"
        "    --facts <directory of the facts pinned in inputFacts> \\\n"
        f"    --pack {pack_path} \\\n"
        f"    --asof {as_of.get('effective', '<effective>')} \\\n"
        f"    --asof-knowledge {as_of.get('knowledge', '<knowledge>')} \\\n"
        f"    --question {attribute}"
    )
    blocks = (
        ("kv", (("Receipt SHA-256", receipt.get("receiptSha256", "?"), True),)),
        (
            "para",
            "This receipt is content-addressed: receiptSha256 is the SHA-256 "
            "of the receipt's RFC 8785-style canonical JSON (sorted keys, "
            "minimal separators, UTF-8), excluding the id and receiptSha256 "
            "fields themselves. Any alteration to the receipt changes its hash.",
        ),
        (
            "para",
            "Every input fact is content-addressed the same way: each fact's "
            "id is urn:duly:fact:sha256:<contentHash>, so the facts this "
            "decision consumed can be verified byte-for-byte against the "
            "hashes pinned in inputFacts.",
        ),
        ("para", "To replay this decision:"),
        ("code", command),
        (
            "para",
            "The facts directory must contain exactly the facts pinned in "
            "inputFacts (matched by content hash); any other fact set is a "
            "different adjudication.",
        ),
        (
            "para",
            f"Engine: {engine.get('kernel', '?')} v{engine.get('version', '?')}, "
            f"{engine.get('backend', '?')} backend.",
        ),
        (
            "para",
            "Determinism statement: this report is a pure rendering of the "
            "receipt, its input facts, and the rule pack. Re-rendering the "
            "same inputs produces a byte-identical report; re-running the "
            "engine on the pinned facts, pack version, and asOf pair "
            "reproduces the same receipt hash.",
        ),
    )
    return _Section("Integrity and replay", blocks)


def _build_sections(
    receipt: dict, facts: list[dict], pack: dict | None
) -> list[_Section]:
    facts_by_id = {f["id"]: f for f in facts if isinstance(f, dict) and "id" in f}
    return [
        _build_header(receipt, facts, pack),
        _build_conclusion(receipt, facts, pack),
        _build_reasoning(receipt, facts_by_id, pack),
        _build_rules_applied(receipt, pack),
        _build_evidence(receipt, facts_by_id),
        _build_integrity(receipt),
    ]


# ---------------------------------------------------------------------------
# Block renderer (the section structure, made transportable)
# ---------------------------------------------------------------------------


def render_report_blocks(
    receipt: dict, facts: list[dict], pack: dict | None = None
) -> list[dict]:
    """Render the audit report as JSON-serializable sections.

    Returns `[{"title": str|None, "blocks": [...]}]`, where each block is one
    of:

        {"tag": "para",    "text": str}
        {"tag": "subhead", "text": str}
        {"tag": "code",    "text": str}
        {"tag": "kv",      "rows":  [{"label": str, "value": str, "mono": bool}]}
        {"tag": "steps",   "steps": [{"lead": str, "evidence": [str]}]}

    Same determinism contract as the other two renderers: pure templating over
    the inputs, no wall clock, no randomness. The tuples become dicts and the
    text is carried verbatim — a caller that renders these to markup is
    responsible for escaping, and should be handing them to a text node.
    """
    sections: list[dict] = []
    for section in _build_sections(receipt, facts, pack):
        blocks: list[dict] = []
        for block in section.blocks:
            tag = block[0]
            if tag in ("para", "subhead", "code"):
                blocks.append({"tag": tag, "text": block[1]})
            elif tag == "kv":
                blocks.append(
                    {
                        "tag": "kv",
                        "rows": [
                            {"label": label, "value": value, "mono": bool(mono)}
                            for label, value, mono in block[1]
                        ],
                    }
                )
            elif tag == "steps":
                blocks.append(
                    {
                        "tag": "steps",
                        "steps": [
                            {"lead": lead, "evidence": list(evidence)}
                            for lead, evidence in block[1]
                        ],
                    }
                )
        sections.append({"title": section.title, "blocks": blocks})
    return sections


# ---------------------------------------------------------------------------
# Markdown renderer (canonical)
# ---------------------------------------------------------------------------


def render_report_markdown(
    receipt: dict, facts: list[dict], pack: dict | None = None
) -> str:
    """Render the audit report as Markdown. Deterministic: same inputs,
    byte-identical output."""
    lines: list[str] = ["# Decision audit report", ""]
    for section in _build_sections(receipt, facts, pack):
        if section.title:
            lines.append(f"## {section.title}")
            lines.append("")
        for block in section.blocks:
            tag = block[0]
            if tag == "para":
                lines.append(block[1])
                lines.append("")
            elif tag == "kv":
                for label, value, mono in block[1]:
                    rendered = f"`{value}`" if mono else value
                    lines.append(f"- **{label}:** {rendered}")
                lines.append("")
            elif tag == "steps":
                for i, (lead, evidence) in enumerate(block[1], start=1):
                    lines.append(f"{i}. {lead}")
                    for line in evidence:
                        lines.append(f"   {line}")
                lines.append("")
            elif tag == "subhead":
                lines.append(f"### {block[1]}")
                lines.append("")
            elif tag == "code":
                lines.append("```")
                lines.append(block[1])
                lines.append("```")
                lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# PDF renderer (reportlab; same section structure, never derived from the
# markdown). invariant=1 keeps the bytes stable across renders.
# ---------------------------------------------------------------------------


def render_report_pdf(
    receipt: dict, facts: list[dict], pack: dict | None = None
) -> bytes:
    """Render the audit report as an A4 PDF. Deterministic: the canvas is
    created with invariant=1, so identical inputs yield identical bytes."""
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

    class _InvariantCanvas(_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)

    h1 = ParagraphStyle(
        "h1", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=10
    )
    h2 = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15,
        spaceBefore=14, spaceAfter=6,
    )
    h3 = ParagraphStyle(
        "h3", fontName="Helvetica-Bold", fontSize=9.5, leading=13,
        spaceBefore=8, spaceAfter=3,
    )
    body = ParagraphStyle(
        "body", fontName="Times-Roman", fontSize=10, leading=14,
        alignment=TA_LEFT, spaceAfter=6,
    )
    kv_style = ParagraphStyle(
        "kv", parent=body, spaceAfter=2, leftIndent=4 * mm, wordWrap="CJK"
    )
    step_style = ParagraphStyle(
        "step", parent=body, spaceBefore=4, spaceAfter=2,
        leftIndent=6 * mm, firstLineIndent=-6 * mm,
    )
    evidence_style = ParagraphStyle(
        "evidence", parent=body, fontSize=9, leading=12,
        leftIndent=10 * mm, spaceAfter=2, textColor="black",
    )
    code_style = ParagraphStyle(
        "code", fontName="Courier", fontSize=8, leading=11,
        leftIndent=4 * mm, spaceBefore=4, spaceAfter=6,
    )

    def _mono_span(text: str) -> str:
        return f'<font face="Courier" size="7.5">{escape(text)}</font>'

    story: list = [Paragraph("Decision audit report", h1)]
    for section in _build_sections(receipt, facts, pack):
        if section.title:
            story.append(Paragraph(escape(section.title), h2))
        for block in section.blocks:
            tag = block[0]
            if tag == "para":
                story.append(Paragraph(escape(block[1]), body))
            elif tag == "kv":
                for label, value, mono in block[1]:
                    rendered = _mono_span(value) if mono else escape(value)
                    story.append(
                        Paragraph(f"<b>{escape(label)}:</b> {rendered}", kv_style)
                    )
                story.append(Spacer(1, 3 * mm))
            elif tag == "steps":
                for i, (lead, evidence) in enumerate(block[1], start=1):
                    story.append(Paragraph(f"{i}. {escape(lead)}", step_style))
                    for line in evidence:
                        story.append(Paragraph(escape(line), evidence_style))
            elif tag == "subhead":
                story.append(Paragraph(escape(block[1]), h3))
            elif tag == "code":
                story.append(Preformatted(block[1], code_style))

    def _footer(canv, doc) -> None:
        canv.saveState()
        canv.setFont("Helvetica", 8)
        canv.drawCentredString(A4[0] / 2, 12 * mm, f"Page {canv.getPageNumber()}")
        canv.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        title="Decision audit report",
        author="duly-kernel",
    )
    doc.build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
        canvasmaker=_InvariantCanvas,
    )
    return buf.getvalue()
