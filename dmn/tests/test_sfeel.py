"""The S-FEEL cell compiler: what it accepts, and what it refuses by name."""

from __future__ import annotations

import pytest

from duly_dmn.errors import DmnCompileError, Location
from duly_dmn.sfeel import compile_input_entry, compile_output_entry

NAMES = frozenset({"amount", "other", "state"})
LOC = Location(decision="d", row=1, column="amount")


def compile_cell(text: str, var: str = "amount"):
    return compile_input_entry(text, var, NAMES, LOC)


@pytest.mark.parametrize(
    "cell,expected",
    [
        ('"US-NY"', 'amount == "US-NY"'),
        ('= "US-NY"', 'amount == "US-NY"'),
        ("45", "amount == 45"),
        ("true", "amount == true"),
        ("< 45", "amount < 45"),
        ("<= 45", "amount <= 45"),
        ("> 45", "amount > 45"),
        (">= 45", "amount >= 45"),
        ("> other", "amount > other"),
        ('date("2026-03-15")', 'amount == date("2026-03-15")'),
        ('>= date("2026-03-15")', 'amount >= date("2026-03-15")'),
        ("[1..5]", "(amount >= 1 and amount <= 5)"),
        ("(0..10]", "(amount > 0 and amount <= 10)"),
        ("[0..10)", "(amount >= 0 and amount < 10)"),
        ("]0..10[", "(amount > 0 and amount < 10)"),
        ('"A","B"', '(amount == "A" or amount == "B")'),
        ('not("A")', 'not (amount == "A")'),
        ("> -5", "amount > -5"),
    ],
)
def test_supported_unary_tests(cell, expected):
    assert compile_cell(cell).condition == expected


@pytest.mark.parametrize("cell", ["-", "", "   "])
def test_irrelevant_cell_produces_no_condition(cell):
    test = compile_cell(cell)
    assert test.irrelevant and test.condition is None


def test_endpoint_reference_is_reported_as_a_dependency():
    """The `given` rule depends on knowing which OTHER columns a cell names."""
    assert compile_cell("> other").references == ("other",)
    assert compile_cell("> 5").references == ()


def test_string_equality_is_flagged_as_a_disjointness_proof():
    """Only this exact shape counts to the kernel's pack validator."""
    assert compile_cell('"US-NY"').equality_literal == "US-NY"
    assert compile_cell("[1..5]").equality_literal is None
    assert compile_cell('"A","B"').equality_literal is None
    assert compile_cell('not("A")').equality_literal is None


@pytest.mark.parametrize(
    "cell,fragment",
    [
        ("sum(amount, 1)", "function 'sum'"),
        ("> count(amount)", "function 'count'"),
        ('date and time("2026-03-15T00:00:00")', "date and time"),
        ('duration("P3D")', "duration(...)"),
        ("every x in amount satisfies x > 1", "every"),
        ("some x in amount satisfies x > 1", "some"),
        ("for x in amount return x", "for"),
        ("if amount > 1 then 2 else 3", "if"),
        ("{a: 1}", "boxed context"),
        ("null", "null"),
        ('!= "A"', "`!=`"),
        ("> unknownColumn", "not a column of this decision table"),
    ],
)
def test_out_of_subset_cells_are_refused_by_name(cell, fragment):
    with pytest.raises(DmnCompileError) as excinfo:
        compile_cell(cell)
    assert excinfo.value.klass == "unsupported-expression"
    assert fragment in str(excinfo.value)


def test_refusal_names_the_cell_and_the_row():
    with pytest.raises(DmnCompileError) as excinfo:
        compile_input_entry("sum(amount, 1)", "amount", NAMES, LOC)
    message = str(excinfo.value)
    assert "decision 'd'" in message and "row 1" in message and "column 'amount'" in message


# --- output cells ----------------------------------------------------------


def test_output_literal_keeps_the_authors_lexeme():
    """`0.00` must not become `0.0`: money amounts are strings in the IR."""
    out = compile_output_entry("0.00", NAMES, LOC)
    assert out.literal is not None and out.literal.raw == "0.00"
    assert out.expr is None


def test_output_expression_and_its_references():
    out = compile_output_entry("amount - other", NAMES, LOC)
    assert out.literal is None
    assert out.expr == "amount - other"
    assert set(out.references) == {"amount", "other"}


def test_output_expression_respects_parentheses():
    out = compile_output_entry("(amount - other) * 2", NAMES, LOC)
    assert out.expr == "(amount - other) * 2"


def test_empty_output_cell_is_refused():
    with pytest.raises(DmnCompileError) as excinfo:
        compile_output_entry("-", NAMES, LOC)
    assert "irrelevant" in str(excinfo.value)


def test_string_literal_contents_are_not_scanned_for_keywords():
    """A fee type called "Every Other Fee" is data, not a quantified expression."""
    assert compile_cell('"Every Other Fee"').condition == 'amount == "Every Other Fee"'
