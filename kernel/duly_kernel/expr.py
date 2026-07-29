"""Typed expression language for the rule IR (spec/rule-ir.md).

Hand-rolled tokenizer + recursive-descent parser + evaluator. Values are
typed; arithmetic and comparisons never coerce — any type mismatch raises
ExprTypeError. Numbers are decimal.Decimal, never float.

Grammar (lowest to highest precedence):

    expr        := or_expr
    or_expr     := and_expr ("or" and_expr)*
    and_expr    := not_expr ("and" not_expr)*
    not_expr    := "not" not_expr | comparison
    comparison  := additive (("==" | "!=" | "<" | "<=" | ">" | ">=") additive)?
    additive    := multiplicative (("+" | "-") multiplicative)*
    multiplicative := unary (("*" | "/") unary)*
    unary       := "-" unary | primary
    primary     := NUMBER | STRING | "true" | "false"
                 | IDENT "(" args ")" | IDENT | "(" expr ")"
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from decimal import Decimal


class ExprError(Exception):
    """Base for expression-language failures."""


class ExprSyntaxError(ExprError):
    """The expression source does not parse."""


class ExprTypeError(ExprError):
    """An operation was applied to operands of the wrong type."""


class ExprNameError(ExprError):
    """An identifier is not bound in the evaluation environment."""


# ---------------------------------------------------------------------------
# Typed values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecimalV:
    value: Decimal


@dataclass(frozen=True)
class MoneyV:
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class DateV:
    value: _dt.date


@dataclass(frozen=True)
class DateTimeV:
    value: _dt.datetime


@dataclass(frozen=True)
class BoolV:
    value: bool


@dataclass(frozen=True)
class StringV:
    value: str


@dataclass(frozen=True)
class CodeV:
    value: str
    code_system: str
    code_system_version: str | None = None


@dataclass(frozen=True)
class EntityRefV:
    value: str


Value = DecimalV | MoneyV | DateV | DateTimeV | BoolV | StringV | CodeV | EntityRefV


def _kind(v: Value) -> str:
    return {
        DecimalV: "decimal",
        MoneyV: "money",
        DateV: "date",
        DateTimeV: "datetime",
        BoolV: "boolean",
        StringV: "string",
        CodeV: "code",
        EntityRefV: "entityRef",
    }[type(v)]


def value_from_fact(value: dict) -> Value:
    """Convert a GroundedFact value union (JSON dict) into a typed value."""
    kind = value.get("kind")
    if kind == "string":
        return StringV(value["value"])
    if kind == "decimal":
        return DecimalV(Decimal(value["value"]))
    if kind == "money":
        return MoneyV(Decimal(value["amount"]), value["currency"])
    if kind == "date":
        return DateV(_dt.date.fromisoformat(value["value"]))
    if kind == "datetime":
        return DateTimeV(parse_datetime(value["value"]))
    if kind == "boolean":
        return BoolV(value["value"])
    if kind == "code":
        return CodeV(value["value"], value["codeSystem"], value.get("codeSystemVersion"))
    if kind == "entityRef":
        return EntityRefV(value["value"])
    raise ExprTypeError(f"unknown fact value kind: {kind!r}")


def value_to_fact(v: Value) -> dict:
    """Serialize a typed value back to the GroundedFact value union shape."""
    if isinstance(v, StringV):
        return {"kind": "string", "value": v.value}
    if isinstance(v, DecimalV):
        return {"kind": "decimal", "value": _decimal_str(v.value)}
    if isinstance(v, MoneyV):
        return {"kind": "money", "amount": _decimal_str(v.amount), "currency": v.currency}
    if isinstance(v, DateV):
        return {"kind": "date", "value": v.value.isoformat()}
    if isinstance(v, DateTimeV):
        return {"kind": "datetime", "value": format_datetime(v.value)}
    if isinstance(v, BoolV):
        return {"kind": "boolean", "value": v.value}
    if isinstance(v, CodeV):
        out = {"kind": "code", "value": v.value, "codeSystem": v.code_system}
        if v.code_system_version is not None:
            out["codeSystemVersion"] = v.code_system_version
        return out
    if isinstance(v, EntityRefV):
        return {"kind": "entityRef", "value": v.value}
    raise ExprTypeError(f"cannot serialize value of type {type(v).__name__}")


def _decimal_str(d: Decimal) -> str:
    """Render a Decimal to the spec's DecimalString form (no exponent)."""
    s = format(d, "f")
    # Normalize "-0" to "0" for determinism.
    if s == "-0":
        s = "0"
    return s


def parse_datetime(s: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def format_datetime(dt: _dt.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    dt = dt.astimezone(_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<op>==|!=|<=|>=|[+\-*/<>(),])
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "true", "false"}


@dataclass(frozen=True)
class _Tok:
    kind: str  # "number" | "string" | "ident" | "op" | "eof"
    text: str
    pos: int


def _tokenize(src: str) -> list[_Tok]:
    toks: list[_Tok] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise ExprSyntaxError(f"unexpected character {src[i]!r} at position {i} in {src!r}")
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        toks.append(_Tok(kind, m.group(), m.start()))
    toks.append(_Tok("eof", "", len(src)))
    return toks


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lit:
    value: Value


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str  # "-" | "not"
    operand: "Node"


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Call:
    func: str
    args: tuple["Node", ...]


Node = Lit | Var | Unary | Binary | Call


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = _tokenize(src)
        self.i = 0

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def next(self) -> _Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, text: str) -> None:
        t = self.next()
        if t.kind != "op" or t.text != text:
            raise ExprSyntaxError(f"expected {text!r} at position {t.pos} in {self.src!r}, got {t.text!r}")

    def at_op(self, *texts: str) -> bool:
        t = self.peek()
        return t.kind == "op" and t.text in texts

    def at_kw(self, kw: str) -> bool:
        t = self.peek()
        return t.kind == "ident" and t.text == kw

    def parse(self) -> Node:
        node = self.or_expr()
        t = self.peek()
        if t.kind != "eof":
            raise ExprSyntaxError(f"unexpected trailing input at position {t.pos} in {self.src!r}: {t.text!r}")
        return node

    def or_expr(self) -> Node:
        node = self.and_expr()
        while self.at_kw("or"):
            self.next()
            node = Binary("or", node, self.and_expr())
        return node

    def and_expr(self) -> Node:
        node = self.not_expr()
        while self.at_kw("and"):
            self.next()
            node = Binary("and", node, self.not_expr())
        return node

    def not_expr(self) -> Node:
        if self.at_kw("not"):
            self.next()
            return Unary("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> Node:
        node = self.additive()
        if self.at_op("==", "!=", "<", "<=", ">", ">="):
            op = self.next().text
            node = Binary(op, node, self.additive())
        return node

    def additive(self) -> Node:
        node = self.multiplicative()
        while self.at_op("+", "-"):
            op = self.next().text
            node = Binary(op, node, self.multiplicative())
        return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while self.at_op("*", "/"):
            op = self.next().text
            node = Binary(op, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.at_op("-"):
            self.next()
            return Unary("-", self.unary())
        return self.primary()

    def primary(self) -> Node:
        t = self.next()
        if t.kind == "number":
            return Lit(DecimalV(Decimal(t.text)))
        if t.kind == "string":
            return Lit(StringV(_unescape(t.text)))
        if t.kind == "ident":
            if t.text == "true":
                return Lit(BoolV(True))
            if t.text == "false":
                return Lit(BoolV(False))
            if t.text in _KEYWORDS:
                raise ExprSyntaxError(f"unexpected keyword {t.text!r} at position {t.pos} in {self.src!r}")
            if self.at_op("("):
                self.next()
                args: list[Node] = []
                if not self.at_op(")"):
                    args.append(self.or_expr())
                    while self.at_op(","):
                        self.next()
                        args.append(self.or_expr())
                self.expect_op(")")
                return Call(t.text, tuple(args))
            return Var(t.text)
        if t.kind == "op" and t.text == "(":
            node = self.or_expr()
            self.expect_op(")")
            return node
        raise ExprSyntaxError(f"unexpected token {t.text!r} at position {t.pos} in {self.src!r}")


def _unescape(quoted: str) -> str:
    body = quoted[1:-1]
    return body.replace('\\"', '"').replace("\\\\", "\\")


def parse(src: str) -> Node:
    """Parse an expression string into an AST."""
    return _Parser(src).parse()


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ExprTypeError(msg)


def _same_currency(a: MoneyV, b: MoneyV, op: str) -> None:
    if a.currency != b.currency:
        raise ExprTypeError(f"money {op} requires matching currencies: {a.currency} vs {b.currency}")


def _eval_arith(op: str, lv: Value, rv: Value) -> Value:
    if op == "+":
        if isinstance(lv, DecimalV) and isinstance(rv, DecimalV):
            return DecimalV(lv.value + rv.value)
        if isinstance(lv, MoneyV) and isinstance(rv, MoneyV):
            _same_currency(lv, rv, "+")
            return MoneyV(lv.amount + rv.amount, lv.currency)
    elif op == "-":
        if isinstance(lv, DecimalV) and isinstance(rv, DecimalV):
            return DecimalV(lv.value - rv.value)
        if isinstance(lv, MoneyV) and isinstance(rv, MoneyV):
            _same_currency(lv, rv, "-")
            return MoneyV(lv.amount - rv.amount, lv.currency)
    elif op == "*":
        if isinstance(lv, DecimalV) and isinstance(rv, DecimalV):
            return DecimalV(lv.value * rv.value)
        if isinstance(lv, MoneyV) and isinstance(rv, DecimalV):
            return MoneyV(lv.amount * rv.value, lv.currency)
        if isinstance(lv, DecimalV) and isinstance(rv, MoneyV):
            return MoneyV(lv.value * rv.amount, rv.currency)
    elif op == "/":
        if isinstance(lv, DecimalV) and isinstance(rv, DecimalV):
            return DecimalV(lv.value / rv.value)
        if isinstance(lv, MoneyV) and isinstance(rv, DecimalV):
            return MoneyV(lv.amount / rv.value, lv.currency)
    raise ExprTypeError(f"cannot apply {op!r} to {_kind(lv)} and {_kind(rv)}")


def _eq(lv: Value, rv: Value) -> bool:
    # code == string compares the code's value field (either operand order).
    if isinstance(lv, CodeV) and isinstance(rv, StringV):
        return lv.value == rv.value
    if isinstance(lv, StringV) and isinstance(rv, CodeV):
        return lv.value == rv.value
    if type(lv) is not type(rv):
        raise ExprTypeError(f"cannot compare {_kind(lv)} with {_kind(rv)}")
    if isinstance(lv, MoneyV) and isinstance(rv, MoneyV):
        _same_currency(lv, rv, "==")
        return lv.amount == rv.amount
    return lv == rv


def _order_key(v: Value):
    if isinstance(v, DecimalV):
        return v.value
    if isinstance(v, MoneyV):
        return v.amount
    if isinstance(v, (DateV, DateTimeV)):
        return v.value
    if isinstance(v, StringV):
        return v.value
    raise ExprTypeError(f"{_kind(v)} values are not ordered")


def _eval_compare(op: str, lv: Value, rv: Value) -> BoolV:
    if op == "==":
        return BoolV(_eq(lv, rv))
    if op == "!=":
        return BoolV(not _eq(lv, rv))
    if type(lv) is not type(rv):
        raise ExprTypeError(f"cannot compare {_kind(lv)} with {_kind(rv)}")
    if isinstance(lv, MoneyV):
        _same_currency(lv, rv, op)  # type: ignore[arg-type]
    a, b = _order_key(lv), _order_key(rv)
    if op == "<":
        return BoolV(a < b)
    if op == "<=":
        return BoolV(a <= b)
    if op == ">":
        return BoolV(a > b)
    if op == ">=":
        return BoolV(a >= b)
    raise ExprSyntaxError(f"unknown comparison operator {op!r}")


def _eval_call(func: str, args: tuple[Value, ...]) -> Value:
    if func == "date":
        _require(len(args) == 1, "date() takes exactly one argument")
        (a,) = args
        _require(isinstance(a, StringV), "date() takes a string literal")
        try:
            return DateV(_dt.date.fromisoformat(a.value))  # type: ignore[union-attr]
        except ValueError as e:
            raise ExprTypeError(f"invalid date literal {a.value!r}: {e}") from None  # type: ignore[union-attr]
    if func == "days_between":
        _require(len(args) == 2, "days_between() takes exactly two arguments")
        a, b = args
        _require(isinstance(a, DateV) and isinstance(b, DateV), "days_between() takes two dates")
        return DecimalV(Decimal((b.value - a.value).days))  # type: ignore[union-attr]
    if func == "abs":
        _require(len(args) == 1, "abs() takes exactly one argument")
        (a,) = args
        if isinstance(a, DecimalV):
            return DecimalV(abs(a.value))
        if isinstance(a, MoneyV):
            return MoneyV(abs(a.amount), a.currency)
        raise ExprTypeError(f"abs() takes a decimal or money, got {_kind(a)}")
    if func in ("min", "max"):
        _require(len(args) == 2, f"{func}() takes exactly two arguments")
        a, b = args
        if type(a) is not type(b):
            raise ExprTypeError(f"{func}() arguments must have the same type: {_kind(a)} vs {_kind(b)}")
        if isinstance(a, MoneyV):
            _same_currency(a, b, func)  # type: ignore[arg-type]
        ka, kb = _order_key(a), _order_key(b)
        if func == "min":
            return a if ka <= kb else b
        return a if ka >= kb else b
    raise ExprNameError(f"unknown function {func!r}")


def evaluate(node: Node, env: dict[str, Value]) -> Value:
    """Evaluate an AST against an environment of typed values."""
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Var):
        if node.name not in env:
            raise ExprNameError(f"unbound variable {node.name!r}")
        return env[node.name]
    if isinstance(node, Unary):
        v = evaluate(node.operand, env)
        if node.op == "-":
            if isinstance(v, DecimalV):
                return DecimalV(-v.value)
            if isinstance(v, MoneyV):
                return MoneyV(-v.amount, v.currency)
            raise ExprTypeError(f"cannot negate {_kind(v)}")
        if node.op == "not":
            _require(isinstance(v, BoolV), f"'not' requires a boolean, got {_kind(v)}")
            return BoolV(not v.value)  # type: ignore[union-attr]
        raise ExprSyntaxError(f"unknown unary operator {node.op!r}")
    if isinstance(node, Binary):
        # Both operands are evaluated (no short-circuit) so type errors
        # always surface loudly and deterministically.
        lv = evaluate(node.left, env)
        rv = evaluate(node.right, env)
        if node.op in ("and", "or"):
            _require(
                isinstance(lv, BoolV) and isinstance(rv, BoolV),
                f"'{node.op}' requires booleans, got {_kind(lv)} and {_kind(rv)}",
            )
            if node.op == "and":
                return BoolV(lv.value and rv.value)  # type: ignore[union-attr]
            return BoolV(lv.value or rv.value)  # type: ignore[union-attr]
        if node.op in ("==", "!=", "<", "<=", ">", ">="):
            return _eval_compare(node.op, lv, rv)
        return _eval_arith(node.op, lv, rv)
    if isinstance(node, Call):
        args = tuple(evaluate(a, env) for a in node.args)
        return _eval_call(node.func, args)
    raise ExprSyntaxError(f"unknown AST node {node!r}")


def evaluate_str(src: str, env: dict[str, Value] | None = None) -> Value:
    """Parse and evaluate an expression string."""
    return evaluate(parse(src), env or {})
