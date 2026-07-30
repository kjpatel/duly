"""Solving a pack backwards: free one input, ask which values hit a target.

The encoding is `assurance/duly_assurance/smt.py` — the same one `prove`
uses, unchanged. That is deliberate and it is the load-bearing design
decision in this package: two encodings of one IR would agree until they
didn't, and the disagreement would surface as a wrong answer to a user
rather than as a test failure.

But `prove` and this module stand in *opposite* relations to the solver, and
the difference is worth stating before any of the code makes sense.

`prove` lives on UNSAT. Its encoding is allowed to widen the input space
(spec/pack-verification.md, P2), because widening keeps UNSAT a proof; the
price is possibly-spurious SAT, which `prove` pays by downgrading a widened
witness to OUT-OF-FRAGMENT.

**This module lives on SAT** — on exactly the answers widening makes
unreliable. So the property that makes `prove` sound makes a raw solver
answer untrustworthy here, and nothing recovers it except running the real
kernel on the proposed case. Hence the shape of everything below: the solver
proposes candidate values and `casefacts.decide` — `duly_kernel.api.adjudicate`
itself — disposes. A candidate the kernel refutes is never returned; it is a
`SolverKernelContradiction` carrying both artifacts.

One narrowing is introduced here that `prove` does not make, and it is the
reason UNSAT is weaker in this module than in that one: a freed `decimal` or
`money` input is **restricted to its decimal grid** (the scale of the value
the case already carries, or an explicit `scale`). duly's money is a decimal
string, not a real, so the grid is where the answers actually live — and
without it the extremal of an open region is an unattainable infimum
(`disclosed + ε`) that no fact could carry and no kernel run could verify.
It is a narrowing all the same, so an UNSATISFIABLE verdict on an ordered
input means "no value *at this scale*", and says so.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal

from duly_assurance.smt import (
    DATE_MAX,
    DATE_MIN,
    OTHER,
    OutOfFragment,
    PackEncoding,
    Universe,
)

from . import casefacts as _cf

try:  # pragma: no cover - the CLI reports this properly
    import z3
except ImportError:  # pragma: no cover
    z3 = None  # type: ignore[assignment]


__all__ = [
    "Query",
    "Answer",
    "Boundary",
    "WhatIfReport",
    "solve",
    "Unsupported",
    "SolverKernelContradiction",
    "SATISFIABLE",
    "UNSATISFIABLE",
    "UNSUPPORTED",
    "Z3_MISSING",
    "OTHER_REPRESENTATIVE",
    "AS_OF",
]


Z3_MISSING = (
    "z3-solver is not installed. What-if is an optional analysis behind an "
    "optional dependency:\n"
    "    uv run --with z3-solver python -m duly_whatif "
    "--case golden/cases/notice-ny-0001 --free nc:noticeMailedDate --target true\n"
    "or `uv sync --extra prove`."
)

# The same deterministic resource ceiling `prove` uses, for the same reason:
# z3's rlimit counts solver work rather than wall-clock time, so a verdict
# does not depend on how fast the machine is (spec/pack-verification.md, P8).
RLIMIT = 40_000_000

SATISFIABLE = "SATISFIABLE"
UNSATISFIABLE = "UNSATISFIABLE"
UNSUPPORTED = "UNSUPPORTED"

# The concrete value used to *verify* the residual region of an open code set.
# `smt.py` gives an open domain a single "any other value" slot, which stands
# for every unenumerated value at once and is therefore not itself a value a
# fact could carry. Returning it unverified would break the contract, so the
# region is verified with this deterministic representative and reported as a
# region rather than dressed up as a value.
OTHER_REPRESENTATIVE = "«any-other-value»"

_ORDERED = ("decimal", "money", "date")
_FINITE = ("boolean", "string", "code")

# Freeing the evaluation point rather than a fact. The evaluation point is an
# input to the run exactly as a fact is — it is a first-class symbol in the
# encoding and a parameter of `adjudicate` — so it is freeable on the same
# terms, and it is what makes "when may I fund?" a question this tool answers.
AS_OF = "asOf"


class Unsupported(Exception):
    """A named construct the query cannot be answered over.

    Always names what stopped it, never a bare refusal — a bare refusal is
    indistinguishable from a bug (spec/pack-verification.md, P2).
    """


class SolverKernelContradiction(AssertionError):
    """The solver claimed something the kernel refuted.

    This is the guard the package is built around, so it is an error and not a
    filter: a candidate that fails verification is never quietly dropped and
    never quietly returned. It carries both artifacts — what the solver
    claimed, and the fact set and decision the kernel produced — because
    either alone is unactionable.

    Reaching this means the encoding and the kernel disagree about the rule
    IR, which is a defect in one of them.
    """

    def __init__(self, claim: str, value: str, expected: str,
                 outcome: _cf.KernelOutcome, facts: list[dict], as_of_effective: str):
        self.claim = claim
        self.value = value
        self.expected = expected
        self.outcome = outcome
        self.facts = facts
        self.as_of_effective = as_of_effective
        super().__init__(
            f"solver/kernel contradiction: {claim}\n"
            f"  freed value      {value}\n"
            f"  solver claimed   {expected}\n"
            f"  kernel decided   {outcome.render()}\n"
            f"  evaluation point {as_of_effective}\n"
            f"  fact ids         {', '.join(sorted(f['id'] for f in facts))}\n"
            f"This is not a query that failed; it is an encoding that disagrees "
            f"with the kernel. Neither answer is trustworthy until it is resolved."
        )


# ---------------------------------------------------------------------------
# Query and results
# ---------------------------------------------------------------------------


@dataclass
class Query:
    """One what-if: a case, a pack, a point, one freed input, one target."""

    facts: list[dict]
    pack: dict
    as_of_effective: str
    as_of_knowledge: str
    decision: str
    free: str                       # an attribute CURIE, or AS_OF
    target: dict | None = None      # a fact value dict; None means "no decision"
    flip: bool = False              # target := anything other than today's decision
    extremal: str = "max"           # "max" | "min"
    scale: int | None = None        # decimal grid for a freed decimal/money


@dataclass
class Answer:
    """One value of the freed input, and what the kernel decided under it."""

    value: str                      # rendered for a human
    fact_value: dict                # the value the kernel was actually run on
    decision: str                   # what the kernel decided
    verified: bool = True
    representative: str | None = None   # set for an open code set's residual region
    note: str | None = None


@dataclass
class Boundary:
    """The step beyond an extremal answer, and the kernel's verdict on it."""

    value: str
    decision: str
    refuted: bool                   # the kernel agreed it does NOT hit the target
    note: str | None = None


@dataclass
class WhatIfReport:
    pack: str
    pack_version: str
    decision: str
    free: str
    free_kind: str
    as_of_effective: str
    target: str
    verdict: str
    current: str = ""               # today's decision, before anything is freed
    answers: list[Answer] = field(default_factory=list)
    extremal: Answer | None = None
    extremal_direction: str | None = None
    boundary: Boundary | None = None
    unbounded: bool = False
    complete: bool = False          # every domain member was kernel-checked
    reason: str | None = None
    assumptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.verdict == SATISFIABLE:
            return 0
        if self.verdict == UNSATISFIABLE:
            return 1
        return 2


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _encode(pack: dict, registry) -> tuple[Universe, PackEncoding]:
    """The shared `smt.py` encoding of `pack`.

    A module-level seam on purpose: it is the single point where the solver's
    view of the rulebase enters, which is what lets a test substitute a
    deliberately broken encoding and prove the contradiction guard fires.
    """
    universe = Universe(registry)
    universe.observe(pack)
    universe.finalize()
    return universe, PackEncoding(pack, universe)


def _symbol_key(free: str) -> str:
    return "asOf:effective" if free == AS_OF else f"attr:{free}"


# ---------------------------------------------------------------------------
# Values in and out of the encoding
# ---------------------------------------------------------------------------


def _pin_term(enc: PackEncoding, key: str, value: dict):
    """`var(key) == value`, in the symbol's own encoding."""
    sym = enc.symbols[key]
    var = enc.vars[key]
    if sym.kind == "boolean":
        return var == z3.BoolVal(bool(value["value"]))
    if sym.kind == "money":
        return var == z3.RealVal(str(value["amount"]))
    if sym.kind == "decimal":
        return var == z3.RealVal(str(value["value"]))
    if sym.kind == "date":
        return var == z3.IntVal(_cf.parse_date(str(value["value"])).toordinal())
    literal = str(value["value"])
    values = sym.values
    if literal in values:
        return var == z3.IntVal(values.index(literal))
    if sym.open_domain:
        # Faithful, not widened: the sentinel means "none of the enumerated
        # literals", which is exactly true of this value, and every guard the
        # fragment can express tests equality against an enumerated literal.
        return var == z3.IntVal(values.index(OTHER))
    raise Unsupported(
        f"the case asserts {sym.label} = {literal!r}, outside the closed value "
        f"domain the ontology declares ({', '.join(values)}) — the conformance "
        f"gate should have refused that fact"
    )


def _decision_term(enc: PackEncoding, attribute: str, target: dict):
    """The target value, in the decision symbol's own encoding."""
    sym = enc.symbols[enc._dkey(attribute)]
    if target.get("kind") != sym.kind:
        raise Unsupported(
            f"{attribute} is a {sym.kind} decision, and the target is a "
            f"{target.get('kind')} — a target the pack could not conclude even "
            f"in principle is a question with no answer"
        )
    if sym.kind == "boolean":
        return z3.BoolVal(bool(target["value"]))
    if sym.kind == "money":
        return z3.RealVal(str(target["amount"]))
    if sym.kind == "decimal":
        return z3.RealVal(str(target["value"]))
    if sym.kind == "date":
        return z3.IntVal(_cf.parse_date(str(target["value"])).toordinal())
    literal = str(target["value"])
    values = sym.values
    if literal not in values:
        raise Unsupported(
            f"{attribute}: no rule in this pack concludes {literal!r} "
            f"(it concludes only: "
            f"{', '.join(v for v in values if v != OTHER) or 'nothing in the fragment'})"
        )
    return z3.IntVal(values.index(literal))


def _value_scale(value: dict) -> int:
    raw = value["amount"] if value["kind"] == "money" else value["value"]
    return max(0, -int(Decimal(str(raw)).as_tuple().exponent))


def _fact_value(sym, template: dict | None, raw) -> dict:
    """A fact value dict for `raw` (a Decimal, date, bool or str).

    `template` is the value the case already carries, and it is the only
    source for the fields the encoding does not model — a money value's
    currency, a code's code system. Inventing them would be a guess; carrying
    them over says "same fact, different value", which is what a what-if is.
    """
    if sym.kind == "boolean":
        return {"kind": "boolean", "value": bool(raw)}
    if sym.kind == "date":
        return {"kind": "date", "value": raw.isoformat()}
    if sym.kind == "money":
        return {
            "kind": "money",
            "amount": str(raw),
            "currency": (template or {}).get("currency", "USD"),
        }
    if sym.kind == "decimal":
        return {"kind": "decimal", "value": str(raw)}
    out = {"kind": sym.kind, "value": str(raw)}
    for name in ("codeSystem", "codeSystemVersion"):
        if template and name in template:
            out[name] = template[name]
    return out


def _render_raw(raw) -> str:
    return raw.isoformat() if isinstance(raw, _dt.date) else str(raw)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def solve(query: Query, registry=None) -> WhatIfReport:
    """Answer `query`, verifying every answer against the kernel.

    Raises `Unsupported` when a named construct puts the question outside the
    fragment, and `SolverKernelContradiction` when the solver and the kernel
    disagree. It never returns an unverified answer.
    """
    if z3 is None:  # pragma: no cover - the CLI reports this properly
        raise Unsupported(Z3_MISSING)

    meta = query.pack["pack"]
    universe, enc = _encode(query.pack, registry)

    key = _symbol_key(query.free)
    if key not in enc.symbols:
        raise Unsupported(
            f"no rule in {meta['name']} binds {query.free}, so the encoding has "
            f"no symbol for it — which is itself the answer: this pack never "
            f"reads {query.free}, and no value of it can change this decision"
        )
    sym = enc.symbols[key]
    if sym.kind not in _ORDERED + _FINITE:  # pragma: no cover - smt.py refuses first
        raise Unsupported(f"{sym.label}: value kind {sym.kind!r} cannot be freed")

    try:
        defined, decision_var = enc.decision_value(query.decision)
    except OutOfFragment as exc:
        raise Unsupported(str(exc)) from exc

    live = _cf.live_by_attribute(query.facts, query.pack, query.as_of_effective)
    if sym.origin == "attribute" and sym.curie not in live:
        raise Unsupported(
            f"no live fact in this case asserts {sym.curie}. What-if varies a "
            f"value the case already carries; it does not mint the fact, the "
            f"entity, or the grounding a new one would need. Assert the fact "
            f"(even hypothetically) and re-run"
        )

    current = _cf.decide(
        query.facts, query.pack, query.as_of_effective,
        query.as_of_knowledge, query.decision,
    )
    target, target_label = _resolve_target(query, current, enc)

    report = WhatIfReport(
        pack=meta["name"], pack_version=meta["version"], decision=query.decision,
        free=query.free, free_kind=sym.kind, as_of_effective=query.as_of_effective,
        target=target_label, verdict=UNSUPPORTED, current=current.render(),
        assumptions=list(enc.assumption_labels()),
        notes=list(universe.notes) + list(enc.notes),
    )

    pins, template = _pins(enc, query, live, key)
    target_term = (
        z3.Not(defined) if target is None
        else z3.And(defined, decision_var == _decision_term(enc, query.decision, target))
    )
    base = list(enc.domain()) + pins + [target_term]

    if sym.kind in _FINITE:
        _answer_finite(query, enc, sym, key, base, target, template, report)
    else:
        _answer_ordered(query, enc, sym, key, base, target, template, report)
    return report


def _resolve_target(query: Query, current: _cf.KernelOutcome, enc: PackEncoding):
    """(target value dict or None, human label)."""
    if not query.flip:
        if query.target is None:
            return None, "no decision at all"
        return query.target, _cf.render_value(query.target)

    if not current.decided:
        raise Unsupported(
            "--flip needs a decision to flip away from, and this case reaches "
            f"none today ({current.render()}). Name the decision you want with "
            f"--target"
        )
    sym = enc.symbols[enc._dkey(query.decision)]
    if sym.kind != "boolean":
        raise Unsupported(
            f"--flip on a {sym.kind} decision needs a target value: 'anything "
            f"other than {current.render()}' names a region, and an extremal "
            f"over a region is not a question this tool answers. Use --target"
        )
    flipped = {"kind": "boolean", "value": not current.value["value"]}
    return flipped, f"{_cf.render_value(flipped)} (today: {current.render()})"


def _pins(enc: PackEncoding, query: Query, live: dict[str, dict], freed_key: str):
    """Pin every input except the freed one; return (terms, freed value template).

    Everything the case says is nailed down, so the only degree of freedom the
    solver has is the one the question is about. Existence is pinned too — an
    attribute with no live fact is pinned *absent*, because "the fact was never
    asserted" is a distinct and frequently decisive region (smt.py, "Existence
    is modeled explicitly"), and the kernel treats a missing binding as
    inapplicability rather than as a free choice.
    """
    terms = []
    template = None
    for key in sorted(enc.symbols):
        sym = enc.symbols[key]
        if key == freed_key:
            if sym.origin == "attribute":
                terms.append(enc.exists[key])
                template = live[sym.curie]["value"]
            continue
        if sym.origin == "asOf":
            terms.append(
                enc.vars[key]
                == z3.IntVal(_cf.parse_date(query.as_of_effective).toordinal())
            )
            continue
        if sym.origin != "attribute":
            continue  # derived: defined by the pack's own rules, never pinned
        fact = live.get(sym.curie)
        if fact is None:
            terms.append(z3.Not(enc.exists[key]))
            continue
        terms.append(enc.exists[key])
        terms.append(_pin_term(enc, key, fact["value"]))

    if freed_key == "asOf:effective":
        terms.extend(_asof_window_terms(enc, live))
    return terms, template


def _asof_window_terms(enc: PackEncoding, live: dict[str, dict]):
    """Keep a freed evaluation point inside every pinned fact's truth window.

    A fact carrying `effectiveFrom`/`effectiveTo` is live only inside it, so
    moving the evaluation point outside would contradict the `exists` pin just
    made. `smt.py` does not model fact windows — it reasons about a rulebase,
    where facts are free — so the constraint belongs here.
    """
    var = enc.vars["asOf:effective"]
    terms = []
    for curie, fact in sorted(live.items()):
        if f"attr:{curie}" not in enc.symbols:
            continue
        if fact.get("effectiveFrom") is not None:
            terms.append(
                var >= _cf.normalize_point(str(fact["effectiveFrom"])).date().toordinal()
            )
        if fact.get("effectiveTo") is not None:
            terms.append(
                var < _cf.normalize_point(str(fact["effectiveTo"])).date().toordinal()
            )
    return terms


def _solver(*terms):
    s = z3.Solver()
    s.set("rlimit", RLIMIT)
    for t in terms:
        s.add(t)
    return s


# ---------------------------------------------------------------------------
# Finite domains: enumerate, and verify every member
# ---------------------------------------------------------------------------


def _answer_finite(query, enc, sym, key, base, target, template, report) -> None:
    """Booleans, strings and codes.

    No ordering, so no extremal — but a finite domain admits something
    stronger than a boundary check: every member is run through the kernel,
    satisfying or not, and *both* verdicts are verified. That makes the answer
    set complete without leaning on the encoding at all, which is the one
    place in this package where the UNSAT asymmetry does not bite.
    """
    var = enc.vars[key]
    if sym.kind == "boolean":
        members = [(False, "false", z3.Not(var)), (True, "true", var)]
    else:
        members = [
            (v, v, var == z3.IntVal(i)) for i, v in enumerate(sym.values)
        ]

    for raw, label, term in members:
        satisfiable = _solver(*base, term).check() == z3.sat
        residual = raw == OTHER and sym.kind != "boolean"
        concrete = OTHER_REPRESENTATIVE if residual else raw
        value = _fact_value(sym, template, concrete)
        outcome = _run(query, sym, key, value)
        _guard(
            query, sym, outcome, target, satisfiable, label, value,
            claim=(
                f"{sym.label} = {label} "
                f"{'reaches' if satisfiable else 'does not reach'} the target"
            ),
        )
        if not satisfiable:
            continue
        others = ", ".join(f'"{v}"' for v in sym.values if v != OTHER)
        report.answers.append(
            Answer(
                value=f"any value other than {others}" if residual else label,
                fact_value=value, decision=outcome.render(),
                representative=OTHER_REPRESENTATIVE if residual else None,
                note=(
                    "an open code set has no enumerable residual, so this region "
                    "was verified with one representative value"
                    if residual else None
                ),
            )
        )

    report.complete = True
    if report.answers:
        report.verdict = SATISFIABLE
        report.notes.append(
            f"every member of {sym.label}'s domain was run through the kernel — "
            f"the satisfying ones and the rest — so this answer set is complete "
            f"and pointwise verified, with nothing resting on the encoding"
        )
    else:
        report.verdict = UNSATISFIABLE
        domain = "true, false" if sym.kind == "boolean" else ", ".join(sym.values)
        report.reason = (
            f"no value in {sym.label}'s domain ({domain}) produces the target — "
            f"and here that is verified rather than inferred: the kernel refused "
            f"every member individually"
        )


# ---------------------------------------------------------------------------
# Ordered domains: optimize on the grid, then verify the value and the step
# ---------------------------------------------------------------------------


def _grid(query, sym, template) -> int:
    """The decimal scale a freed ordered input is searched on (0 for a date)."""
    if sym.kind == "date":
        return 0
    if query.scale is not None:
        return query.scale
    return _value_scale(template) if template else 2


def _answer_ordered(query, enc, sym, key, base, target, template, report) -> None:
    var = enc.vars[key]
    scale = _grid(query, sym, template)

    if sym.kind == "date":
        objective, grid_terms = var, []
        to_raw = _dt.date.fromordinal
        anchor_raw = (
            _cf.parse_date(query.as_of_effective) if sym.origin == "asOf"
            else _cf.parse_date(str(template["value"]))
        )
        anchor = anchor_raw.toordinal()
    else:
        # duly money is a decimal, not a real. Pinning the freed symbol to its
        # own decimal grid is a NARROWING — the one place this module departs
        # from `prove`'s widen-only rule — and it is what makes an extremal
        # attainable, and therefore verifiable, at all.
        step_var = z3.Int(f"whatif!grid!{key}")
        grid_terms = [var == z3.ToReal(step_var) / z3.RealVal(10 ** scale)]
        objective = step_var
        to_raw = lambda k: Decimal(k).scaleb(-scale)  # noqa: E731
        current = Decimal(str(template["amount" if sym.kind == "money" else "value"]))
        anchor = int(current.scaleb(scale).to_integral_value())
        report.notes.append(
            f"{sym.label} was searched on its decimal grid at scale {scale} "
            f"(step {Decimal(1).scaleb(-scale)}); duly decimals and money are "
            f"decimal strings rather than reals, so that is where the answers "
            f"live. An UNSATISFIABLE verdict therefore means 'no value at this "
            f"scale'"
        )

    if query.flip:
        best, direction, step = _nearest(base + grid_terms, objective, anchor)
    else:
        direction = query.extremal if query.extremal in ("max", "min") else "max"
        best = _optimize(base + grid_terms, objective, direction)
        step = 1 if direction == "max" else -1

    if best is None:
        report.verdict = UNSATISFIABLE
        report.extremal_direction = direction
        report.reason = _unsat_reason(sym, scale)
        return
    if best == "unbounded":
        # The satisfying region runs to infinity the way the caller asked, so
        # there is no extremal there to verify. Returning that as the whole
        # answer would hand back an unverified claim, which is the one thing
        # this package must not do — so report the region's *other* end, which
        # is a value the kernel can be handed.
        best, direction, step = _open_region(
            base + grid_terms, objective, direction, anchor, report, sym
        )
        if best is None:  # pragma: no cover - a satisfiable region has an end
            report.verdict = UNSATISFIABLE
            report.reason = _unsat_reason(sym, scale)
            return

    raw = to_raw(best)
    value = _fact_value(sym, template, raw)
    outcome = _run(query, sym, key, value)
    _guard(
        query, sym, outcome, target, True, _render_raw(raw), value,
        claim=f"{sym.label} = {_render_raw(raw)} reaches the target",
    )
    answer = Answer(
        value=_render_raw(raw), fact_value=value, decision=outcome.render()
    )
    report.extremal = answer
    report.extremal_direction = direction
    report.answers.append(answer)
    report.verdict = SATISFIABLE

    if sym.kind == "date" and not (
        DATE_MIN.toordinal() < best < DATE_MAX.toordinal() - 1
    ):
        report.unbounded = True
        report.notes.append(
            f"the extremal sits on the encoding's own date bound "
            f"[{DATE_MIN.isoformat()}, {DATE_MAX.isoformat()}), so it is a limit "
            f"of the fragment rather than of the rulebase"
        )
        return

    _verify_boundary(query, sym, key, target, template, best, step, to_raw, report)


def _unsat_reason(sym, scale: int) -> str:
    grid = "" if sym.kind == "date" else f" at scale {scale}"
    return (
        f"no value of {sym.label}{grid} produces the target, on any input the "
        f"fragment can express"
    )


def _optimize(terms, objective, direction):
    """The optimum of `objective`: `None` if unsatisfiable, "unbounded" if open.

    Z3's `Optimize` returns a *unique* optimum for the objective even when the
    model around it is not unique, and that is what makes this deterministic
    without a normalization ladder: the answer is a property of the constraint
    set rather than of the solver's search. `prove` needs the ladder because it
    prints a whole witness; here the freed symbol is the only degree of freedom
    and the question itself pins which of its values to report.
    """
    opt = z3.Optimize()
    opt.set("rlimit", RLIMIT)
    for t in terms:
        opt.add(t)
    handle = opt.maximize(objective) if direction == "max" else opt.minimize(objective)
    result = opt.check()
    if result == z3.unsat:
        return None
    if result == z3.unknown:  # pragma: no cover - needs a query above the rlimit
        raise Unsupported(
            "the solver returned unknown inside the deterministic resource "
            "limit; no claim is made either way"
        )
    bound = opt.upper(handle) if direction == "max" else opt.lower(handle)
    if not z3.is_int_value(bound):
        return "unbounded"
    return bound.as_long()


def _open_region(terms, objective, direction, anchor, report, sym):
    """Where to look when the satisfying region has no extremal that way.

    Two shapes, and both end in something the kernel can check:

    - a **ray** — unbounded one way, bounded the other. Its finite end is the
      informative answer anyway ("every value from X upward reaches the
      target"), and it comes with a boundary step that can be refuted.
    - **everything** — unbounded both ways. Then today's own value satisfies
      too, so it is the witness: deterministic, already in the case, and the
      first thing a reader would sanity-check.
    """
    report.unbounded = True
    opposite = "min" if direction == "max" else "max"
    other = _optimize(terms, objective, opposite)
    if other is not None and other != "unbounded":
        report.notes.append(
            f"the satisfying region is unbounded toward {direction}: nothing in "
            f"the fragment bounds {sym.label} that way. Its {opposite} end is "
            f"reported instead, because that is the end with a value the kernel "
            f"can be handed"
        )
        return other, opposite, (1 if opposite == "max" else -1)

    report.notes.append(
        f"every value of {sym.label} the fragment can express reaches the "
        f"target, so there is no boundary anywhere. Today's own value is "
        f"reported as the witness, and it was verified like any other answer"
    )
    return anchor, "any", 0


def _nearest(terms, objective, anchor):
    """The satisfying value closest to today's, and the step back toward today.

    The interesting flip is not the extreme one, it is the *cheapest*: how
    little would have to change. Ties (one step up and one step down both
    flip) resolve to the larger value, deterministically, and the reported
    boundary is the step back toward today's value — which is the step that
    must NOT flip if this really is the nearest one.
    """
    distance = z3.If(objective >= anchor, objective - anchor, anchor - objective)
    found = _optimize(terms, distance, "min")
    if found is None or found == "unbounded":
        return found, "nearest", -1
    best = _optimize(terms + [distance == z3.IntVal(found)], objective, "max")
    return best, "nearest", (-1 if best > anchor else 1)


def _verify_boundary(query, sym, key, target, template, best, step, to_raw, report):
    """Run the kernel one step beyond the extremal and require a refutation.

    What this establishes, exactly — and the distinction is worth stating
    rather than implying: the kernel confirms that the extremal value hits the
    target, and that the next value along does not. It does *not* establish
    that nothing further out hits it. That last part is the maximality claim;
    it is an UNSAT claim; and like every UNSAT claim here it rests on the
    encoding rather than on a kernel run.
    """
    if step == 0:
        # Every value satisfies, so there is no step that could be refuted.
        report.boundary = Boundary(
            value="(none)", decision="(not evaluated)", refuted=False,
            note="the satisfying region has no boundary: every value reaches the target",
        )
        return
    beyond = to_raw(best + step)
    if isinstance(beyond, _dt.date) and not (DATE_MIN <= beyond < DATE_MAX):
        report.boundary = Boundary(
            value=_render_raw(beyond), decision="(not evaluated)", refuted=False,
            note="one step beyond leaves the encoded date range",
        )
        return
    value = _fact_value(sym, template, beyond)
    outcome = _run(query, sym, key, value)
    _guard(
        query, sym, outcome, target, False, _render_raw(beyond), value,
        claim=(
            f"{sym.label} = {_render_raw(beyond)}, one step "
            f"{'beyond' if report.extremal_direction != 'nearest' else 'back toward today from'} "
            f"the answer, does not reach the target"
        ),
    )
    report.boundary = Boundary(
        value=_render_raw(beyond), decision=outcome.render(), refuted=True
    )


# ---------------------------------------------------------------------------
# The kernel, and the guard
# ---------------------------------------------------------------------------


def _rebuilt(query: Query, sym, value: dict):
    """(facts, as-of) for the hypothetical case with the freed input set."""
    if sym.origin == "asOf":
        return query.facts, str(value["value"])
    return _cf.substitute(query.facts, sym.curie, value), query.as_of_effective


def _run(query: Query, sym, key: str, value: dict) -> _cf.KernelOutcome:
    """Rebuild the case with the freed input set to `value`, and adjudicate."""
    facts, as_of = _rebuilt(query, sym, value)
    return _cf.decide(
        facts, query.pack, as_of, query.as_of_knowledge, query.decision
    )


def _guard(query, sym, outcome, target, should_match, label, value, *, claim) -> None:
    """The contract, enforced: the kernel is the only thing that decides."""
    if outcome.matches(target) == should_match:
        return
    facts, as_of = _rebuilt(query, sym, value)
    raise SolverKernelContradiction(
        claim=claim, value=label,
        expected=(
            f"the target ({_cf.render_value(target) if target else 'no decision'})"
            if should_match else "some decision other than the target"
        ),
        outcome=outcome, facts=facts, as_of_effective=as_of,
    )
