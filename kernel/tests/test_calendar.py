"""Calendar arithmetic (spec/rule-ir.md, "Calendars"): add_business_days
semantics, pack calendar validation, and the `asOf: effective` binding.

The reference calendar in these tests mirrors the TILA precise business-day
definition (12 CFR 1026.2(a)(6)): Sundays and listed holiday dates don't
count, Saturdays do. Nothing here depends on that convention — it is the
pack's data, not the function's.
"""

import datetime as dt

import pytest

from duly_kernel import expr
from duly_kernel.api import adjudicate
from duly_kernel.engine import evaluate_pack, normalize_point
from duly_kernel.expr import (
    Calendar,
    DateV,
    DecimalV,
    ExprCalendarError,
    ExprNameError,
    ExprTypeError,
    StringV,
    evaluate_str,
    parse_calendars,
)
from duly_kernel.ir import PackValidationError, validate_pack

from decimal import Decimal


CAL_BLOCK = {
    "tila-precise": {
        "description": "Sundays and listed holidays out; Saturdays count.",
        "excludedWeekdays": ["Sunday"],
        "coverage": {"from": "2026-01-01", "to": "2028-01-01"},
        "holidays": ["2026-05-25", "2026-07-04", "2026-12-25", "2027-01-01"],
    }
}


def cal() -> dict[str, Calendar]:
    return parse_calendars(CAL_BLOCK)


def add(start: str, n: int, name: str = "tila-precise") -> str:
    result = evaluate_str(
        f'add_business_days(date("{start}"), {n}, "{name}")', {}, cal()
    )
    assert isinstance(result, DateV)
    return result.value.isoformat()


# ---------------------------------------------------------------------------
# add_business_days semantics
# ---------------------------------------------------------------------------


class TestAddBusinessDays:
    def test_plain_weekday_run_counts_every_day(self):
        # Mon 2026-03-02 + 3 -> Thu 2026-03-05 (no Sunday, no holiday).
        assert add("2026-03-02", 3) == "2026-03-05"

    def test_saturday_counts_sunday_does_not(self):
        # Fri 2026-03-06: Sat 3/7 counts (1), Sun 3/8 skipped,
        # Mon 3/9 (2), Tue 3/10 (3).
        assert add("2026-03-06", 3) == "2026-03-10"

    def test_holiday_and_sunday_both_extend_the_window(self):
        # The Memorial-Day window: Fri 2026-05-22 -> Sat 5/23 (1),
        # Sun 5/24 skipped, Mon 5/25 holiday skipped, Tue 5/26 (2),
        # Wed 5/27 (3).
        assert add("2026-05-22", 3) == "2026-05-27"

    def test_zero_days_returns_the_start_date(self):
        assert add("2026-05-24", 0) == "2026-05-24"  # even on a Sunday

    def test_start_day_itself_never_counts(self):
        # "following" semantics: the walk starts the day after `start`,
        # so starting on a Saturday still needs one full business day.
        assert add("2026-03-07", 1) == "2026-03-09"  # Sat -> Mon (Sun skipped)

    def test_negative_count_is_rejected(self):
        with pytest.raises(ExprTypeError, match="non-negative integer"):
            add("2026-03-02", -1)

    def test_fractional_count_is_rejected(self):
        with pytest.raises(ExprTypeError, match="non-negative integer"):
            evaluate_str('add_business_days(date("2026-03-02"), 1.5, "tila-precise")', {}, cal())

    def test_unknown_calendar_is_a_loud_name_error(self):
        with pytest.raises(ExprNameError, match="unknown calendar 'nope'"):
            add("2026-03-02", 3, "nope")

    def test_no_calendars_supplied_names_the_gap(self):
        with pytest.raises(ExprNameError, match="none"):
            evaluate_str('add_business_days(date("2026-03-02"), 3, "tila-precise")')

    def test_wrong_argument_types_are_type_errors(self):
        with pytest.raises(ExprTypeError):
            evaluate_str('add_business_days("2026-03-02", 3, "tila-precise")', {}, cal())
        with pytest.raises(ExprTypeError):
            evaluate_str('add_business_days(date("2026-03-02"), date("2026-03-03"), "tila-precise")', {}, cal())

    def test_year_edge_inside_coverage_walks_across_the_boundary(self):
        # Wed 2026-12-30 -> Thu 12/31 (1), Fri 2027-01-01 holiday skipped,
        # Sat 1/2 (2), Sun skipped, Mon 1/4 (3). Crossing the year boundary
        # is fine while both years are covered.
        assert add("2026-12-30", 3) == "2027-01-04"

    def test_start_outside_coverage_fails_loudly(self):
        with pytest.raises(ExprCalendarError, match="does not cover start date 2025-12-31"):
            add("2025-12-31", 3)

    def test_walk_leaving_coverage_fails_loudly_not_silently(self):
        # The walk from 2027-12-30 must examine days in 2028, which the
        # calendar does not cover: refuse, never treat them as business days.
        with pytest.raises(ExprCalendarError, match="does not cover 2028-01-01"):
            add("2027-12-30", 3)

    def test_result_is_composable_with_comparisons(self):
        v = evaluate_str(
            'add_business_days(date("2026-05-22"), 3, "tila-precise") < date("2026-05-28")',
            {},
            cal(),
        )
        assert v == expr.BoolV(True)


# ---------------------------------------------------------------------------
# parse_calendars validation
# ---------------------------------------------------------------------------


class TestParseCalendars:
    def test_absent_block_is_empty(self):
        assert parse_calendars(None) == {}

    def test_round_trip(self):
        c = cal()["tila-precise"]
        assert c.excluded_weekdays == frozenset({6})
        assert dt.date(2026, 5, 25) in c.holidays
        assert c.coverage_from == dt.date(2026, 1, 1)
        assert c.coverage_to == dt.date(2028, 1, 1)

    def test_unknown_weekday_name(self):
        block = {"c": {**CAL_BLOCK["tila-precise"], "excludedWeekdays": ["Sonntag"]}}
        with pytest.raises(ExprCalendarError, match="unknown weekday 'Sonntag'"):
            parse_calendars(block)

    def test_unparsable_holiday_date(self):
        block = {"c": {**CAL_BLOCK["tila-precise"], "holidays": ["May 25, 2026"]}}
        with pytest.raises(ExprCalendarError, match="not an ISO date"):
            parse_calendars(block)

    def test_holiday_outside_coverage(self):
        block = {"c": {**CAL_BLOCK["tila-precise"], "holidays": ["2031-01-01"]}}
        with pytest.raises(ExprCalendarError, match="outside coverage"):
            parse_calendars(block)

    def test_missing_coverage(self):
        spec = dict(CAL_BLOCK["tila-precise"])
        del spec["coverage"]
        with pytest.raises(ExprCalendarError, match="coverage"):
            parse_calendars({"c": spec})

    def test_inverted_coverage(self):
        block = {
            "c": {
                **CAL_BLOCK["tila-precise"],
                "coverage": {"from": "2028-01-01", "to": "2026-01-01"},
            }
        }
        with pytest.raises(ExprCalendarError, match="'from' must precede 'to'"):
            parse_calendars(block)

    def test_unknown_key_rejected(self):
        block = {"c": {**CAL_BLOCK["tila-precise"], "observanceShift": True}}
        with pytest.raises(ExprCalendarError, match="unknown key"):
            parse_calendars(block)


# ---------------------------------------------------------------------------
# Pack validation: calendars block + static calendar references + asOf
# ---------------------------------------------------------------------------


def minimal_pack(**overrides) -> dict:
    pack = {
        "pack": {"name": "cal-test", "version": "1.0.0"},
        "calendars": {
            "biz": {
                "excludedWeekdays": ["Sunday"],
                "coverage": {"from": "2026-01-01", "to": "2027-01-01"},
                "holidays": ["2026-05-25"],
            }
        },
        "rules": [
            {
                "id": "R1",
                "version": "1.0.0",
                "priority": 100,
                "citation": {"text": "test"},
                "effectiveFrom": "2026-01-01",
                "given": {
                    "thing": {"entityType": "t:Thing"},
                    "start": {"attribute": "t:startDate"},
                },
                "then": {
                    "entity": "thing",
                    "attribute": "t:deadline",
                    "value": {
                        "kind": "date",
                        "expr": 'add_business_days(start, 3, "biz")',
                    },
                },
            }
        ],
    }
    pack.update(overrides)
    return pack


class TestPackValidation:
    def test_valid_calendar_pack_passes(self):
        validate_pack(minimal_pack())

    def test_malformed_calendars_block_is_a_pack_error(self):
        pack = minimal_pack(calendars={"biz": {"excludedWeekdays": ["Sonntag"], "coverage": {"from": "2026-01-01", "to": "2027-01-01"}}})
        with pytest.raises(PackValidationError, match="unknown weekday"):
            validate_pack(pack)

    def test_reference_to_undeclared_calendar_is_a_pack_error(self):
        pack = minimal_pack()
        pack["rules"][0]["then"]["value"]["expr"] = 'add_business_days(start, 3, "other")'
        with pytest.raises(PackValidationError, match="unknown calendar 'other'"):
            validate_pack(pack)

    def test_reference_without_any_calendars_block_is_a_pack_error(self):
        pack = minimal_pack()
        del pack["calendars"]
        with pytest.raises(PackValidationError, match="pack declares: none"):
            validate_pack(pack)

    def test_calendar_argument_must_be_a_string_literal(self):
        pack = minimal_pack()
        pack["rules"][0]["then"]["value"]["expr"] = "add_business_days(start, 3, calName)"
        with pytest.raises(PackValidationError, match="quoted calendar name literal"):
            validate_pack(pack)

    def test_wrong_arity_is_caught_statically(self):
        pack = minimal_pack()
        pack["rules"][0]["then"]["value"]["expr"] = "add_business_days(start, 3)"
        with pytest.raises(PackValidationError, match="exactly three arguments"):
            validate_pack(pack)

    def test_calendar_reference_in_when_is_checked_too(self):
        pack = minimal_pack()
        pack["rules"][0]["when"] = ['add_business_days(start, 3, "other") > start']
        with pytest.raises(PackValidationError, match="unknown calendar 'other'"):
            validate_pack(pack)

    def test_as_of_binding_validates(self):
        pack = minimal_pack()
        pack["rules"][0]["given"]["today"] = {"asOf": "effective"}
        validate_pack(pack)

    def test_as_of_binding_rejects_unknown_dial(self):
        pack = minimal_pack()
        pack["rules"][0]["given"]["today"] = {"asOf": "knowledge"}
        with pytest.raises(PackValidationError, match="asOf must be one of"):
            validate_pack(pack)


# ---------------------------------------------------------------------------
# Engine: asOf binding + calendar evaluation end to end
# ---------------------------------------------------------------------------


def _fact(attribute: str, value: dict) -> dict:
    return {
        "id": f"urn:duly:fact:test:{attribute}",
        "contentHash": "0" * 64,  # not verified by the kernel; receipts echo it
        "caseId": "case:test:cal",
        "entity": {"id": "thing:1", "type": "t:Thing"},
        "attribute": attribute,
        "value": value,
        "assertion": {"kind": "machine", "at": "2026-05-22T00:00:00Z"},
        "status": "asserted",
    }


DEADLINE_PACK = {
    "pack": {"name": "cal-e2e", "version": "1.0.0"},
    "calendars": {
        "biz": {
            "excludedWeekdays": ["Sunday"],
            "coverage": {"from": "2026-01-01", "to": "2027-01-01"},
            "holidays": ["2026-05-25"],
        }
    },
    "decisions": [{"attribute": "t:open", "entityType": "t:Thing"}],
    "rules": [
        {
            "id": "DL",
            "version": "1.0.0",
            "priority": 100,
            "citation": {"text": "test"},
            "effectiveFrom": "2026-01-01",
            "given": {
                "thing": {"entityType": "t:Thing"},
                "start": {"attribute": "t:startDate"},
            },
            "then": {
                "entity": "thing",
                "attribute": "t:deadline",
                "value": {"kind": "date", "expr": 'add_business_days(start, 3, "biz")'},
            },
        },
        {
            "id": "OPEN",
            "version": "1.0.0",
            "priority": 100,
            "citation": {"text": "test"},
            "effectiveFrom": "2026-01-01",
            "given": {
                "thing": {"entityType": "t:Thing"},
                "deadline": {"derived": "t:deadline"},
                "today": {"asOf": "effective"},
            },
            "when": ["today > deadline"],
            "then": {
                "entity": "thing",
                "attribute": "t:open",
                "value": {"kind": "boolean", "value": True},
            },
        },
    ],
}


class TestEngineIntegration:
    def facts(self):
        return [_fact("t:startDate", {"kind": "date", "value": "2026-05-22"})]

    def run(self, as_of: str):
        effective = normalize_point(as_of)
        knowledge = normalize_point(as_of + "T23:59:59Z")
        return evaluate_pack(self.facts(), DEADLINE_PACK, effective, knowledge)

    def test_deadline_computed_through_sunday_and_holiday(self):
        result = self.run("2026-05-28")
        deadline = result.surviving_for("t:deadline")
        assert deadline is not None
        assert deadline.value == DateV(dt.date(2026, 5, 27))

    def test_as_of_binding_flips_with_the_evaluation_date(self):
        # On the deadline day the guard `today > deadline` is false.
        assert self.run("2026-05-27").surviving_for("t:open") is None
        assert self.run("2026-05-28").surviving_for("t:open") is not None

    def test_as_of_binding_leaves_no_premise(self):
        result = self.run("2026-05-28")
        open_firing = result.surviving_for("t:open")
        assert open_firing is not None
        # The derived deadline is a premise; the asOf binding is not (the
        # receipt's top-level asOf already pins the evaluation point).
        assert [p[0] for p in open_firing.premises] == ["derived"]

    def test_receipt_pins_pack_version_over_calendar_semantics(self):
        receipt = adjudicate(
            facts=self.facts(),
            pack=DEADLINE_PACK,
            as_of_effective="2026-05-28",
            as_of_knowledge="2026-05-28T23:59:59Z",
            decision_attribute="t:open",
        )
        assert receipt["decision"]["value"] == {"kind": "boolean", "value": True}
        assert receipt["rulePack"] == {"name": "cal-e2e", "version": "1.0.0"}

    def test_walk_outside_coverage_fails_the_run_loudly(self):
        facts = [_fact("t:startDate", {"kind": "date", "value": "2026-12-30"})]
        effective = normalize_point("2026-12-31")
        with pytest.raises(ExprCalendarError):
            evaluate_pack(facts, DEADLINE_PACK, effective, effective)


# ---------------------------------------------------------------------------
# Direct Calendar behavior
# ---------------------------------------------------------------------------


def test_is_business_day_semantics():
    c = cal()["tila-precise"]
    assert c.is_business_day(dt.date(2026, 5, 23)) is True  # Saturday counts
    assert c.is_business_day(dt.date(2026, 5, 24)) is False  # Sunday
    assert c.is_business_day(dt.date(2026, 5, 25)) is False  # listed holiday
    with pytest.raises(ExprCalendarError):
        c.is_business_day(dt.date(2030, 1, 1))  # outside coverage


def test_eval_call_signature_requires_calendar_name_string():
    with pytest.raises(ExprTypeError, match="calendar name string"):
        expr._eval_call(
            "add_business_days",
            (DateV(dt.date(2026, 3, 2)), DecimalV(Decimal(3)), DateV(dt.date(2026, 1, 1))),
            cal(),
        )
    with pytest.raises(ExprTypeError, match="exactly three arguments"):
        expr._eval_call(
            "add_business_days",
            (DateV(dt.date(2026, 3, 2)), DecimalV(Decimal(3))),
            cal(),
        )
    # StringV name resolves.
    out = expr._eval_call(
        "add_business_days",
        (DateV(dt.date(2026, 3, 2)), DecimalV(Decimal(3)), StringV("tila-precise")),
        cal(),
    )
    assert out == DateV(dt.date(2026, 3, 5))
