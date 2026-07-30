"""Compile failures, located.

Every refusal names *where* it happened. A DMN decision table is a grid, so
a location is a decision id, a table row (1-based, as a DMN editor shows it),
and a column — plus the offending source text. An error that says only
"unsupported expression" costs the author a hunt through XML; an error that
says `decision 'toleranceCureAmount', row 2, input column 'actual'
(trid:actualAmountAtClosing): "sum(a, b)"` costs them nothing.

There is exactly one exception type. The compiler never warns, never
degrades, and never emits a partial pack: refusing loudly is the whole
contract (spec/dmn.md, "Refusal classes").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """Where in the DMN document a problem is. Every field is optional
    because refusals happen at every granularity — the definitions element,
    a decision, a column, a single cell."""

    decision: str | None = None
    row: int | None = None
    rule_id: str | None = None
    column: str | None = None
    expression: str | None = None
    text: str | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.decision is not None:
            parts.append(f"decision {self.decision!r}")
        if self.row is not None:
            row = f"row {self.row}"
            if self.rule_id is not None:
                row += f" (rule {self.rule_id!r})"
            parts.append(row)
        elif self.rule_id is not None:
            parts.append(f"rule {self.rule_id!r}")
        if self.column is not None:
            col = f"column {self.column!r}"
            if self.expression is not None:
                col += f" [{self.expression}]"
            parts.append(col)
        elif self.expression is not None:
            parts.append(f"expression {self.expression!r}")
        out = ", ".join(parts)
        if self.text is not None:
            out = f"{out}: {self.text!r}" if out else f"{self.text!r}"
        return out


class DmnCompileError(Exception):
    """The DMN document cannot be compiled into the duly rule IR.

    `klass` is the refusal class (spec/dmn.md); it exists so callers and
    tests can assert on the category without matching prose."""

    def __init__(self, klass: str, message: str, location: Location | None = None):
        self.klass = klass
        self.message = message
        self.location = location or Location()
        where = self.location.describe()
        full = f"[{klass}] {message}"
        if where:
            full = f"{full}\n  at {where}"
        super().__init__(full)


# Refusal classes. Named constants so tests assert on the taxonomy, not the
# wording, and so spec/dmn.md's table has something to be checked against.
UNSUPPORTED_DMN_VERSION = "unsupported-dmn-version"
MALFORMED_DOCUMENT = "malformed-document"
UNSUPPORTED_HIT_POLICY = "unsupported-hit-policy"
UNSUPPORTED_EXPRESSION = "unsupported-expression"
MISSING_CITATION = "missing-citation"
MISSING_EFFECTIVE_DATE = "missing-effective-date"
MISSING_RULE_ID = "missing-rule-id"
UNPROVABLE_UNIQUE = "unprovable-unique"
UNSUPPORTED_TABLE_SHAPE = "unsupported-table-shape"
BINDING_ERROR = "binding-error"
