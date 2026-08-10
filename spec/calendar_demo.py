#!/usr/bin/env python3
"""Calendar arithmetic in the rule IR, demonstrated on committed data.

Until pack 2026.1.0 the TILA rescission pack could only CERTIFY the deadline
printed on the Notice of Right to Cancel — the IR had no way to walk a
business-day calendar. Now the pack embeds the precise 12 CFR 1026.2(a)(6)
calendar (Sundays and 5 U.S.C. 6103(a) holidays out, SATURDAYS COUNT) and
RESC-DL-01 computes "midnight of the third business day following the latest
trigger" itself, with add_business_days() over that pack-versioned data.

This script adjudicates the committed TILA starter (consummation, notice
delivery, and material disclosures all Friday 2026-05-22 — Memorial Day
weekend) at every evaluation date straddling the window, printing the
computed deadline and the funding answer. The flip lands on 2026-05-28:
naive 3-calendar-day arithmetic would have funded two days earlier, and a
weekday-only calendar would have funded a day late.

Run from the repo root:

    uv run python spec/calendar_demo.py

Everything is deterministic: same starter facts, same pack, same asOf
points, same bytes, forever.
"""
from __future__ import annotations

import json
import pathlib

import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK_PATH = ROOT / "examples/rulepacks/tila-rescission-us-federal/pack.yaml"
FACTS_DIR = ROOT / "examples/starters/tila-rescission/facts"

# The week around the window. 2026-05-22 is a Friday; the three precise
# business days that follow are Sat 5/23, Tue 5/26, Wed 5/27 — Sunday 5/24
# and Memorial Day Monday 5/25 do not count.
AS_OF_POINTS = [
    ("2026-05-22", "consummation day (Friday)"),
    ("2026-05-23", "Saturday — counts as business day 1"),
    ("2026-05-24", "Sunday — never a precise business day"),
    ("2026-05-25", "Memorial Day — 5 U.S.C. 6103(a) holiday"),
    ("2026-05-26", "naive 3-calendar-day math would fund today, wrongly"),
    ("2026-05-27", "computed deadline day — period runs until midnight"),
    ("2026-05-28", "first fundable day"),
]


def main() -> int:
    pack = yaml.safe_load(PACK_PATH.read_text(encoding="utf-8"))
    facts = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(FACTS_DIR.glob("*.json"))
    ]
    calendar = pack["calendars"]["tila-precise"]
    print(f"pack: {pack['pack']['name']}@{pack['pack']['version']}")
    print(
        f"calendar 'tila-precise': excludes {', '.join(calendar['excludedWeekdays'])}s "
        f"+ {len(calendar['holidays'])} listed holiday dates, "
        f"coverage [{calendar['coverage']['from']}, {calendar['coverage']['to']})"
    )
    print(f"facts: {len(facts)} committed starter facts (all triggers 2026-05-22)\n")

    for as_of, label in AS_OF_POINTS:
        deadline = adjudicate(
            facts=facts,
            pack=pack,
            as_of_effective=as_of,
            as_of_knowledge=f"{as_of}T23:59:59Z",
            decision_attribute="resc:rescissionDeadline",
        )["decision"]["value"]["value"]
        funding = adjudicate(
            facts=facts,
            pack=pack,
            as_of_effective=as_of,
            as_of_knowledge=f"{as_of}T23:59:59Z",
            decision_attribute="resc:fundingPermitted",
        )
        permitted = funding["decision"]["value"]["value"]
        rules = ", ".join(r["ruleId"] for r in funding["rulesFired"])
        verdict = "CLEAR TO FUND" if permitted else "funding hold"
        print(f"asOf {as_of}  computed deadline: midnight of {deadline}  ->  {verdict}")
        print(f"    {label}")
        print(f"    rules fired: {rules}")

    # The protective default, for contrast: strip the notice-delivery fact
    # and the deadline cannot be computed at all — a loud no-decision, and
    # the funding hold survives even well past the would-be deadline.
    print()
    without_notice = [f for f in facts if f["attribute"] != "resc:noticeDeliveredDate"]
    try:
        adjudicate(
            facts=without_notice,
            pack=pack,
            as_of_effective="2026-06-30",
            as_of_knowledge="2026-06-30T23:59:59Z",
            decision_attribute="resc:rescissionDeadline",
        )
        raise SystemExit("expected a loud no-decision without the notice fact")
    except AdjudicationError as e:
        print(f"without the notice-delivery fact, the deadline question refuses: {e}")
    held = adjudicate(
        facts=without_notice,
        pack=pack,
        as_of_effective="2026-06-30",
        as_of_knowledge="2026-06-30T23:59:59Z",
        decision_attribute="resc:fundingPermitted",
    )
    assert held["decision"]["value"] == {"kind": "boolean", "value": False}
    print(
        "and funding stays held on 2026-06-30 by "
        + ", ".join(r["ruleId"] for r in held["rulesFired"])
        + " (protective default)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
