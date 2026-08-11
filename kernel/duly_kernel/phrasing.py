"""Decision phrasing: how a decision *value* is worded (spec/rule-ir.md).

A decision's meaning is `decision.value`, which is hashed. How that value is
*said* — "Cure required" rather than "250.00 USD", "Not compliant" rather than
"noticeCompliant: no" — is domain knowledge that belongs with the rules, so it
is carried by the pack in an optional per-decision `phrasing:` block. This
module is that block's renderer, and the only one: `duly_kernel.ir` validates
phrasing where a pack author will read the error, and everything that renders a
decision for a human reads it from here.

    determination(receipt, facts, pack) -> {"verdict", "detail", "tone"} | None

`None` is the load-bearing return. It means *this pack declares no phrasing
case that applies*, and it is deliberately not a wording, because the honest
fallback differs per medium: `duly_kernel.report` heads a boolean report with
`permitted: no`, the demo's answer line says `Yes`/`No` and flags anything else
`generic`. A renderer that let this module invent the fallback would be
publishing wording no pack author wrote — which is the defect this module
exists to remove.

CRITICAL PROPERTY — phrasing is presentation and stays presentation. Nothing
here is written to a receipt, a fact, an envelope, or any other hashed body: a
wording key added in place would change every hash and break replay
(spec/compatibility.md C2). Wording must stay free to improve.

Determinism holds as everywhere else in the kernel: pure templating over the
receipt, the facts and the pack, no wall clock (`{daysBetween:…}` subtracts two
fact values), no randomness.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .relevance import consulted_attributes

# Shared with `duly_kernel.ir`'s validator, which imports both from here. A
# validator and a renderer that disagree about what a placeholder *is* fail in
# the worst possible way: the pack loads, and the sentence silently comes out
# wrong. One definition, imported, cannot drift.
PHRASING_TOKEN = re.compile(r"\{([^{}]*)\}")
PHRASING_FORMATS = {"", "day", "int"}


# ---------------------------------------------------------------------------
# Value formatting (shared with the report renderer)
# ---------------------------------------------------------------------------


def local_name(curie: str) -> str:
    """The local part of a CURIE ('nc:noticeCompliant' -> 'noticeCompliant')."""
    i = curie.find(":")
    return curie[i + 1:] if i >= 0 else curie


def format_value(value: Any) -> str:
    """A fact/decision value mapping, rendered plainly ('250.00 USD', 'true')."""
    if not isinstance(value, dict):
        return str(value)
    kind = value.get("kind")
    if kind == "money":
        return f"{value.get('amount')} {value.get('currency')}"
    if kind == "boolean":
        return "true" if value.get("value") else "false"
    return str(value.get("value"))


def _day_part(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def _fmt_score(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Reading the run: facts, derived conclusions, abstentions
# ---------------------------------------------------------------------------


def _find_derived_value(node: Any, attribute_suffix: str) -> dict[str, Any] | None:
    """Depth-first search of a derivation tree for a conclusion on an attribute."""
    if not isinstance(node, dict):
        return None
    conclusion = node.get("conclusion")
    if isinstance(conclusion, dict):
        attr = conclusion.get("attribute", "")
        if attr == attribute_suffix or attr.endswith(":" + attribute_suffix):
            return conclusion.get("value")
    for premise in node.get("premises", []) or []:
        found = _find_derived_value(premise, attribute_suffix)
        if found is not None:
            return found
    return None


def _fact_value(facts: list[dict[str, Any]], attribute_suffix: str) -> Any:
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        attr = fact.get("attribute", "")
        if attr == attribute_suffix or attr.endswith(":" + attribute_suffix):
            value = fact.get("value", {})
            return value.get("value") if isinstance(value, dict) else value
    return None


def low_confidence_caveat(receipt: dict[str, Any], pack: Any = None) -> str | None:
    """The `{caveat}` sentence: "Presumption only — …" when this decision
    stands only because a below-floor fact was excluded, else None.

    Unresolvable-when-absent is the point. A pack writes `detail: "{caveat}"`
    for the guarded case and a different alternative for the unguarded one, so
    a decision that abstained over nothing never claims it did.

    **Scoped to the attributes this decision's rules can consult** when a pack
    is supplied. Abstentions are case-wide — the kernel excludes below-floor
    facts before any rule runs — so a receipt carries exclusions that had
    nothing to do with the question it answers. Unscoped, a decision that never
    read the attribute would be captioned "Presumption only — … excluded",
    which is a false claim about *why that answer is what it is*, and it would
    reach the audit report a regulator reads.

    No committed artifact changes: all 43 corpus receipts carrying a
    `low_confidence` entry have the abstained attribute genuinely consulted by
    their decision, because the corpus asks one question per case. The demo
    asks several of one case, which is where the divergence is visible.

    Without a pack the old unscoped behaviour stands, because the alternative
    is to silently drop caveats a caller cannot verify: `None` from
    `consulted_attributes` means *unknown*, not *consults nothing*.
    """
    low_confidence = [
        a
        for a in receipt.get("abstentions") or []
        if isinstance(a, dict) and a.get("reason") == "low_confidence"
    ]
    consulted = consulted_attributes(pack, (receipt.get("decision") or {}).get("attribute"))
    if consulted is not None:
        low_confidence = [a for a in low_confidence if a.get("attribute") in consulted]
    if not low_confidence:
        return None
    parts = []
    for entry in low_confidence:
        attr = local_name(entry.get("attribute", ""))
        confidence = entry.get("confidence") or {}
        threshold = entry.get("threshold") or {}
        if (
            confidence.get("score") is not None
            and threshold.get("minConfidence") is not None
        ):
            parts.append(
                f"{attr} excluded at confidence "
                f"{_fmt_score(confidence['score'])}, below the "
                f"{_fmt_score(threshold['minConfidence'])} floor"
            )
        else:
            parts.append(f"{attr} excluded below the confidence floor")
    return "Presumption only — " + "; ".join(parts)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _scalar(raw: Any, fmt: str) -> str | None:
    """Format an already-unwrapped scalar (a fact's `value.value`)."""
    if fmt == "day":
        return _day_part(str(raw)) or str(raw)
    if fmt == "int":
        try:
            return str(int(float(raw)))
        except (TypeError, ValueError):
            return None
    return str(raw)


def _value(value: Any, fmt: str) -> str | None:
    """Format a value mapping (`{kind, value}` / `{kind, amount, currency}`)."""
    if not isinstance(value, dict):
        return _scalar(value, fmt)
    if fmt == "day":
        return _day_part(str(value.get("value") or "")) or format_value(value)
    if fmt == "int":
        return _scalar(value.get("value", value.get("amount")), "int")
    return format_value(value)


def _days_between(facts: list[dict[str, Any]], start: str, end: str) -> str | None:
    a, b = _fact_value(facts, start), _fact_value(facts, end)
    if a is None or b is None:
        return None
    try:
        return str(
            (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days
        )
    except ValueError:
        return None


def _token(
    token: str,
    receipt: dict[str, Any],
    facts: list[dict[str, Any]],
    value: dict[str, Any],
    pack: Any = None,
) -> str | None:
    """Resolve one `{token}`. None means *unresolvable*, which discards the
    template alternative that used it — that is how a pack says "phrase it
    this way when the inputs are there, that way when they are not"."""
    spec, _, fmt = token.partition("|")
    head, _, arg = spec.strip().partition(":")
    fmt, arg = fmt.strip(), arg.strip()
    if head == "value":
        return _value(value, fmt)
    if head == "money":
        text = " ".join(
            str(part) for part in (value.get("amount"), value.get("currency")) if part
        )
        return text or None
    if head == "caveat":
        return low_confidence_caveat(receipt, pack)
    if head == "fact":
        raw = _fact_value(facts, arg)
        return None if raw is None else _scalar(raw, fmt)
    if head == "derived":
        found = _find_derived_value(receipt.get("derivation"), arg)
        return None if found is None else _value(found, fmt)
    if head == "daysBetween":
        start, _, end = arg.partition(",")
        return _days_between(facts, start.strip(), end.strip())
    return None


def _render(
    template: Any,
    receipt: dict[str, Any],
    facts: list[dict[str, Any]],
    value: dict[str, Any],
    pack: Any = None,
) -> str | None:
    if not isinstance(template, str):
        return None
    out: list[str] = []
    pos = 0
    for match in PHRASING_TOKEN.finditer(template):
        resolved = _token(match.group(1), receipt, facts, value, pack)
        if resolved is None:
            return None
        out.append(template[pos:match.start()])
        out.append(resolved)
        pos = match.end()
    out.append(template[pos:])
    return "".join(out)


def _first(
    candidates: Any,
    receipt: dict[str, Any],
    facts: list[dict[str, Any]],
    value: dict[str, Any],
    pack: Any = None,
) -> str | None:
    """The first alternative whose every token resolves, or None."""
    if isinstance(candidates, str):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        rendered = _render(candidate, receipt, facts, value, pack)
        if rendered is not None:
            return rendered
    return None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _money_is_positive(value: dict[str, Any]) -> bool:
    amount = value.get("amount")
    try:
        return float(amount) > 0
    except (TypeError, ValueError):
        return bool(amount)


def _case_applies(
    when: Any,
    receipt: dict[str, Any],
    facts: list[dict[str, Any]],
    value: dict[str, Any],
    pack: Any = None,
) -> bool:
    """Every declared guard must hold; an absent/empty `when` always holds."""
    if not when:
        return True
    if not isinstance(when, dict):
        return False
    if "value" in when:
        expected = when["value"]
        if isinstance(expected, bool):
            if value.get("kind") != "boolean" or bool(value.get("value")) is not expected:
                return False
        elif str(value.get("value", "")) != str(expected):
            return False
    if "amount" in when:
        if (when["amount"] == "positive") is not _money_is_positive(value):
            return False
    if "abstained" in when:
        excluded = low_confidence_caveat(receipt, pack) is not None
        if (when["abstained"] == "lowConfidence") is not excluded:
            return False
    guard = when.get("fact")
    if isinstance(guard, dict):
        raw = _fact_value(facts, str(guard.get("attribute", "")))
        if "present" in guard and bool(guard["present"]) is not (raw is not None):
            return False
        if "equals" in guard:
            if raw is None:
                return False
            expected_text = guard["equals"]
            if isinstance(expected_text, str) and "{" in expected_text:
                expected_text = _render(expected_text, receipt, facts, value, pack)
                if expected_text is None:
                    return False
            if str(raw) != str(expected_text):
                return False
    return True


def decision_phrasing(pack: Any, attribute: str) -> list[Any] | None:
    """The `phrasing` case list a pack declares for one decision attribute."""
    if not isinstance(pack, dict):
        return None
    for decision in pack.get("decisions") or []:
        if isinstance(decision, dict) and decision.get("attribute") == attribute:
            cases = decision.get("phrasing")
            return cases if isinstance(cases, list) else None
    return None


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def determination(
    receipt: dict[str, Any],
    facts: list[dict[str, Any]] | None,
    pack: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """How this receipt's decision is worded, per its pack — or None.

    Returns ``{"verdict", "detail", "tone"}``: the headline, one supporting
    clause with no terminal period (``""`` when the pack declares none), and a
    tone of ``pos``/``neg``/``warn``/``""``. `phrasing` is an ordered case
    list and the first case whose guards all hold wins, so the pack's order is
    the renderer's precedence.

    Returns **None** when there is no pack, no `phrasing` for this decision, or
    no case whose guards hold and whose `verdict` template fully resolves. The
    caller supplies its own fallback: see the module docstring for why that is
    not decided here.

    `facts` are the facts the caller has for this run — the `{fact:…}`,
    `{daysBetween:…}` and `fact:` guards read them. Passing fewer facts than
    the run consumed makes a template alternative unresolvable, never wrong:
    an unresolvable alternative is skipped, and a case whose verdict cannot be
    rendered is passed over as if its guards had failed.
    """
    decision = receipt.get("decision") or {}
    attribute = decision.get("attribute", "")
    value = decision.get("value") or {}
    facts = facts or []

    for case in decision_phrasing(pack, attribute) or []:
        if not isinstance(case, dict):
            continue
        if not _case_applies(case.get("when"), receipt, facts, value, pack):
            continue
        verdict = _first(case.get("verdict"), receipt, facts, value, pack)
        if verdict is None:
            continue
        detail = _first(case.get("detail"), receipt, facts, value, pack)
        return {
            "verdict": verdict,
            "detail": detail or "",
            "tone": str(case.get("tone") or ""),
        }
    return None
