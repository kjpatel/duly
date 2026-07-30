"""S-FEEL cell compiler: DMN table cells -> duly rule-IR expression source.

Scope is S-FEEL (DMN 1.3 clause 10.3.1, the "Simplified FEEL" subset that
decision-table cells are defined over), and not one token more. The two cell
grammars:

    unary_tests  := positive_unary_tests | "not" "(" positive_unary_tests ")" | "-"
    positive_unary_test := [ "<" | "<=" | ">" | ">=" ] endpoint | interval
    interval     := ("(" | "]" | "[") endpoint ".." endpoint (")" | "[" | "]")
    endpoint     := qualified_name | numeric | string | boolean | date("...")

    output_entry := literal | name | output_entry (("+"|"-"|"*"|"/") output_entry)
                  | "(" output_entry ")"

Everything else in FEEL — `for`/`some`/`every`, `if`/`then`/`else`, boxed
contexts, lists, function definitions, function invocation other than
`date(...)`, temporal literals other than `date(...)`, `null` — is a loud
refusal naming the cell, the row, and the offending text. This module never
approximates: an unrecognised construct is a `DmnCompileError`, never a
dropped condition (a dropped condition is a rule that fires more often than
its author believes, which is the exact failure the whole project exists to
prevent).

Names are restricted to duly identifiers (`[A-Za-z_][A-Za-z0-9_]*`). FEEL
permits names containing spaces and dots; duly's expression language does
not, and inventing a mangling would make the compiled `when` clause stop
looking like the cell it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import UNSUPPORTED_EXPRESSION, DmnCompileError, Location

# ---------------------------------------------------------------------------
# Constructs that are real FEEL and deliberately out of scope. Detected on the
# raw cell text before tokenizing, so the message names the construct rather
# than blaming whichever token the parser happened to choke on.
# ---------------------------------------------------------------------------

_OUT_OF_SUBSET: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bdate\s+and\s+time\s*\("), "the `date and time(...)` temporal literal"),
    (re.compile(r"\byears\s+and\s+months\s+duration\s*\("), "the `years and months duration(...)` literal"),
    (re.compile(r"\bdays\s+and\s+time\s+duration\s*\("), "the `days and time duration(...)` literal"),
    (re.compile(r"\bduration\s*\("), "the `duration(...)` literal"),
    (re.compile(r"\btime\s*\("), "the `time(...)` literal"),
    (re.compile(r"\bfor\b"), "the `for ... in ... return ...` iteration expression"),
    (re.compile(r"\bsome\b"), "the `some ... in ... satisfies ...` quantified expression"),
    (re.compile(r"\bevery\b"), "the `every ... in ... satisfies ...` quantified expression"),
    (re.compile(r"\bsatisfies\b"), "the `... satisfies ...` quantified expression"),
    (re.compile(r"\bif\b"), "the `if ... then ... else ...` conditional expression"),
    (re.compile(r"\bfunction\s*\("), "a function definition"),
    (re.compile(r"\bexternal\b"), "an external function binding"),
    (re.compile(r"\binstance\s+of\b"), "the `instance of` type test"),
    (re.compile(r"\bnull\b"), "the `null` literal"),
    (re.compile(r"\{"), "a boxed context"),
    (re.compile(r"@\""), "an `@\"...\"` temporal at-literal"),
)

_ALLOWED_FUNCTION = "date"

_STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')


def _reject_out_of_subset(text: str, loc: Location) -> None:
    # String contents are data, not syntax: blank them first so a fee type
    # literally named "Every Other Fee" is not mistaken for a quantified
    # expression.
    scannable = _STRING_LITERAL.sub('""', text)
    for pattern, what in _OUT_OF_SUBSET:
        if pattern.search(scannable):
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"cell uses {what}, which is outside the supported S-FEEL subset. "
                f"duly compiles literals, comparisons, ranges and unary tests only "
                f"(spec/dmn.md, \"The S-FEEL subset\").",
                loc,
            )


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<dotdot>\.\.)
  | (?P<op><=|>=|!=|<|>|=|\+|-|\*|/)
  | (?P<punct>[()\[\],])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str
    pos: int


def _tokenize(src: str, loc: Location) -> list[_Tok]:
    toks: list[_Tok] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m or m.end() == i:
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"cell contains a character duly's S-FEEL subset does not recognise: "
                f"{src[i]!r} at offset {i}.",
                loc,
            )
        kind = m.lastgroup or ""
        if kind != "ws":
            toks.append(_Tok(kind, m.group(), i))
        i = m.end()
    toks.append(_Tok("eof", "", len(src)))
    return toks


# ---------------------------------------------------------------------------
# Endpoint / literal values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Endpoint:
    """One S-FEEL endpoint. `kind` is `string`, `number`, `boolean`, `date`
    or `name`; `source` is what to emit into duly expression source; `raw`
    keeps the author's exact lexeme so `0.00` stays `0.00` and never becomes
    `0.0` (money amounts are strings in the IR for exactly this reason)."""

    kind: str
    source: str
    raw: str


class _Parser:
    def __init__(self, src: str, loc: Location, names: frozenset[str]):
        self.src = src
        self.loc = loc
        self.names = names
        self.toks = _tokenize(src, loc)
        self.i = 0
        self.referenced: list[str] = []

    # -- token helpers -----------------------------------------------------
    @property
    def cur(self) -> _Tok:
        return self.toks[self.i]

    def advance(self) -> _Tok:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect_end(self) -> None:
        if self.cur.kind != "eof":
            self.fail(f"unexpected trailing text {self.src[self.cur.pos:]!r}")

    def fail(self, message: str) -> "DmnCompileError":
        raise DmnCompileError(
            UNSUPPORTED_EXPRESSION,
            f"cell does not parse as S-FEEL: {message}.",
            self.loc,
        )

    # -- endpoints ---------------------------------------------------------
    def endpoint(self) -> Endpoint:
        tok = self.cur
        if tok.kind == "string":
            self.advance()
            return Endpoint("string", tok.text, tok.text)
        if tok.kind == "number":
            self.advance()
            return Endpoint("number", tok.text, tok.text)
        if tok.kind == "op" and tok.text == "-" and self.toks[self.i + 1].kind == "number":
            self.advance()
            num = self.advance()
            return Endpoint("number", f"-{num.text}", f"-{num.text}")
        if tok.kind == "name":
            if tok.text in ("true", "false"):
                self.advance()
                return Endpoint("boolean", tok.text, tok.text)
            if self.toks[self.i + 1].kind == "punct" and self.toks[self.i + 1].text == "(":
                return self.call()
            self.advance()
            if tok.text not in self.names:
                raise DmnCompileError(
                    UNSUPPORTED_EXPRESSION,
                    f"cell references {tok.text!r}, which is not a column of this "
                    f"decision table. Known column bindings: "
                    f"{', '.join(sorted(self.names)) or 'none'}.",
                    self.loc,
                )
            self.referenced.append(tok.text)
            return Endpoint("name", tok.text, tok.text)
        raise self.fail(f"expected a literal or a column name, got {tok.text!r}")

    def call(self) -> Endpoint:
        name = self.advance()
        if name.text != _ALLOWED_FUNCTION:
            raise DmnCompileError(
                UNSUPPORTED_EXPRESSION,
                f"cell invokes the function {name.text!r}. The supported S-FEEL "
                f"subset permits no function invocation other than "
                f"`date(\"YYYY-MM-DD\")` — arithmetic and calendar functions belong "
                f"in the rule IR, not in a decision-table cell "
                f"(spec/dmn.md, \"What this deliberately does not do\").",
                self.loc,
            )
        self.advance()  # (
        if self.cur.kind != "string":
            raise self.fail("date() takes exactly one ISO date string literal")
        arg = self.advance()
        if not (self.cur.kind == "punct" and self.cur.text == ")"):
            raise self.fail("date() takes exactly one ISO date string literal")
        self.advance()
        source = f"date({arg.text})"
        return Endpoint("date", source, source)


# ---------------------------------------------------------------------------
# Unary tests (input entries)
# ---------------------------------------------------------------------------

_OPEN_EXCLUSIVE = {"(", "]"}
_CLOSE_EXCLUSIVE = {")", "["}


@dataclass(frozen=True)
class InputTest:
    """A compiled input cell.

    `irrelevant` is the DMN `-` cell: no condition at all. `condition` is
    duly expression source. `equality_literal` is set only when the cell
    compiled to exactly `var == "quoted string"` — the one shape the kernel's
    pack validator accepts as a disjointness proof, so the compiler tracks it
    explicitly rather than re-deriving it from the emitted text."""

    irrelevant: bool
    condition: str | None
    references: tuple[str, ...]
    equality_literal: str | None


def compile_input_entry(
    text: str, var: str, names: frozenset[str], loc: Location
) -> InputTest:
    """Compile one input cell into a duly `when` condition over `var`."""
    stripped = (text or "").strip()
    if stripped in ("", "-"):
        return InputTest(True, None, (), None)

    _reject_out_of_subset(stripped, loc)
    parser = _Parser(stripped, loc, names)

    negate = False
    if parser.cur.kind == "name" and parser.cur.text == "not":
        parser.advance()
        if not (parser.cur.kind == "punct" and parser.cur.text == "("):
            raise parser.fail("`not` must be written as `not( ... )`")
        parser.advance()
        negate = True

    rendered, atomic, equality = _positive_unary_tests(parser, var)

    if negate:
        if not (parser.cur.kind == "punct" and parser.cur.text == ")"):
            raise parser.fail("unclosed `not(`")
        parser.advance()
        rendered = f"not ({rendered})"
        atomic = True
        equality = None
    parser.expect_end()

    references = tuple(dict.fromkeys(n for n in parser.referenced if n != var))
    if not atomic:
        rendered = f"({rendered})"
    return InputTest(False, rendered, references, equality)


def _positive_unary_tests(parser: _Parser, var: str) -> tuple[str, bool, str | None]:
    """Comma-separated tests are a disjunction (DMN 1.3 10.3.2.14)."""
    parts: list[tuple[str, bool]] = [_positive_unary_test(parser, var)]
    while parser.cur.kind == "punct" and parser.cur.text == ",":
        parser.advance()
        parts.append(_positive_unary_test(parser, var))
    if len(parts) == 1:
        text, atomic = parts[0]
        m = _EQ_SHAPE.match(text)
        return text, atomic, (m.group(1) if m else None)
    joined = " or ".join(t if a else f"({t})" for t, a in parts)
    return f"({joined})", True, None


# The exact shape kernel/duly_kernel/ir.py::_equality_guards accepts as a
# disjointness proof. Kept as a literal regex here so a change on either side
# shows up as a test failure rather than as a pack that stops validating.
_EQ_SHAPE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*\s==\s"((?:[^"\\]|\\.)*)"$')


def _positive_unary_test(parser: _Parser, var: str) -> tuple[str, bool]:
    tok = parser.cur
    if tok.kind == "op" and tok.text in ("<", "<=", ">", ">="):
        parser.advance()
        end = parser.endpoint()
        return f"{var} {tok.text} {end.source}", True
    if tok.kind == "op" and tok.text == "=":
        parser.advance()
        end = parser.endpoint()
        return f"{var} == {end.source}", True
    if tok.kind == "op" and tok.text == "!=":
        raise DmnCompileError(
            UNSUPPORTED_EXPRESSION,
            "cell uses `!=`, which is not an S-FEEL unary test. Write the "
            "negation as `not( ... )`.",
            parser.loc,
        )
    # `(`, `[` and `]` all open a range; `]0..10[` is DMN's alternative
    # spelling for the exclusive-exclusive interval `(0..10)`.
    if tok.kind == "punct" and tok.text in ("(", "[", "]"):
        return _interval(parser, var)
    end = parser.endpoint()
    return f"{var} == {end.source}", True


def _interval(parser: _Parser, var: str) -> tuple[str, bool]:
    open_tok = parser.advance()
    low = parser.endpoint()
    if parser.cur.kind != "dotdot":
        raise parser.fail("a range needs `..` between its endpoints")
    parser.advance()
    high = parser.endpoint()
    close_tok = parser.cur
    if close_tok.kind != "punct" or close_tok.text not in (")", "]", "["):
        raise parser.fail(f"a range must close with `)`, `]` or `[`, got {close_tok.text!r}")
    parser.advance()
    lo_op = ">" if open_tok.text in _OPEN_EXCLUSIVE else ">="
    hi_op = "<" if close_tok.text in _CLOSE_EXCLUSIVE else "<="
    return f"{var} {lo_op} {low.source} and {var} {hi_op} {high.source}", False


# ---------------------------------------------------------------------------
# Output entries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputValue:
    """A compiled output cell: either a literal (kind + exact lexeme) or a
    duly expression referencing column bindings."""

    literal: Endpoint | None
    expr: str | None
    references: tuple[str, ...]


def compile_output_entry(text: str, names: frozenset[str], loc: Location) -> OutputValue:
    stripped = (text or "").strip()
    if stripped in ("", "-"):
        raise DmnCompileError(
            UNSUPPORTED_EXPRESSION,
            "output cell is empty or `-`. `-` means \"irrelevant\", which has no "
            "meaning for a conclusion: every row of a duly-compiled table must "
            "state what it concludes.",
            loc,
        )
    _reject_out_of_subset(stripped, loc)
    parser = _Parser(stripped, loc, names)
    node = _additive(parser)
    parser.expect_end()
    references = tuple(dict.fromkeys(parser.referenced))
    if isinstance(node, Endpoint) and node.kind != "name":
        return OutputValue(node, None, references)
    source = node.source if isinstance(node, Endpoint) else node
    return OutputValue(None, source, references)


def _additive(parser: _Parser) -> Endpoint | str:
    node = _multiplicative(parser)
    while parser.cur.kind == "op" and parser.cur.text in ("+", "-"):
        op = parser.advance().text
        rhs = _multiplicative(parser)
        node = f"{_src(node)} {op} {_src(rhs)}"
    return node


def _multiplicative(parser: _Parser) -> Endpoint | str:
    node = _primary(parser)
    while parser.cur.kind == "op" and parser.cur.text in ("*", "/"):
        op = parser.advance().text
        rhs = _primary(parser)
        node = f"{_src(node)} {op} {_src(rhs)}"
    return node


def _primary(parser: _Parser) -> Endpoint | str:
    if parser.cur.kind == "punct" and parser.cur.text == "(":
        parser.advance()
        inner = _additive(parser)
        if not (parser.cur.kind == "punct" and parser.cur.text == ")"):
            raise parser.fail("unclosed `(`")
        parser.advance()
        return f"({_src(inner)})"
    return parser.endpoint()


def _src(node: Endpoint | str) -> str:
    return node.source if isinstance(node, Endpoint) else node
