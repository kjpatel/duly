"""Golden-corpus generator: python -m duly_assurance generate.

Synthesizes adjudication cases from per-scenario templates, adjudicates each
with the reference kernel, and writes cases + receipts under the output
directory (golden/README.md is the authoritative contract).

Determinism contract:
- No wall-clock reads anywhere. Every timestamp is derived from the case's
  own synthetic dates.
- All randomness flows from `random.Random` streams seeded from --seed. Each
  template gets its own stream seeded from ``f"{seed}:{template_name}"`` so
  adding a template never disturbs another template's draws.
- Case ids are ``<id_prefix>-<counter:04d>`` (e.g. notice-ny-0001, trid-0001),
  assigned in draw order. Regeneration with the same seed and templates is
  byte-identical.

Redraw rule: if a drawn case raises AdjudicationError, that draw is invalid;
it is discarded and the next draw is taken from the *same* per-template RNG
stream while the case id stays fixed. Because the stream position only
depends on prior draws, the redraw is deterministic. Bounded at 20 attempts
per case id, after which generation aborts loudly.

Template registry: STATE_TEMPLATES is data, not code. Adding a state to the
notice scenario is a single registry line built by `notice_template()`, e.g.

    "fl": notice_template("US-FL", (5, 90)),

once the pack carries rules gated on that governingState.

Two draw styles, both deterministic:

- *Range templates* (notice, trid) draw every parameter from the per-template
  RNG over ranges wide enough to cross the pack's thresholds in both
  directions. Coverage of any single boundary is probabilistic.
- *Boundary-stratified templates* (ron, esign, resc, rec) carry a `strata`
  table: an explicit list of the boundary cells the pack encodes. The case
  counter picks the cell — cell ``(counter - 1) % len(strata)`` — and the RNG
  draws the magnitudes *inside* it (how far past a statutory commencement
  date, how many inches short of a margin, which confidence below a floor).
  With a quota at least as large as the table, every boundary is covered by
  construction rather than by luck, which is what makes the corpus a
  regression net for these packs. The stratum is fixed across the redraw
  loop, so every stratum must be able to produce a valid case (a stratum that
  always raised AdjudicationError would exhaust the redraw budget and abort).

A stratum may also name the `question` to ask, so one template covers several
of its pack's declared decisions: a pack whose decision attribute never
appears as a corpus question is outside the impact net for that attribute.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import yaml

from duly_kernel.api import adjudicate
from duly_kernel.engine import AdjudicationError
from duly_core import content_hash as _content_hash, load_schema

GENERATOR_NAME = "duly-golden-generator"
GENERATOR_VERSION = "0.1.0"

NOTICE_PACK = "rulepacks/termination-notice-us-states/pack.yaml"
TRID_PACK = "rulepacks/trid-fee-tolerance-us-federal/pack.yaml"
RON_PACK = "rulepacks/notarization-ron-us-states/pack.yaml"
ESIGN_PACK = "rulepacks/esign-closing-package/pack.yaml"
RESC_PACK = "rulepacks/tila-rescission-us-federal/pack.yaml"
RECORDING_PACK = "rulepacks/county-recording-us/pack.yaml"

# Synthetic policy expiration dates span this window (2025-2026) so that
# mailed dates (= asOf.effective) land on both sides of the pack's
# 2026-01-01 rule-version boundary (NY-NR-45-LEGACY vs NY-NR-45).
EXPIRATION_START = _dt.date(2025, 6, 1)
EXPIRATION_END = _dt.date(2026, 12, 31)


def notice_template(
    state: str,
    margin_days: tuple[int, int],
    *,
    nonpayment_share: float = 0.2,
) -> dict:
    """Registry entry for one state's termination-notice scenario.

    `state` is the ISO 3166-2 governing-state code (e.g. "US-NY");
    `margin_days` is the inclusive (low, high) range of days between the
    notice mailing date and the policy expiration, drawn uniformly so cases
    cross the pack's compliance thresholds in both directions.
    """
    return {
        "kind": "notice",
        "id_prefix": f"notice-{state.rsplit('-', 1)[-1].lower()}",
        "pack": NOTICE_PACK,
        "question": "nc:noticeCompliant",
        "ontology": "duly-starter-notice",
        "state": state,
        "notice_type": "Nonrenewal",
        "margin_days": margin_days,
        "nonpayment_share": nonpayment_share,
        "weight": 3,
    }


# ---------------------------------------------------------------------------
# Boundary strata (data): the decision boundaries each pack encodes
# ---------------------------------------------------------------------------

# The RON authorization dates the pack actually encodes, mirrored here only so
# draws can be placed on both sides of each one. The pack is the authority;
# this table is the generator's aim. US-GA carries NO authorization rule in
# the pack — its entry is a bare date pivot so Georgia cases spread over time
# while both sides fail closed under RON-DEF-00.
RON_AUTHORIZATION: dict[str, _dt.date] = {
    "US-VA": _dt.date(2012, 7, 1),   # 2011 Acts cc. 731, 834
    "US-TX": _dt.date(2018, 7, 1),   # HB 1217, 85th Leg.
    "US-FL": _dt.date(2020, 1, 1),   # ch. 2019-71, Laws of Fla.
    "US-NY": _dt.date(2023, 1, 31),  # Exec. Law § 135-c
    "US-CA": _dt.date(2030, 1, 1),   # SB 696 statutory outside operative date
    "US-GA": _dt.date(2021, 1, 1),   # no rule in the pack: pivot only
}

# How far from the pivot an as-of date is drawn (days). 1 puts a case on the
# statute's last non-authorized day / first authorized day.
RON_DATE_SPANS = (1, 31, 366, 1500)

# state x method x side of the authorization date, plus the two confidence
# cells for the pack's 0.9 floor on ron:notarizationMethod. `side` is relative
# to RON_AUTHORIZATION[state]: before / on the commencement day / after.
RON_STRATA: tuple[dict, ...] = (
    {"state": "US-VA", "side": "before", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-VA", "side": "on", "method": "RemoteOnline"},
    {"state": "US-VA", "side": "after", "method": "RemoteOnline"},
    {"state": "US-TX", "side": "before", "method": "RemoteOnline"},
    {"state": "US-TX", "side": "on", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-TX", "side": "after", "method": "RemoteOnline"},
    {"state": "US-FL", "side": "before", "method": "RemoteOnline"},
    {"state": "US-FL", "side": "on", "method": "RemoteOnline"},
    {"state": "US-FL", "side": "after", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-NY", "side": "before", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-NY", "side": "on", "method": "RemoteOnline"},
    {"state": "US-NY", "side": "after", "method": "RemoteOnline"},
    # California: signed law, not yet operative. `before` is every closing
    # adjudicated today (fails closed); `on`/`after` are the 2030 flip.
    {"state": "US-CA", "side": "before", "method": "RemoteOnline"},
    {"state": "US-CA", "side": "on", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-CA", "side": "after", "method": "RemoteOnline"},
    # Method guard: an in-person act is compliant even where RON is not
    # permitted (RON-COMP-01 is scoped to RemoteOnline).
    {"state": "US-CA", "side": "before", "method": "InPerson"},
    # Unauthorized jurisdiction: no rule for Georgia, so RON-DEF-00 answers on
    # both sides of the pivot.
    {"state": "US-GA", "side": "before", "method": "RemoteOnline", "question": "ron:ronPermitted"},
    {"state": "US-GA", "side": "after", "method": "RemoteOnline"},
    {"state": "US-GA", "side": "after", "method": "InPerson"},
    # Both sides of the 0.9 per-attribute floor on ron:notarizationMethod:
    # excluded, the deficiency rule cannot fire and the compliance
    # presumption decides; at the floor it binds and the deficiency stands.
    {"state": "US-FL", "side": "before", "method": "RemoteOnline", "method_confidence": "below_floor"},
    {"state": "US-FL", "side": "before", "method": "RemoteOnline", "method_confidence": "at_floor"},
)

# The effectiveFrom of the rule that governs each document type, so as-of
# dates can straddle it. EscrowInstructions matches no rule at all (the
# fail-safe path), so its pivot is just the reference closing date.
ESIGN_REFERENCE_DATE = _dt.date(2026, 7, 15)

ESIGN_PIVOTS: dict[str, _dt.date] = {
    "ClosingDisclosure": _dt.date(2015, 10, 3),   # PKG-CD-10/11 (TRID)
    "RightToCancelNotice": _dt.date(2011, 12, 30),  # PKG-RTC-20/21
    "PromissoryNote": _dt.date(2023, 12, 13),     # PKG-NOTE-31/32 (GSE eNote)
    "DeedOfTrust": _dt.date(2000, 10, 1),         # PKG-DOT-40 (ESIGN)
    "EscrowInstructions": ESIGN_REFERENCE_DATE,   # no rule: reference date
}

ESIGN_DATE_SPANS = (1, 30, 200, 900)

# The pack's routing matrix, one stratum per cell, crossed with the questions
# it declares (pkg:signingMethod, pkg:eSignEligible) and with the commencement
# date of the rule that decides the cell. `flag` names which corroborating
# fact the case carries: the ESIGN consumer consent, the MERS eRegistry
# registration, or neither.
ESIGN_STRATA: tuple[dict, ...] = (
    {"doc": "ClosingDisclosure", "flag": "consent", "value": True, "side": "before"},
    {"doc": "ClosingDisclosure", "flag": "consent", "value": True, "side": "on"},
    {"doc": "ClosingDisclosure", "flag": "consent", "value": True, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "ClosingDisclosure", "flag": "consent", "value": False, "side": "reference"},
    {"doc": "ClosingDisclosure", "flag": "consent", "value": False, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "RightToCancelNotice", "flag": "consent", "value": True, "side": "before"},
    {"doc": "RightToCancelNotice", "flag": "consent", "value": True, "side": "on"},
    {"doc": "RightToCancelNotice", "flag": "consent", "value": True, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "RightToCancelNotice", "flag": "consent", "value": False, "side": "reference"},
    {"doc": "PromissoryNote", "flag": "registered", "value": True, "side": "before"},
    {"doc": "PromissoryNote", "flag": "registered", "value": True, "side": "on"},
    {"doc": "PromissoryNote", "flag": "registered", "value": True, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "PromissoryNote", "flag": "registered", "value": False, "side": "reference"},
    {"doc": "PromissoryNote", "flag": "registered", "value": False, "side": "reference",
     "question": "pkg:eSignEligible"},
    # A note with consumer consent but no registration fact: consent does not
    # satisfy the transferable-record control requirement.
    {"doc": "PromissoryNote", "flag": "consent", "value": True, "side": "reference"},
    {"doc": "DeedOfTrust", "flag": "consent", "value": True, "side": "reference"},
    {"doc": "DeedOfTrust", "flag": "consent", "value": True, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "DeedOfTrust", "flag": "consent", "value": True, "side": "before"},
    {"doc": "DeedOfTrust", "flag": "consent", "value": False, "side": "reference"},
    # The unknown-document-type fail-safe, with and without consent.
    {"doc": "EscrowInstructions", "flag": "consent", "value": True, "side": "reference"},
    {"doc": "EscrowInstructions", "flag": "consent", "value": True, "side": "reference",
     "question": "pkg:eSignEligible"},
    {"doc": "EscrowInstructions", "flag": "consent", "value": False, "side": "reference"},
)

# Consummation dates (all 2026, all weekdays, none itself a federal holiday)
# grouped by what the three-business-day rescission window that FOLLOWS the
# latest trigger contains under 12 CFR 1026.2(a)(6). Every date is verified by
# assurance/tests/test_generate.py against add_business_days(), so a wrong
# entry fails the suite rather than quietly weakening the corpus:
#   both     — a Sunday AND a 5 U.S.C. 6103(a) holiday: 5 calendar days
#   sunday   — a Sunday only: 4 calendar days (Saturday counts!)
#   holiday  — a holiday only, no Sunday: 4 calendar days
#   neither  — neither: exactly 3 calendar days, the naive-arithmetic case
RESC_CALENDARS: dict[str, tuple[str, ...]] = {
    "both": ("2026-01-15", "2026-02-12", "2026-05-22"),
    "sunday": ("2026-02-26", "2026-04-02", "2026-05-07", "2026-09-11"),
    "holiday": ("2026-06-16", "2026-11-09", "2026-11-23"),
    "neither": ("2026-01-05", "2026-03-24", "2026-05-04", "2026-10-14"),
}

RESC_WELL_AFTER_SPANS = (2, 5, 11, 30)

# TILA rescission strata. `calendar` picks the window shape (above);
# `trigger` says which of the three 1026.23(a)(3)(i) triggers is the latest
# (the drawn calendar date is always the latest one, so the window shape
# holds); `as_of` places the evaluation point relative to the deadline.
RESC_STRATA: tuple[dict, ...] = (
    # The centerpiece window: Sunday + Memorial Day inside it. Naive
    # 3-calendar-day math would fund on latest+4; the pack must not.
    {"calendar": "both", "trigger": "same_day", "as_of": "consummation"},
    {"calendar": "both", "trigger": "same_day", "as_of": "naive_plus_1"},
    {"calendar": "both", "trigger": "same_day", "as_of": "at_deadline"},
    {"calendar": "both", "trigger": "same_day", "as_of": "after_deadline"},
    {"calendar": "both", "trigger": "same_day", "as_of": "well_after"},
    {"calendar": "both", "trigger": "same_day", "as_of": "after_deadline",
     "question": "resc:rescissionDeadline"},
    {"calendar": "both", "trigger": "same_day", "as_of": "after_deadline",
     "question": "resc:rescissionApplies"},
    {"calendar": "sunday", "trigger": "same_day", "as_of": "at_deadline"},
    {"calendar": "sunday", "trigger": "same_day", "as_of": "after_deadline",
     "question": "resc:rescissionDeadline"},
    {"calendar": "sunday", "trigger": "same_day", "as_of": "naive_plus_1"},
    # No holiday after_deadline cell: after-deadline funding is covered on the
    # "both" and "sunday" calendars, and the table must not exceed the resc
    # quota (25) or its tail cells would never be drawn.
    {"calendar": "holiday", "trigger": "same_day", "as_of": "at_deadline"},
    {"calendar": "holiday", "trigger": "same_day", "as_of": "naive_plus_1"},
    {"calendar": "neither", "trigger": "same_day", "as_of": "at_deadline"},
    {"calendar": "neither", "trigger": "same_day", "as_of": "after_deadline",
     "question": "resc:rescissionDeadline"},
    # The "whichever occurs last" arm: notice, then material disclosures.
    {"calendar": "both", "trigger": "notice_last", "as_of": "in_window"},
    {"calendar": "neither", "trigger": "notice_last", "as_of": "after_deadline",
     "question": "resc:rescissionDeadline"},
    {"calendar": "sunday", "trigger": "disclosures_last", "as_of": "in_window"},
    {"calendar": "both", "trigger": "disclosures_last", "as_of": "after_deadline",
     "question": "resc:rescissionDeadline"},
    # Purchase money: a residential mortgage transaction is exempt, so there
    # is no notice, no deadline, and no funding delay.
    {"calendar": "neither", "trigger": "same_day", "as_of": "after_deadline",
     "transaction_type": "Purchase", "notice": False, "question": "resc:rescissionApplies"},
    {"calendar": "both", "trigger": "same_day", "as_of": "after_deadline",
     "transaction_type": "Purchase", "notice": False},
    {"calendar": "sunday", "trigger": "same_day", "as_of": "well_after",
     "transaction_type": "Purchase", "notice": False},
    # Not the consumer's principal dwelling: outside 1026.23(a)(1) entirely.
    {"calendar": "neither", "trigger": "same_day", "as_of": "after_deadline",
     "dwelling": False, "notice": False, "question": "resc:rescissionApplies"},
    # Same, but evaluated inside the would-be window: rescission does not
    # apply, so no deadline is derived, RESC-FUND-STAY cannot bind, and
    # RESC-FUND-NA answers even on a day the hold would otherwise cover.
    {"calendar": "both", "trigger": "same_day", "as_of": "in_window", "dwelling": False},
    # The protective default: no notice-delivery fact, so no deadline can be
    # computed and nothing can show the period expired even long past the
    # would-be deadline.
    {"calendar": "both", "trigger": "same_day", "as_of": "well_after", "notice": False,
     "disclosures": True},
    # A misprinted notice (printed date 2 calendar days after the latest
    # trigger — impossible under any business-day calendar): the pack
    # computes the deadline itself, so the misprint changes nothing; the
    # printed-date fact rides along unconsumed.
    {"calendar": "both", "trigger": "same_day", "as_of": "in_window",
     "stated_deadline": "impossible"},
)

# The first-page reservation each encoded jurisdiction requires, mirrored from
# the pack so draws land on both sides of it. The pack is the authority.
REC_REQUIRED_TOP_SPACE: dict[str, str] = {"US-CA": "2.5", "US-AZ": "2.0"}

REC_TOP_SPACE_OVER = ("0.1", "0.2", "0.5", "1.0")
REC_TOP_SPACE_UNDER = ("0.1", "0.3", "0.5", "0.9")
# Below the 0.85 per-attribute floor on rec:firstPageTopSpaceInches. 0.80 and
# 0.84 clear the pack's 0.75 default and still abstain — the override is what
# excludes them.
REC_CONFIDENCE_BELOW_FLOOR = (0.58, 0.72, 0.80, 0.84)
REC_CONFIDENCE_ABOVE_FLOOR = (0.90, 0.95, 0.99)
# Below the pack default floor of 0.75, applied to a boolean read off the
# document face (rec:coverPageAttached carries no per-attribute override).
REC_CONFIDENCE_BELOW_DEFAULT = (0.61, 0.70, 0.74)

REC_REFERENCE_DATE = _dt.date(2026, 8, 20)
REC_DATE_SPANS = (1, 45, 400)

# County-recording strata. `top_space` is relative to the jurisdiction's
# requirement (over / at / under); `as_of` is the reference closing date
# unless it names a rule commencement to sit before. Only US-CA and US-AZ
# appear: the pack grants a recordability presumption to those two only, and
# any other state is a deliberate no-decision (fail closed by absence), which
# a corpus case cannot carry — see golden/README.md.
REC_STRATA: tuple[dict, ...] = (
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "concurrent": True},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "at", "cover": False,
     "concurrent": True},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "concurrent": True},
    # The statutory cure: a compliant separate sheet attached.
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "under", "cover": True,
     "concurrent": True},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "concurrent": True, "question": "rec:sb2FeeDueUSD"},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "concurrent": False, "question": "rec:sb2FeeDueUSD"},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "question": "rec:sb2FeeDueUSD"},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "concurrent": True, "question": "rec:requiredFirstPageTopSpaceInches"},
    # Rev. & Tax. Code § 11933: a grant deed with no transfer-tax declaration
    # on its face cannot be recorded, however well formatted.
    {"state": "US-CA", "instrument": "GrantDeed", "top_space": "over", "cover": False,
     "concurrent": False, "declaration": False},
    {"state": "US-CA", "instrument": "GrantDeed", "top_space": "over", "cover": False,
     "concurrent": False, "declaration": True},
    {"state": "US-CA", "instrument": "GrantDeed", "top_space": "over", "cover": False,
     "concurrent": False},
    {"state": "US-CA", "instrument": "GrantDeed", "top_space": "over", "cover": False,
     "concurrent": False, "declaration": False, "as_of": "before_dtt"},
    {"state": "US-CA", "instrument": "GrantDeed", "top_space": "over", "cover": False,
     "concurrent": True, "declaration": True, "question": "rec:sb2FeeDueUSD"},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "concurrent": True, "as_of": "before_sb2"},
    # Both sides of the 0.85 floor on the measured inches. Below it the
    # measurement abstains (routed to recording-review) and the presumption
    # survives; at the floor it binds and the deficiency stands.
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "concurrent": True, "top_space_confidence": "below_floor"},
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "concurrent": True, "top_space_confidence": "at_floor"},
    # Two abstentions in one receipt: the measurement below its 0.85
    # override and the cover-page boolean below the 0.75 pack default.
    {"state": "US-CA", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "concurrent": True, "top_space_confidence": "below_floor",
     "cover_confidence": "below_default"},
    # Arizona: the long-tail contrast. The same measurement that fails in
    # California passes under A.R.S. § 11-480(B)'s 2 inch margin.
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "over", "cover": False},
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "at", "cover": False},
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "under", "cover": False},
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "under", "cover": True},
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "over", "cover": False,
     "question": "rec:requiredFirstPageTopSpaceInches"},
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "top_space_confidence": "below_floor"},
    # § 11933 is California-only, so an Arizona grant deed needs no
    # transfer-tax declaration.
    {"state": "US-AZ", "instrument": "GrantDeed", "top_space": "over", "cover": False},
    # Before A.R.S. § 11-480's own 1991 commencement no requirement is
    # concluded, so the deficiency rule cannot bind its derived premise.
    {"state": "US-AZ", "instrument": "DeedOfTrust", "top_space": "under", "cover": False,
     "as_of": "before_az"},
)


# Template registry: adding a scenario variant is adding a data entry here,
# not code. Notice-state entries are one line each via notice_template();
# stratified entries point at a `strata` table above.
STATE_TEMPLATES: dict[str, dict] = {
    "ny": notice_template("US-NY", (5, 90)),
    # Margin ranges cross each state's statutory threshold both ways
    # (NY 45, FL 120, CA 75 days).
    "fl": notice_template("US-FL", (30, 180)),
    "ca": notice_template("US-CA", (15, 140)),
    "trid": {
        "kind": "trid",
        "id_prefix": "trid",
        "pack": TRID_PACK,
        "question": "trid:toleranceCureAmount",
        "ontology": "duly-mortgage-closing",
        "as_of_effective": "2026-03-15",
        "weight": 1,
    },
    "ron": {
        "kind": "ron",
        "id_prefix": "ron",
        "pack": RON_PACK,
        "question": "ron:notarizationCompliant",
        "ontology": "duly-mortgage-closing",
        "strata": RON_STRATA,
        "weight": 1,
    },
    "esign": {
        "kind": "esign",
        "id_prefix": "esign",
        "pack": ESIGN_PACK,
        "question": "pkg:signingMethod",
        "ontology": "duly-mortgage-closing",
        "strata": ESIGN_STRATA,
        "weight": 1,
    },
    "resc": {
        "kind": "resc",
        "id_prefix": "resc",
        "pack": RESC_PACK,
        "question": "resc:fundingPermitted",
        "ontology": "duly-mortgage-closing",
        "strata": RESC_STRATA,
        "weight": 1,
    },
    "rec": {
        "kind": "rec",
        "id_prefix": "rec",
        "pack": RECORDING_PACK,
        "question": "rec:recordable",
        "ontology": "duly-mortgage-closing",
        "strata": REC_STRATA,
        "weight": 1,
    },
}


def stratum_for(template: dict, index: int) -> dict:
    """The boundary cell a stratified template uses for case number `index`
    (1-based). Cells cycle, so a quota at least as large as the table covers
    every boundary; a smaller quota covers a prefix of it."""
    strata = template["strata"]
    return strata[(index - 1) % len(strata)]


# ---------------------------------------------------------------------------
# Canonicalization + content addressing (mirrors spec/validate.py)
# ---------------------------------------------------------------------------


def content_hash(doc: dict, hash_field: str = "contentHash") -> str:
    """Content hash, defaulting to a fact's field — this module builds facts."""
    return _content_hash(doc, hash_field)


# ---------------------------------------------------------------------------
# Fact construction
# ---------------------------------------------------------------------------


def make_fact(
    case_ref: str,
    entity_id: str,
    entity_type: str,
    attribute: str,
    value: dict,
    ontology: str,
    ts: str,
    *,
    confidence: dict | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> dict:
    """Build a schema-valid GroundedFact for the synthetic corpus.

    Grounding is an honest attestation (this corpus does not fake source
    documents); the assertion is a machine assertion by the generator; all
    timestamps are the derived per-case timestamp `ts` (no wall clock).
    `confidence` defaults to a fully-confident raw score; low-confidence
    templates pass an explicit score to exercise the pack abstention policy.
    `effective_from` / `effective_to` carry a bounded-truth window ([from, to),
    RFC 3339 stamps) for facts that are only true over an interval, such as
    the TILA rescission-period windows.
    """
    doc = {
        "caseId": case_ref,
        "entity": {"id": entity_id, "type": entity_type},
        "attribute": attribute,
        "value": value,
        "grounding": {
            "kind": "attestation",
            "actor": "golden-generator",
            "channel": "synthetic",
            "at": ts,
        },
        "assertion": {
            "kind": "machine",
            "at": ts,
            "extractor": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        },
        "confidence": confidence if confidence is not None else {"score": 1.0, "method": "raw"},
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": {"ontology": ontology, "version": "0.1.0"},
    }
    if effective_from is not None:
        doc["effectiveFrom"] = effective_from
    if effective_to is not None:
        doc["effectiveTo"] = effective_to
    digest = content_hash(doc)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **doc}


def build_notice_facts(
    template: dict,
    case_id: str,
    *,
    expiration: _dt.date,
    margin: int,
    nonpayment: bool,
    mailed_confidence: dict | None = None,
    expiration_confidence: dict | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one termination-notice case.

    The notice is mailed `margin` days before `expiration`; asOf.effective is
    the mailed date, asOf.knowledge two days later. The optional confidence
    overrides exercise the pack's abstentionPolicy (mailed date carries a
    per-attribute floor, expiration date the pack default).
    """
    mailed = expiration - _dt.timedelta(days=margin)
    ts = f"{mailed.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    notice_id = f"notice:{case_id}"
    policy_id = f"policy:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, notice_id, "nc:TerminationNotice", "nc:noticeType",
            {
                "kind": "code",
                "value": template["notice_type"],
                "codeSystem": "duly-starter-notice/notice-types",
                "codeSystemVersion": "0.1.0",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, notice_id, "nc:TerminationNotice", "nc:noticeMailedDate",
            {"kind": "date", "value": mailed.isoformat()},
            ontology, ts,
            confidence=mailed_confidence,
        ),
        make_fact(
            case_ref, policy_id, "nc:Policy", "nc:governingState",
            {
                "kind": "code",
                "value": template["state"],
                "codeSystem": "iso-3166-2",
                "codeSystemVersion": "2020",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, policy_id, "nc:Policy", "nc:policyExpirationDate",
            {"kind": "date", "value": expiration.isoformat()},
            ontology, ts,
            confidence=expiration_confidence,
        ),
    ]
    if nonpayment:
        facts.append(
            make_fact(
                case_ref, notice_id, "nc:TerminationNotice", "nc:terminationGround",
                {
                    "kind": "code",
                    "value": "Nonpayment",
                    "codeSystem": "duly-starter-notice/termination-grounds",
                    "codeSystemVersion": "0.1.0",
                },
                ontology, ts,
            )
        )
    as_of_effective = mailed.isoformat()
    as_of_knowledge = f"{(mailed + _dt.timedelta(days=2)).isoformat()}T12:00:00Z"
    return facts, as_of_effective, as_of_knowledge


def draw_notice_params(template: dict, rng: random.Random) -> dict:
    span = (EXPIRATION_END - EXPIRATION_START).days
    lo, hi = template["margin_days"]
    params = {
        "expiration": EXPIRATION_START + _dt.timedelta(days=rng.randrange(span + 1)),
        "margin": rng.randint(lo, hi),
        "nonpayment": rng.random() < template["nonpayment_share"],
    }
    # Confidence draws exercising the pack's abstentionPolicy
    # (nc:noticeMailedDate floor 0.9 per-attribute, default 0.75), on both
    # sides of each boundary. None = the make_fact default (1.0 raw).
    r = rng.random()
    if r < 0.05:
        # Below the per-attribute floor AND the pack default: excluded.
        params["mailed_confidence"] = {"score": 0.6, "method": "platt"}
    elif r < 0.10:
        # Above the 0.75 default but below the 0.9 override: excluded only
        # because the per-attribute floor beats the default.
        params["mailed_confidence"] = {"score": 0.85, "method": "platt"}
    elif r < 0.15:
        # Exactly at the per-attribute floor: binds (at-floor is inclusive).
        params["mailed_confidence"] = {"score": 0.9, "method": "platt"}
    else:
        params["mailed_confidence"] = None
    r = rng.random()
    if r < 0.04:
        # Below the pack default floor (no override on this attribute): excluded.
        params["expiration_confidence"] = {"score": 0.7, "method": "temperature"}
    elif r < 0.08:
        # Exactly at the default floor: binds.
        params["expiration_confidence"] = {"score": 0.75, "method": "temperature"}
    else:
        params["expiration_confidence"] = None
    return params


def _cents(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}"


def build_trid_facts(
    template: dict,
    case_id: str,
    *,
    disclosed_cents: int,
    actual_cents: int,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one TRID transfer-tax tolerance case."""
    closing = _dt.date.fromisoformat(template["as_of_effective"])
    ts = f"{closing.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    fee_id = f"fee:transfer-tax:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:feeType",
            {
                "kind": "code",
                "value": "TransferTax",
                "codeSystem": "duly-starter-trid/fee-types",
                "codeSystemVersion": "0.1.0",
            },
            ontology, ts,
        ),
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:disclosedAmountAtBaseline",
            {"kind": "money", "amount": _cents(disclosed_cents), "currency": "USD"},
            ontology, ts,
        ),
        make_fact(
            case_ref, fee_id, "trid:Fee", "trid:actualAmountAtClosing",
            {"kind": "money", "amount": _cents(actual_cents), "currency": "USD"},
            ontology, ts,
        ),
    ]
    as_of_effective = closing.isoformat()
    as_of_knowledge = f"{(closing + _dt.timedelta(days=2)).isoformat()}T12:00:00Z"
    return facts, as_of_effective, as_of_knowledge


def draw_trid_params(template: dict, rng: random.Random) -> dict:
    disclosed = rng.randint(20000, 480000)  # $200.00 .. $4800.00 in cents
    r = rng.random()
    if r < 0.45:  # increase (including small ones near the baseline)
        actual = disclosed + rng.randint(1, 60000)
    elif r < 0.75:  # equal
        actual = disclosed
    else:  # decrease
        actual = disclosed - rng.randint(1, min(disclosed - 100, 40000))
    return {"disclosed_cents": disclosed, "actual_cents": actual}


def _code(value: str, code_system: str, version: str = "0.1.0") -> dict:
    return {
        "kind": "code",
        "value": value,
        "codeSystem": code_system,
        "codeSystemVersion": version,
    }


def _as_of_points(as_of: _dt.date) -> tuple[str, str]:
    """The (effective, knowledge) pair for a case evaluated on `as_of`:
    effective is the date itself, knowledge two days later (the same
    convention the notice and TRID templates use)."""
    return as_of.isoformat(), f"{(as_of + _dt.timedelta(days=2)).isoformat()}T12:00:00Z"


# ---------------------------------------------------------------------------
# RON: remote online notarization authorization, state by state
# ---------------------------------------------------------------------------


def build_ron_facts(
    template: dict,
    case_id: str,
    *,
    state: str,
    method: str,
    as_of: _dt.date,
    method_confidence: dict | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one RON closing.

    asOf.effective is the closing date: it is the dial that decides whether a
    state's authorization statute was in force, which is the whole point of
    this pack. `method_confidence` exercises the pack's 0.9 floor on
    ron:notarizationMethod.
    """
    ts = f"{as_of.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    notarization_id = f"notarization:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, notarization_id, "ron:Notarization", "ron:governingState",
            _code(state, "iso-3166-2", "2020"), ontology, ts,
        ),
        make_fact(
            case_ref, notarization_id, "ron:Notarization", "ron:notarizationMethod",
            _code(method, "duly-starter-ron/notarization-methods"), ontology, ts,
            confidence=method_confidence,
        ),
    ]
    eff, kn = _as_of_points(as_of)
    return facts, eff, kn


def draw_ron_params(template: dict, rng: random.Random, index: int) -> dict:
    stratum = stratum_for(template, index)
    pivot = RON_AUTHORIZATION[stratum["state"]]
    span = rng.choice(RON_DATE_SPANS)
    side = stratum["side"]
    if side == "before":
        as_of = pivot - _dt.timedelta(days=span)
    elif side == "on":
        as_of = pivot
    else:
        as_of = pivot + _dt.timedelta(days=span)
    params: dict = {"state": stratum["state"], "method": stratum["method"], "as_of": as_of}
    floor = stratum.get("method_confidence")
    if floor == "below_floor":
        # 0.88 clears the pack default of 0.75 and still abstains: the
        # per-attribute override is what excludes it.
        params["method_confidence"] = {"score": rng.choice((0.62, 0.74, 0.88)), "method": "platt"}
    elif floor == "at_floor":
        params["method_confidence"] = {"score": 0.9, "method": "platt"}
    else:
        params["method_confidence"] = None
    if "question" in stratum:
        params["question"] = stratum["question"]
    return params


# ---------------------------------------------------------------------------
# eSign: closing-package signing-channel routing
# ---------------------------------------------------------------------------


def build_esign_facts(
    template: dict,
    case_id: str,
    *,
    document_type: str,
    as_of: _dt.date,
    consent: bool | None = None,
    enote_registered: bool | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one closing-package document.

    One pkg:SigningTask entity per case (the rule-IR v0 one-entity-per-type
    constraint), with the document's type carried as an attribute. Exactly one
    corroborating fact is present — the ESIGN consumer consent or the MERS
    eRegistry registration — mirroring the pack's fixtures; `None` means the
    fact is absent, which is a distinct outcome from `False`.
    """
    ts = f"{as_of.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    task_id = f"task:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, task_id, "pkg:SigningTask", "pkg:documentType",
            _code(document_type, "duly-starter-esign/document-types"), ontology, ts,
        ),
    ]
    if consent is not None:
        facts.append(
            make_fact(
                case_ref, task_id, "pkg:SigningTask", "pkg:esignConsentObtained",
                {"kind": "boolean", "value": consent}, ontology, ts,
            )
        )
    if enote_registered is not None:
        facts.append(
            make_fact(
                case_ref, task_id, "pkg:SigningTask", "pkg:eNoteRegistered",
                {"kind": "boolean", "value": enote_registered}, ontology, ts,
            )
        )
    eff, kn = _as_of_points(as_of)
    return facts, eff, kn


def draw_esign_params(template: dict, rng: random.Random, index: int) -> dict:
    stratum = stratum_for(template, index)
    document_type = stratum["doc"]
    span = rng.choice(ESIGN_DATE_SPANS)
    side = stratum["side"]
    if side == "before":
        as_of = ESIGN_PIVOTS[document_type] - _dt.timedelta(days=span)
    elif side == "on":
        as_of = ESIGN_PIVOTS[document_type]
    else:  # a present-day closing, well clear of every commencement date
        as_of = ESIGN_REFERENCE_DATE + _dt.timedelta(days=span)
    params: dict = {"document_type": document_type, "as_of": as_of}
    if stratum["flag"] == "consent":
        params["consent"] = stratum["value"]
    else:
        params["enote_registered"] = stratum["value"]
    if "question" in stratum:
        params["question"] = stratum["question"]
    return params


# ---------------------------------------------------------------------------
# TILA rescission: the precise business-day calendar of 12 CFR 1026.2(a)(6)
# ---------------------------------------------------------------------------


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """The nth `weekday` (Monday = 0) of a month."""
    first = _dt.date(year, month, 1)
    return first + _dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    """The last `weekday` of a month (e.g. the last Monday in May)."""
    next_month = _dt.date(year + (month == 12), month % 12 + 1, 1)
    last = next_month - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def federal_holidays(year: int) -> frozenset[_dt.date]:
    """The legal public holidays of 5 U.S.C. 6103(a), on their statutory dates.

    12 CFR 1026.2(a)(6)'s *precise* business-day definition — the one
    1026.23 rescission uses — excludes "Sundays and the legal public holidays
    specified in 5 U.S.C. 6103(a)". Specified there, not as observed: Official
    Staff Commentary 2(a)(6)-2 says that when a date-specified holiday falls
    on a Saturday, the substitute day federal offices observe (the preceding
    Friday) IS a business day. So no 6103(b) observance shifting happens here,
    and Saturdays always count.

    Juneteenth (June 19) only became a legal public holiday on 2021-06-17
    (Pub. L. 117-17). Rather than silently apply the modern calendar to older
    years, this refuses them; every date the corpus draws is in 2026.
    """
    if year < 2021:
        raise ValueError(
            f"federal_holidays({year}): the pre-Juneteenth holiday calendar is "
            "not modeled; rescission draws are confined to 2026"
        )
    return frozenset({
        _dt.date(year, 1, 1),               # New Year's Day
        _nth_weekday(year, 1, 0, 3),        # Birthday of Martin Luther King, Jr.
        _nth_weekday(year, 2, 0, 3),        # Washington's Birthday
        _last_weekday(year, 5, 0),          # Memorial Day
        _dt.date(year, 6, 19),              # Juneteenth
        _dt.date(year, 7, 4),               # Independence Day
        _nth_weekday(year, 9, 0, 1),        # Labor Day
        _nth_weekday(year, 10, 0, 2),       # Columbus Day
        _dt.date(year, 11, 11),             # Veterans Day
        _nth_weekday(year, 11, 3, 4),       # Thanksgiving Day
        _dt.date(year, 12, 25),             # Christmas Day
    })


def is_business_day(day: _dt.date) -> bool:
    """True unless `day` is a Sunday or a 5 U.S.C. 6103(a) holiday."""
    return day.weekday() != 6 and day not in federal_holidays(day.year)


def add_business_days(start: _dt.date, count: int) -> _dt.date:
    """The `count`-th business day after `start` under 1026.2(a)(6)."""
    day = start
    remaining = count
    while remaining:
        day += _dt.timedelta(days=1)
        if is_business_day(day):
            remaining -= 1
    return day


def build_resc_facts(
    template: dict,
    case_id: str,
    *,
    consummation: _dt.date,
    transaction_type: str,
    principal_dwelling: bool,
    as_of: _dt.date,
    notice_delivered: _dt.date | None = None,
    disclosures_delivered: _dt.date | None = None,
    stated_deadline: _dt.date | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one TILA rescission case.

    Since pack 2026.2.0 the deadline is COMPUTED by RESC-DL-01 over the
    pack-embedded `tila-precise` calendar, and the funding flip compares the
    computed deadline against the asOf date (an `asOf: effective` binding) —
    so the case carries only the trigger-date facts, not the old
    extraction-derived rescission-period window facts.

    resc:statedRescissionDeadline — the date printed in the H-8 notice's
    "final date to cancel" blank — is still emitted when a notice was
    delivered: it mirrors what a real extraction run reads off the document,
    and the `stated_deadline: impossible` stratum uses it to prove a
    misprinted notice can no longer mislead the deadline decision (no rule
    consumes the printed date; receipts never list it as an input fact).

    The business-day arithmetic in this module (add_business_days /
    federal_holidays) stays deliberately independent of the kernel's: it
    seeds the draws and cross-checks the pack's embedded calendar in
    assurance/tests/test_generate.py.
    """
    ts = f"{consummation.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    loan_id = f"loan:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, loan_id, "resc:Loan", "resc:consummationDate",
            {"kind": "date", "value": consummation.isoformat()}, ontology, ts,
        ),
        make_fact(
            case_ref, loan_id, "resc:Loan", "resc:transactionType",
            _code(transaction_type, "duly-starter-resc/transaction-types"), ontology, ts,
        ),
        make_fact(
            case_ref, loan_id, "resc:Loan", "resc:securedByPrincipalDwelling",
            {"kind": "boolean", "value": principal_dwelling}, ontology, ts,
        ),
    ]
    if notice_delivered is not None:
        facts.append(
            make_fact(
                case_ref, loan_id, "resc:Loan", "resc:noticeDeliveredDate",
                {"kind": "date", "value": notice_delivered.isoformat()}, ontology, ts,
            )
        )
    if disclosures_delivered is not None:
        facts.append(
            make_fact(
                case_ref, loan_id, "resc:Loan", "resc:materialDisclosuresDeliveredDate",
                {"kind": "date", "value": disclosures_delivered.isoformat()}, ontology, ts,
            )
        )
    if stated_deadline is not None:
        facts.append(
            make_fact(
                case_ref, loan_id, "resc:Loan", "resc:statedRescissionDeadline",
                {"kind": "date", "value": stated_deadline.isoformat()}, ontology, ts,
            )
        )
    eff, kn = _as_of_points(as_of)
    return facts, eff, kn


def draw_resc_params(template: dict, rng: random.Random, index: int) -> dict:
    stratum = stratum_for(template, index)
    # The drawn date is always the LATEST of the three 1026.23(a)(3)(i)
    # triggers, so the window shape promised by `calendar` holds whichever
    # trigger occurs last.
    latest = _dt.date.fromisoformat(rng.choice(RESC_CALENDARS[stratum["calendar"]]))
    trigger = stratum["trigger"]
    if trigger == "notice_last":
        consummation = latest - _dt.timedelta(days=2)
        notice_delivered = latest
        disclosures_delivered = latest - _dt.timedelta(days=1)
    elif trigger == "disclosures_last":
        consummation = latest - _dt.timedelta(days=3)
        notice_delivered = consummation
        disclosures_delivered = latest
    else:  # same_day: consummation, notice, and disclosures all on one day
        consummation = notice_delivered = disclosures_delivered = latest

    has_notice = stratum.get("notice", True)
    if not stratum.get("disclosures", has_notice):
        disclosures_delivered = None
    if stratum.get("stated_deadline") == "impossible":
        # Two calendar days after the latest trigger: no business-day
        # calendar could print this lawfully. The pack computes the deadline
        # itself, so the misprint must not change any decision — the case
        # proves the printed date is out of the loop.
        stated_deadline = latest + _dt.timedelta(days=2)
    else:
        stated_deadline = add_business_days(latest, 3)
    if not has_notice:
        # No notice delivered means no printed deadline to extract (and the
        # pack cannot compute one: RESC-DL-01 cannot bind its trigger dates).
        notice_delivered = None
        stated_deadline = None

    # asOf placement is relative to the TRUE deadline the pack computes —
    # not the printed date, which may deliberately be a misprint.
    base = add_business_days(latest, 3) if has_notice else latest
    mode = stratum["as_of"]
    span = rng.choice(RESC_WELL_AFTER_SPANS)
    if mode == "consummation":
        as_of = consummation
    elif mode == "naive_plus_1":
        # The day after a NAIVE three-calendar-day deadline: a weekday-only or
        # calendar-day implementation disburses here, wrongly.
        as_of = latest + _dt.timedelta(days=4)
    elif mode == "in_window":
        as_of = base - _dt.timedelta(days=1)
    elif mode == "at_deadline":
        as_of = base
    elif mode == "after_deadline":
        as_of = base + _dt.timedelta(days=1)
    else:  # well_after
        as_of = base + _dt.timedelta(days=span)

    params: dict = {
        "consummation": consummation,
        "transaction_type": stratum.get("transaction_type", "Refinance"),
        "principal_dwelling": stratum.get("dwelling", True),
        "notice_delivered": notice_delivered,
        "disclosures_delivered": disclosures_delivered,
        "stated_deadline": stated_deadline,
        "as_of": as_of,
    }
    if "question" in stratum:
        params["question"] = stratum["question"]
    return params


# ---------------------------------------------------------------------------
# County recording: format, transfer-tax, and SB 2 fee readiness
# ---------------------------------------------------------------------------


def build_rec_facts(
    template: dict,
    case_id: str,
    *,
    state: str,
    instrument_type: str,
    top_space: str,
    cover_page: bool,
    as_of: _dt.date,
    concurrent: bool | None = None,
    declaration: bool | None = None,
    top_space_confidence: dict | None = None,
    cover_page_confidence: dict | None = None,
) -> tuple[list[dict], str, str]:
    """Facts + asOf points for one county recording submission.

    `top_space` is the measured first-page top space in inches, as a decimal
    string. It is the one MEASURED quantity here, so it is the one that
    carries a calibrated confidence and can fall below the pack's 0.85
    per-attribute floor; the codes and booleans read off the document face
    stay fully confident unless a stratum says otherwise. `concurrent` and
    `declaration` are `None` when the fact is simply absent, which is a
    distinct outcome from `False`.
    """
    ts = f"{as_of.isoformat()}T12:00:00Z"
    case_ref = f"case:golden:{case_id}"
    submission_id = f"submission:{case_id}"
    ontology = template["ontology"]
    facts = [
        make_fact(
            case_ref, submission_id, "rec:RecordingSubmission", "rec:recordingState",
            _code(state, "iso-3166-2", "2020"), ontology, ts,
        ),
        make_fact(
            case_ref, submission_id, "rec:RecordingSubmission", "rec:instrumentType",
            _code(instrument_type, "duly-starter-recording/instrument-types"), ontology, ts,
        ),
        make_fact(
            case_ref, submission_id, "rec:RecordingSubmission", "rec:firstPageTopSpaceInches",
            {"kind": "decimal", "value": top_space}, ontology, ts,
            confidence=top_space_confidence,
        ),
        make_fact(
            case_ref, submission_id, "rec:RecordingSubmission", "rec:coverPageAttached",
            {"kind": "boolean", "value": cover_page}, ontology, ts,
            confidence=cover_page_confidence,
        ),
    ]
    if concurrent is not None:
        facts.append(
            make_fact(
                case_ref, submission_id, "rec:RecordingSubmission",
                "rec:concurrentWithTaxedTransfer",
                {"kind": "boolean", "value": concurrent}, ontology, ts,
            )
        )
    if declaration is not None:
        facts.append(
            make_fact(
                case_ref, submission_id, "rec:RecordingSubmission",
                "rec:transferTaxDeclarationPresent",
                {"kind": "boolean", "value": declaration}, ontology, ts,
            )
        )
    eff, kn = _as_of_points(as_of)
    return facts, eff, kn


# Rule commencements a recording stratum can sit before.
REC_RULE_DATES: dict[str, _dt.date] = {
    "before_dtt": _dt.date(2015, 1, 1),   # CA-DTT-11933 (face declaration)
    "before_sb2": _dt.date(2018, 1, 1),   # CA-SB2-75 (Building Homes and Jobs Act)
    "before_az": _dt.date(1991, 1, 1),    # AZ-TOPMARGIN-20 (A.R.S. § 11-480)
}


def draw_rec_params(template: dict, rng: random.Random, index: int) -> dict:
    stratum = stratum_for(template, index)
    state = stratum["state"]
    required = Decimal(REC_REQUIRED_TOP_SPACE[state])
    where = stratum["top_space"]
    if where == "over":
        top_space = required + Decimal(rng.choice(REC_TOP_SPACE_OVER))
    elif where == "at":
        top_space = required  # at the requirement binds: `measured < required` is false
    else:
        top_space = required - Decimal(rng.choice(REC_TOP_SPACE_UNDER))

    span = rng.choice(REC_DATE_SPANS)
    mode = stratum.get("as_of")
    if mode is None:
        as_of = REC_REFERENCE_DATE + _dt.timedelta(days=span)
    else:
        as_of = REC_RULE_DATES[mode] - _dt.timedelta(days=span)

    floor = stratum.get("top_space_confidence")
    if floor == "below_floor":
        score = rng.choice(REC_CONFIDENCE_BELOW_FLOOR)
    elif floor == "at_floor":
        score = 0.85
    else:
        score = rng.choice(REC_CONFIDENCE_ABOVE_FLOOR)
    params: dict = {
        "state": state,
        "instrument_type": stratum["instrument"],
        "top_space": str(top_space),
        "cover_page": stratum["cover"],
        "as_of": as_of,
        "top_space_confidence": {"score": score, "method": "conformal"},
    }
    if stratum.get("cover_confidence") == "below_default":
        params["cover_page_confidence"] = {
            "score": rng.choice(REC_CONFIDENCE_BELOW_DEFAULT),
            "method": "platt",
        }
    if "concurrent" in stratum:
        params["concurrent"] = stratum["concurrent"]
    if "declaration" in stratum:
        params["declaration"] = stratum["declaration"]
    if "question" in stratum:
        params["question"] = stratum["question"]
    return params


# ---------------------------------------------------------------------------
# Generation driver
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if (root / "rulepacks").is_dir():
        return root
    return Path.cwd()


def _fact_validator(root: Path):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = load_schema("grounded-fact")  # ships in duly_core; see A8
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_fact(validator, fact: dict) -> None:
    errors = list(validator.iter_errors(fact))
    if errors:
        msgs = "; ".join(e.message for e in errors)
        raise ValueError(f"generated fact failed schema validation: {msgs}")


def allocate(count: int, names: list[str]) -> dict[str, int]:
    """Split `count` across templates proportionally to their registry
    weights (largest-remainder, ties broken by registry order). Purely
    integer arithmetic, so allocation is deterministic."""
    weights = {n: STATE_TEMPLATES[n]["weight"] for n in names}
    total = sum(weights.values())
    quotas: dict[str, int] = {}
    remainders: list[tuple[int, int, str]] = []
    for idx, n in enumerate(names):
        q, r = divmod(count * weights[n], total)
        quotas[n] = q
        remainders.append((-r, idx, n))
    for _, _, n in sorted(remainders)[: count - sum(quotas.values())]:
        quotas[n] += 1
    return quotas


def _generate_case(template: dict, case_id: str, index: int, rng: random.Random, pack: dict, validator):
    for _ in range(20):
        if template["kind"] == "notice":
            params = draw_notice_params(template, rng)
            builder = build_notice_facts
        elif template["kind"] == "trid":
            params = draw_trid_params(template, rng)
            builder = build_trid_facts
        elif template["kind"] == "ron":
            params = draw_ron_params(template, rng, index)
            builder = build_ron_facts
        elif template["kind"] == "esign":
            params = draw_esign_params(template, rng, index)
            builder = build_esign_facts
        elif template["kind"] == "resc":
            params = draw_resc_params(template, rng, index)
            builder = build_resc_facts
        elif template["kind"] == "rec":
            params = draw_rec_params(template, rng, index)
            builder = build_rec_facts
        else:  # pragma: no cover - registry entries are internal data
            raise ValueError(f"unknown template kind: {template['kind']!r}")
        # A stratum may pick one of the pack's other declared decisions; the
        # chosen question is recorded in case.yaml so replay asks it too.
        question = params.pop("question", template["question"])
        facts, eff, kn = builder(template, case_id, **params)
        for fact in facts:
            _validate_fact(validator, fact)
        try:
            receipt = adjudicate(facts, pack, eff, kn, question)
        except AdjudicationError:
            # Deterministic redraw: discard this draw, take the next one from
            # the same stream; the case id does not advance.
            continue
        return facts, eff, kn, question, receipt
    raise AdjudicationError(f"could not draw a valid case for {case_id} after 20 attempts")


def _dump_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _write_case(out: Path, case_id: str, template: dict, question: str, eff: str, kn: str, facts: list[dict], receipt: dict) -> None:
    case_dir = out / "cases" / case_id
    (case_dir / "facts").mkdir(parents=True)
    case_yaml = (
        f"id: {case_id}\n"
        f"pack: {template['pack']}\n"
        f"question: {question}\n"
        f"asOfEffective: \"{eff}\"\n"
        f"asOfKnowledge: \"{kn}\"\n"
    )
    (case_dir / "case.yaml").write_text(case_yaml, encoding="utf-8")
    for fact in facts:
        name = fact["attribute"].replace(":", "-") + ".json"
        (case_dir / "facts" / name).write_text(_dump_json(fact), encoding="utf-8")
    (out / "receipts" / f"{case_id}.json").write_text(_dump_json(receipt), encoding="utf-8")


def _decision_label(receipt: dict) -> str:
    v = receipt["decision"]["value"]
    if v["kind"] == "boolean":
        return "compliant" if v["value"] else "non-compliant"
    if v["kind"] == "money":
        return "no-fee-or-cure" if Decimal(v["amount"]) == 0 else "fee-or-cure-owed"
    if v["kind"] == "code":
        return v["value"]
    if v["kind"] == "date":
        return "date-certified"
    if v["kind"] == "decimal":
        return v["value"]
    return "other"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance generate",
        description="Generate the golden corpus (deterministic; see golden/README.md).",
    )
    parser.add_argument("--out", default="golden", help="output directory (default: golden)")
    parser.add_argument("--count", type=int, default=350, help="total cases across templates")
    parser.add_argument("--seed", type=int, default=7, help="generator seed")
    parser.add_argument(
        "--templates",
        default=None,
        help="comma-separated template names (default: all registered)",
    )
    args = parser.parse_args(argv)

    if args.templates:
        names = [n.strip() for n in args.templates.split(",") if n.strip()]
        unknown = [n for n in names if n not in STATE_TEMPLATES]
        if unknown:
            known = ", ".join(STATE_TEMPLATES)
            print(f"unknown template(s): {', '.join(unknown)} (registered: {known})", file=sys.stderr)
            return 2
    else:
        names = list(STATE_TEMPLATES)
    if args.count < 1:
        print("--count must be at least 1", file=sys.stderr)
        return 2

    root = repo_root()
    out = Path(args.out)
    validator = _fact_validator(root)
    quotas = allocate(args.count, names)

    # Generate everything in memory first so a failure leaves the existing
    # corpus untouched, then reset cases/ + receipts/ and write.
    generated: list[tuple[str, str, dict, str, str, str, list[dict], dict]] = []
    packs: dict[str, dict] = {}
    for name in names:
        template = STATE_TEMPLATES[name]
        pack_rel = template["pack"]
        if pack_rel not in packs:
            packs[pack_rel] = yaml.safe_load((root / pack_rel).read_text())
        rng = random.Random(f"{args.seed}:{name}")
        for i in range(1, quotas[name] + 1):
            case_id = f"{template['id_prefix']}-{i:04d}"
            facts, eff, kn, question, receipt = _generate_case(
                template, case_id, i, rng, packs[pack_rel], validator
            )
            generated.append((name, case_id, template, question, eff, kn, facts, receipt))

    # Reset the synthetic corpus only: review-* entries are human-review
    # golden cases (duly_review.golden), not generator output — they carry
    # provenance no seed can regenerate, so regeneration preserves them
    # (golden/README.md, "Case id series").
    for sub in ("cases", "receipts"):
        sub_dir = out / sub
        if sub_dir.exists():
            for entry in sub_dir.iterdir():
                if entry.name.startswith("review-"):
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
        else:
            sub_dir.mkdir(parents=True)
    for _, case_id, template, question, eff, kn, facts, receipt in generated:
        _write_case(out, case_id, template, question, eff, kn, facts, receipt)

    print(f"generated {len(generated)} cases into {out}")
    for name in names:
        rows = [g for g in generated if g[0] == name]
        labels: dict[str, int] = {}
        for row in rows:
            label = _decision_label(row[7])
            labels[label] = labels.get(label, 0) + 1
        split = ", ".join(f"{v} {k}" for k, v in sorted(labels.items()))
        print(f"  {name}: {len(rows)} cases ({split})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
