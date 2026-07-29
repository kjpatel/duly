import datetime as dt
from decimal import Decimal

import pytest

from duly_kernel.expr import (
    BoolV,
    CodeV,
    DateV,
    DecimalV,
    ExprNameError,
    ExprSyntaxError,
    ExprTypeError,
    MoneyV,
    StringV,
    evaluate_str,
    value_from_fact,
    value_to_fact,
)


def d(s: str) -> DecimalV:
    return DecimalV(Decimal(s))


class TestLiteralsAndArithmetic:
    def test_integer_literal(self):
        assert evaluate_str("45") == d("45")

    def test_decimal_exactness_no_floats(self):
        # The classic float trap: 0.1 + 0.2 must be exactly 0.3.
        assert evaluate_str("0.1 + 0.2") == d("0.3")

    def test_precedence_and_parens(self):
        assert evaluate_str("2 + 3 * 4") == d("14")
        assert evaluate_str("(2 + 3) * 4") == d("20")

    def test_unary_minus(self):
        assert evaluate_str("-5 + 2") == d("-3")

    def test_division(self):
        assert evaluate_str("1 / 8") == d("0.125")

    def test_string_literal(self):
        assert evaluate_str('"US-NY"') == StringV("US-NY")

    def test_booleans(self):
        assert evaluate_str("true") == BoolV(True)
        assert evaluate_str("false") == BoolV(False)

    def test_date_literal(self):
        assert evaluate_str('date("2026-09-01")') == DateV(dt.date(2026, 9, 1))

    def test_syntax_error(self):
        with pytest.raises(ExprSyntaxError):
            evaluate_str("1 +")

    def test_unbound_variable(self):
        with pytest.raises(ExprNameError):
            evaluate_str("mailed")


class TestTypingNeverCoerces:
    def test_string_plus_decimal_raises(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('"a" + 1')

    def test_string_decimal_comparison_raises(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('"45" == 45')

    def test_bool_arithmetic_raises(self):
        with pytest.raises(ExprTypeError):
            evaluate_str("true + true")

    def test_and_requires_booleans(self):
        with pytest.raises(ExprTypeError):
            evaluate_str("1 and true")

    def test_not_requires_boolean(self):
        with pytest.raises(ExprTypeError):
            evaluate_str("not 5")

    def test_date_decimal_comparison_raises(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('date("2026-01-01") < 5')


class TestMoney:
    usd = MoneyV(Decimal("100.50"), "USD")
    eur = MoneyV(Decimal("3.00"), "EUR")

    def test_money_minus_money(self):
        env = {"actual": self.usd, "disclosed": MoneyV(Decimal("0.50"), "USD")}
        assert evaluate_str("actual - disclosed", env) == MoneyV(Decimal("100.00"), "USD")

    def test_currency_mismatch_raises(self):
        env = {"a": self.usd, "b": self.eur}
        with pytest.raises(ExprTypeError):
            evaluate_str("a - b", env)
        with pytest.raises(ExprTypeError):
            evaluate_str("a < b", env)

    def test_money_times_decimal(self):
        env = {"a": MoneyV(Decimal("10.00"), "USD")}
        assert evaluate_str("a * 0.1", env) == MoneyV(Decimal("1.000"), "USD")
        assert evaluate_str("0.5 * a", env) == MoneyV(Decimal("5.000"), "USD")

    def test_money_plus_decimal_raises(self):
        env = {"a": self.usd}
        with pytest.raises(ExprTypeError):
            evaluate_str("a + 1", env)

    def test_money_comparison_same_currency(self):
        env = {"a": self.usd, "b": MoneyV(Decimal("200"), "USD")}
        assert evaluate_str("a < b", env) == BoolV(True)


class TestFunctions:
    def test_days_between(self):
        assert evaluate_str('days_between(date("2026-07-25"), date("2026-09-01"))') == d("38")

    def test_days_between_negative(self):
        assert evaluate_str('days_between(date("2026-09-01"), date("2026-07-25"))') == d("-38")

    def test_days_between_requires_dates(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('days_between(1, date("2026-09-01"))')

    def test_abs_min_max(self):
        assert evaluate_str("abs(-3)") == d("3")
        assert evaluate_str("min(3, 7)") == d("3")
        assert evaluate_str("max(3, 7)") == d("7")

    def test_min_mixed_types_raises(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('min(3, date("2026-01-01"))')

    def test_unknown_function(self):
        with pytest.raises(ExprNameError):
            evaluate_str("frobnicate(1)")


class TestCodeValues:
    code = CodeV("Nonrenewal", "duly-starter-notice/notice-types", "0.1.0")

    def test_code_equals_string_compares_value(self):
        env = {"noticeType": self.code}
        assert evaluate_str('noticeType == "Nonrenewal"', env) == BoolV(True)
        assert evaluate_str('noticeType == "Cancellation"', env) == BoolV(False)
        assert evaluate_str('"Nonrenewal" == noticeType', env) == BoolV(True)
        assert evaluate_str('noticeType != "Cancellation"', env) == BoolV(True)

    def test_code_ordering_raises(self):
        env = {"c": self.code}
        with pytest.raises(ExprTypeError):
            evaluate_str('c < "Z"', env)


class TestBooleanLogic:
    def test_and_or_not(self):
        assert evaluate_str("true and not false") == BoolV(True)
        assert evaluate_str("false or false") == BoolV(False)

    def test_no_short_circuit_type_escape(self):
        # Type errors surface even when the left operand would decide.
        with pytest.raises(ExprTypeError):
            evaluate_str("true or (1 and true)")


class TestFactValueRoundTrip:
    def test_decimal_round_trip(self):
        v = value_from_fact({"kind": "decimal", "value": "45"})
        assert value_to_fact(v) == {"kind": "decimal", "value": "45"}

    def test_money_round_trip(self):
        v = value_from_fact({"kind": "money", "amount": "100.50", "currency": "USD"})
        assert value_to_fact(v) == {"kind": "money", "amount": "100.50", "currency": "USD"}

    def test_date_round_trip(self):
        v = value_from_fact({"kind": "date", "value": "2026-09-01"})
        assert value_to_fact(v) == {"kind": "date", "value": "2026-09-01"}
