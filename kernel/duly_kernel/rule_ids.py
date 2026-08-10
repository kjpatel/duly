"""The rule-id convention, and the ids that predate it.

A rule id is a **handle, not a claim**. Everything an id is tempted to encode
already has a home on the rule: the statute is in `citation`, the date is in
`effectiveFrom`, the threshold is in `then.value`, the jurisdiction is in the
`when` guard. An id that repeats one of those becomes *false* the moment that
field changes — and unlike the field, the id cannot be corrected, because it is
inside every receipt that ever cited it. `NY-NR-45` names New York's 45-day
nonrenewal notice; the day the legislature moves to 60 days, the pack gets a
new rule and the old id keeps saying 45 in 76 golden receipts forever.

So the convention (spec/rule-ir.md, "Rule ids") is:

    <PREFIX>-<TOPIC>[-<QUALIFIER>…][-NN]

uppercase, hyphen-separated, letters only, with an optional **trailing
two-digit sequence number** that means nothing but "the next id in this
family". Three parts of it are machine-checked here; the rest is style, left to
review:

1. **No digits except the trailing sequence.** Kills years (`TX-RON-2018`),
   statute sections (`CA-DTT-11933`), and bill numbers (`CA-SB2-75`).
2. **The sequence must not echo the rule's own numbers.** A two-digit tail that
   equals a numeric literal in the rule's `when` or `then.value` is a day count
   or a dollar amount wearing a sequence number's clothes. `00` is exempt: it is
   the conventional default-rule slot, and a default very often concludes zero.
3. **One pack, one family.** When a pack declares `pack.idPrefix`, every id it
   mints starts with it, so a pack cannot grow two competing schemes the way
   three of the six committed packs did.

The checks run **only for packs that declare `pack.idPrefix`** — declaring one
is how a pack opts into the convention. Every pack in this repo declares one
(`examples/tests/test_example_rule_ids.py` sweeps the committed packs and
fails if one does
not); an adopter porting a rulebase with its own established ids is not forced
to rename anything, which matters because renaming is exactly what this module
argues is impossible after the fact.

What it deliberately does **not** catch: a semantic number that never appears
in the rule body. `CA-TOPSPACE-25` encodes 2.5 inches, and `25` is not `2.5`, so
the echo check passes it. The prose rule is the primary instrument; the checks
make the common accidents loud.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

#: `<PREFIX>-<TOPIC>[-<QUALIFIER>…]` with an optional trailing 2-digit sequence.
RULE_ID_RE = re.compile(r"^[A-Z]+(?:-[A-Z]+)*(?:-(?P<seq>[0-9]{2}))?$")

#: A pack's declared id family.
ID_PREFIX_RE = re.compile(r"^[A-Z]+$")

_NUMERAL_RE = re.compile(r"\d+(?:\.\d+)?")

_SPEC = 'spec/rule-ir.md, "Rule ids"'


# ---------------------------------------------------------------------------
# Grandfathered ids
#
# Every rule id committed to this repo before the convention existed, listed by
# pack, exempt forever. This is a list and not a rule on purpose: a heuristic
# ("ids that look old", "ids committed before date D") would quietly widen, and
# the point of an exemption is that it is finite and countable. 46 ids across
# six packs; 17 of them would fail the convention today, which is the honest
# measure of how much drift one roadmap item late costs. `test_rule_ids.py`
# pins both numbers, so growing this list is a visible diff with a failing
# test attached.
#
# Nothing here may ever be renamed: `NY-NR-45` alone appears in 76 golden
# receipts, and a receipt is not editable by construction.
# ---------------------------------------------------------------------------
GRANDFATHERED_RULE_IDS: dict[str, frozenset[str]] = {
    "county-recording-us": frozenset(
        {
            "REC-DEF-CA",
            "REC-DEF-AZ",
            "CA-TOPSPACE-25",  # jurisdiction-first; 25 = 2.5 inches
            "AZ-TOPMARGIN-20",  # jurisdiction-first; 20 = 2.0 inches
            "REC-TOPSPACE-01",
            "CA-DTT-11933",  # jurisdiction-first; 11933 = Rev. & Tax. Code § 11933
            "CA-SB2-75",  # jurisdiction-first; SB2 = the bill, 75 = $75 cap
            "CA-SB2-EXEMPT-DTT",  # jurisdiction-first; SB2 = the bill
        }
    ),
    "esign-closing-package": frozenset(
        {
            "PKG-DEF-00",
            "PKG-DEF-01",
            "PKG-CD-10",
            "PKG-CD-11",
            "PKG-RTC-20",
            "PKG-RTC-21",
            "PKG-NOTE-30",
            "PKG-NOTE-31",
            "PKG-NOTE-32",
            "PKG-DOT-40",
        }
    ),
    "notarization-ron-us-states": frozenset(
        {
            "RON-DEF-00",
            "VA-RON-2012",  # jurisdiction-first; 2012 = the authorization year
            "TX-RON-2018",  # jurisdiction-first; 2018 = the authorization year
            "FL-RON-2020",  # jurisdiction-first; 2020 = the authorization year
            "NY-RON-2023",  # jurisdiction-first; 2023 = the authorization year
            "CA-RON-2030",  # jurisdiction-first; 2030 = the authorization year
            "RON-COMP-00",
            "RON-COMP-01",
        }
    ),
    "termination-notice-us-states": frozenset(
        {
            "NC-DEF-00",
            "NY-NR-45-LEGACY",  # jurisdiction-first; 45 = the pre-1986 day count
            "NY-NR-45",  # jurisdiction-first; 45 = the day count
            "NY-NR-NONPAY-15",  # jurisdiction-first; 15 = the day count
            "FL-NR-120",  # jurisdiction-first; 120 = the day count
            "FL-NONPAY-10",  # jurisdiction-first; 10 = the day count
            "CA-NR-75",  # jurisdiction-first; 75 = the day count
            "CA-NONPAY-10",  # jurisdiction-first; 10 = the day count
            "NC-NR-01",
        }
    ),
    "tila-rescission-us-federal": frozenset(
        {
            "RESC-APP-01",
            "RESC-APP-02",
            "RESC-EXC-RMT",
            "RESC-DL-01",
            "RESC-FUND-DEF",
            "RESC-FUND-STAY",
            "RESC-FUND-EXP",
            "RESC-FUND-NA",
        }
    ),
    "trid-fee-tolerance-us-federal": frozenset(
        {
            "TRID-DEF-00",
            "TRID-CAT-02",
            "TRID-ZT-01",
        }
    ),
}

#: Pinned so that adding an exemption cannot pass unnoticed.
GRANDFATHERED_RULE_ID_COUNT = 46


def is_grandfathered(pack_name: object, rule_id: str) -> bool:
    if not isinstance(pack_name, str):
        return False
    return rule_id in GRANDFATHERED_RULE_IDS.get(pack_name, frozenset())


def _rule_numerals(rule: dict) -> set[Decimal]:
    """Every number the rule itself asserts or tests."""
    texts: list[str] = [str(cond) for cond in (rule.get("when") or [])]
    value = (rule.get("then") or {}).get("value")
    if isinstance(value, dict):
        for key in ("value", "amount", "expr"):
            if key in value and not isinstance(value[key], bool):
                texts.append(str(value[key]))
    found: set[Decimal] = set()
    for text in texts:
        for numeral in _NUMERAL_RE.findall(text):
            try:
                found.add(Decimal(numeral))
            except InvalidOperation:  # pragma: no cover - regex guarantees parse
                pass
    return found


def rule_id_problem(rule: dict, prefix: str) -> str | None:
    """The reason this id does not follow the convention, or None.

    `prefix` is the pack's declared `idPrefix`; callers only reach here for
    packs that declared one, and for ids that are not grandfathered.
    """
    rid = rule["id"]
    match = RULE_ID_RE.match(rid)
    if match is None:
        digits = "', '".join(re.findall(r"\d+", rid)) or "none"
        return (
            f"is not a conforming rule id (digit group(s): '{digits}'). Ids are "
            f"uppercase letters and hyphens, with at most a trailing two-digit "
            f"sequence number: {prefix}-<TOPIC>[-<QUALIFIER>][-NN], e.g. "
            f"{prefix}-STATE-01. A year, a statute section, a bill number or a "
            f"day count in an id is a claim the id cannot retract — the "
            f"citation, effectiveFrom and then.value fields already carry those"
        )
    if not rid.startswith(prefix + "-"):
        return (
            f"does not start with this pack's declared id family {prefix + '-'!r} "
            f"(pack.idPrefix). One pack, one family: a jurisdiction belongs in a "
            f"later segment ({prefix}-NY-NONRENEWAL-01), not in front, so the "
            f"pack cannot grow two competing schemes"
        )
    seq = match.group("seq")
    if seq is None or int(seq) == 0:
        return None
    echoed = sorted(n for n in _rule_numerals(rule) if n == int(seq))
    if echoed:
        return (
            f"ends in the sequence number {seq}, which is also a literal in the "
            f"rule's own body ({echoed[0]}). A sequence number means nothing but "
            f"'the next id in this family'; a number that matches the rule's day "
            f"count, dollar amount or threshold reads as a claim about the law, "
            f"and it will be wrong the day the law changes. Use the next unused "
            f"sequence number, or none at all"
        )
    return None


def check_rule_ids(pack: dict, rules: list[dict]) -> str | None:
    """Validate every non-grandfathered id against the pack's declared family.

    Returns a complete error message, or None. A pack that declares no
    `pack.idPrefix` has not opted into the convention and is not checked.
    """
    meta = pack.get("pack") or {}
    prefix = meta.get("idPrefix")
    if prefix is None:
        return None
    if not isinstance(prefix, str) or not ID_PREFIX_RE.match(prefix):
        return (
            f"pack.idPrefix must be uppercase letters naming this pack's rule-id "
            f"family (e.g. 'RESC'), got {prefix!r}"
        )
    pack_name = meta.get("name")
    for rule in rules:
        rid = rule["id"]
        if is_grandfathered(pack_name, rid):
            continue
        problem = rule_id_problem(rule, prefix)
        if problem:
            return f"rule {rid!r} {problem}. See {_SPEC}"
    return None
