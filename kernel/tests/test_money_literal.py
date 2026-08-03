"""There is no money literal, and the error that says so has to teach.

`amount > 200` is the one type mismatch a pack author reaches for on purpose:
money is the only comparable value kind with no literal form, so the natural
way to write a threshold is the one way that does not work. What the author
does next depends entirely on whether the message names the alternative.

The idiom the message points at is not a workaround — it is what all six
committed packs already do, and it is why `git grep` finds no inline numeric
literal in any `when:` guard in this repository.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from duly_kernel.expr import BoolV, DecimalV, ExprTypeError, MoneyV, evaluate, parse

USD = MoneyV(Decimal("312.40"), "USD")


def test_money_has_no_literal_form():
    """`200.00 USD` is not expressible, so the mistake is reached by parsing."""
    with pytest.raises(Exception):
        parse("amount > 200.00 USD")


@pytest.mark.parametrize("src", ["amount > 200", "200 < amount", "amount == 200"])
def test_comparing_money_to_a_number_names_the_idiom(src):
    with pytest.raises(ExprTypeError) as excinfo:
        evaluate(parse(src), {"amount": USD})
    message = str(excinfo.value)
    # The diagnosis, in whichever operand order the author wrote...
    assert "cannot compare" in message and "money" in message and "decimal" in message
    # ...and the cure, which is the part that saves an author a source dive.
    assert "no literal form" in message
    assert "derived:" in message
    assert "spec/rule-ir.md" in message


def test_the_idiom_the_message_recommends_actually_works():
    """A money threshold bound as a value compares fine — the whole point."""
    env = {"amount": USD, "limit": MoneyV(Decimal("200.00"), "USD")}
    assert evaluate(parse("amount > limit"), env).value is True


def test_decimal_comparisons_are_untouched():
    """The teaching clause is money-specific; it must not decorate every
    mismatch. A decimal against a number is ordinary and legal."""
    assert evaluate(parse("days > 30"), {"days": DecimalV(Decimal("45"))}).value is True


def test_an_unrelated_mismatch_gets_no_money_advice():
    """Advice on a mismatch it does not explain would be noise at best."""
    with pytest.raises(ExprTypeError) as excinfo:
        evaluate(parse("flag > 30"), {"flag": BoolV(True)})
    assert "no literal form" not in str(excinfo.value)
