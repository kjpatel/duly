"""DMN XML -> an in-memory model, with `xml.etree.ElementTree` and nothing else.

Reading is deliberately separate from compiling: this module knows DMN's
element names and duly's annotation convention, and it knows *nothing* about
the rule IR. Everything it produces is ordered — element document order, never
a dict or set iteration — because the compiler's determinism contract is only
as good as its input's.

The duly extension namespace (`urn:duly:dmn:0.1`) carries the four things DMN
has no vocabulary for, all of them per-decision rather than per-row: which
entity the decision is about, which attribute it concludes, that attribute's
duly value kind, and the code system a `code` conclusion draws from. See
spec/dmn.md M3 for why these are extension elements and the legal metadata
is annotation columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import MALFORMED_DOCUMENT, UNSUPPORTED_DMN_VERSION, DmnCompileError, Location

# DMN model namespaces this compiler accepts. 1.3 is the floor: it is the
# first release in which rule annotation columns (`annotation` /
# `annotationEntry`) are part of the metamodel, and the citation convention
# is built on them.
DMN_NAMESPACES: dict[str, str] = {
    "https://www.omg.org/spec/DMN/20191111/MODEL/": "1.3",
    "https://www.omg.org/spec/DMN/20211108/MODEL/": "1.4",
    "https://www.omg.org/spec/DMN/20230324/MODEL/": "1.5",
}

DULY_NS = "urn:duly:dmn:0.1"


@dataclass(frozen=True)
class InputColumn:
    label: str
    expression: str
    type_ref: str | None
    index: int


@dataclass(frozen=True)
class OutputColumn:
    label: str | None
    name: str | None
    type_ref: str | None
    output_values: str | None


@dataclass(frozen=True)
class Row:
    index: int  # 1-based, as a decision-table editor numbers rows
    input_entries: tuple[str, ...]
    output_entry: str
    annotations: dict[str, str]
    description: str | None


@dataclass(frozen=True)
class DecisionTable:
    hit_policy: str
    aggregation: str | None
    inputs: tuple[InputColumn, ...]
    outputs: tuple[OutputColumn, ...]
    annotation_names: tuple[str, ...]
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Decision:
    id: str
    name: str
    question: str | None
    description: str | None
    entity_type: str | None
    attribute: str | None
    value_kind: str | None
    currency: str | None
    code_system: str | None
    code_system_version: str | None
    entity_var: str | None
    table: DecisionTable


@dataclass
class Definitions:
    dmn_version: str
    name: str | None
    description: str | None
    pack: dict[str, str] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _ns_of(tag: str) -> str | None:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else None


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    return "".join(el.itertext()).strip() or None


def read_file(path: str | Path) -> Definitions:
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as e:
        raise DmnCompileError(
            MALFORMED_DOCUMENT, f"file is not well-formed XML: {e}", Location()
        ) from None
    return read_element(tree.getroot())


def read_string(source: str) -> Definitions:
    try:
        root = ET.fromstring(source)
    except ET.ParseError as e:
        raise DmnCompileError(
            MALFORMED_DOCUMENT, f"input is not well-formed XML: {e}", Location()
        ) from None
    return read_element(root)


def read_element(root: ET.Element) -> Definitions:
    ns = _ns_of(root.tag)
    if _local(root.tag) != "definitions":
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            f"root element is {_local(root.tag)!r}; a DMN document's root is `definitions`.",
            Location(),
        )
    if ns not in DMN_NAMESPACES:
        known = ", ".join(f"{v} ({k})" for k, v in DMN_NAMESPACES.items())
        raise DmnCompileError(
            UNSUPPORTED_DMN_VERSION,
            f"document declares the DMN namespace {ns!r}, which this compiler does "
            f"not accept. DMN 1.3 is the floor (rule annotation columns are the "
            f"citation vehicle and do not exist before 1.3). Accepted: {known}.",
            Location(),
        )

    defs = Definitions(
        dmn_version=DMN_NAMESPACES[ns],
        name=root.get("name"),
        description=_text(root.find(f"{{{ns}}}description")),
    )

    for ext in root.findall(f"{{{ns}}}extensionElements"):
        for pack_el in ext.findall(f"{{{DULY_NS}}}pack"):
            defs.pack = {k: v for k, v in sorted(pack_el.attrib.items())}

    for decision_el in root.findall(f"{{{ns}}}decision"):
        defs.decisions.append(_read_decision(decision_el, ns))

    if not defs.decisions:
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            "document declares no `decision` elements; there is nothing to compile.",
            Location(),
        )
    return defs


def _read_decision(el: ET.Element, ns: str) -> Decision:
    did = el.get("id") or el.get("name") or "<unnamed decision>"
    loc = Location(decision=did)

    ext_attrs: dict[str, str] = {}
    for ext in el.findall(f"{{{ns}}}extensionElements"):
        for d in ext.findall(f"{{{DULY_NS}}}decision"):
            ext_attrs.update(d.attrib)

    table_el = el.find(f"{{{ns}}}decisionTable")
    if table_el is None:
        other = [
            _local(child.tag)
            for child in el
            if _local(child.tag)
            in ("literalExpression", "context", "invocation", "relation", "list", "functionDefinition")
        ]
        raise DmnCompileError(
            MALFORMED_DOCUMENT,
            (
                f"decision has no `decisionTable`"
                + (f" (its logic is a {other[0]!r})" if other else "")
                + ". This compiler compiles decision tables only; boxed expressions "
                "are outside the supported subset (spec/dmn.md, \"What this "
                "deliberately does not do\")."
            ),
            loc,
        )

    return Decision(
        id=did,
        name=el.get("name") or did,
        question=_text(el.find(f"{{{ns}}}question")),
        description=_text(el.find(f"{{{ns}}}description")),
        entity_type=ext_attrs.get("entityType"),
        attribute=ext_attrs.get("attribute"),
        value_kind=ext_attrs.get("valueKind"),
        currency=ext_attrs.get("currency"),
        code_system=ext_attrs.get("codeSystem"),
        code_system_version=ext_attrs.get("codeSystemVersion"),
        entity_var=ext_attrs.get("entityVar"),
        table=_read_table(table_el, ns, loc),
    )


def _read_table(el: ET.Element, ns: str, loc: Location) -> DecisionTable:
    inputs: list[InputColumn] = []
    for i, input_el in enumerate(el.findall(f"{{{ns}}}input")):
        expr_el = input_el.find(f"{{{ns}}}inputExpression")
        expression = _text(expr_el.find(f"{{{ns}}}text")) if expr_el is not None else None
        if not expression:
            raise DmnCompileError(
                MALFORMED_DOCUMENT,
                f"input column {i + 1} has no `inputExpression/text`. In a "
                f"duly-compiled table the input expression is the attribute CURIE "
                f"the column binds (e.g. `trid:feeType`).",
                loc,
            )
        label = input_el.get("label") or _default_label(expression)
        inputs.append(
            InputColumn(
                label=label,
                expression=expression,
                type_ref=expr_el.get("typeRef") if expr_el is not None else None,
                index=i,
            )
        )

    outputs = tuple(
        OutputColumn(
            label=o.get("label"),
            name=o.get("name"),
            type_ref=o.get("typeRef"),
            output_values=_text(
                o.find(f"{{{ns}}}outputValues/{{{ns}}}text")
                if o.find(f"{{{ns}}}outputValues") is not None
                else None
            ),
        )
        for o in el.findall(f"{{{ns}}}output")
    )

    annotation_names = tuple(
        (a.get("name") or "").strip() for a in el.findall(f"{{{ns}}}annotation")
    )

    rows: list[Row] = []
    for i, rule_el in enumerate(el.findall(f"{{{ns}}}rule")):
        entries = tuple(
            (_text(e.find(f"{{{ns}}}text")) or "").strip()
            for e in rule_el.findall(f"{{{ns}}}inputEntry")
        )
        out_entries = [
            (_text(e.find(f"{{{ns}}}text")) or "").strip()
            for e in rule_el.findall(f"{{{ns}}}outputEntry")
        ]
        ann_values = [
            (_text(a.find(f"{{{ns}}}text")) or "").strip()
            for a in rule_el.findall(f"{{{ns}}}annotationEntry")
        ]
        annotations: dict[str, str] = {}
        for name, value in zip(annotation_names, ann_values):
            if name:
                annotations[name] = value
        rows.append(
            Row(
                index=i + 1,
                input_entries=entries,
                output_entry=out_entries[0] if out_entries else "",
                annotations=annotations,
                description=_text(rule_el.find(f"{{{ns}}}description")),
            )
        )

    return DecisionTable(
        hit_policy=(el.get("hitPolicy") or "UNIQUE").strip().upper(),
        aggregation=el.get("aggregation"),
        inputs=tuple(inputs),
        outputs=outputs,
        annotation_names=annotation_names,
        rows=tuple(rows),
    )


def _default_label(expression: str) -> str:
    """A column with no `label` binds under the local part of its CURIE.

    `trid:actualAmountAtClosing` -> `actualAmountAtClosing`. Deterministic and
    reversible; unlike a rule id, a binding name is internal to the rule and
    carries no audit identity, so deriving one is safe. Collisions are caught
    by the compiler, not papered over."""
    local = expression.rsplit(":", 1)[-1].strip()
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in local)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"v_{cleaned}"
    return cleaned
