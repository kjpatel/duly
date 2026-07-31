"""Static pack verification: python -m duly_assurance prove | prove-equivalent.

Two analyses over the SMT encoding in `smt.py`, both **validation-time only**:
no solver output reaches a receipt, and neither subcommand changes any
adjudication.

`prove <pack>...`
  For every pair of same-priority rules concluding one attribute, one of
  PROVED-DISJOINT / NOT-PROVED (with a readable witness) / OUT-OF-FRAGMENT
  (naming the construct). Plus rule reachability and, per decision
  attribute, the input regions no rule covers.

`prove-equivalent <packA> <packB>`
  Whether two packs conclude the same value for an attribute over the whole
  input space, rather than over a fixture list.

Exit codes — `prove`: 1 when a NOT-PROVED pair has no explicit `overrides`
between its rules, else 0 (an OUT-OF-FRAGMENT verdict or an uncovered
region is a finding, not a failure). `prove-equivalent`: 0 proved,
1 not proved, 2 out of fragment.

Design decisions and their rationale: spec/pack-verification.md.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from duly_kernel import ir as _ir

from .smt import (
    DATE_MAX,
    DATE_MIN,
    OTHER,
    OutOfFragment,
    PackEncoding,
    Universe,
    date_literals,
    numeric_literals,
)

try:  # pragma: no cover - the CLI reports this properly
    import z3
except ImportError:  # pragma: no cover
    z3 = None  # type: ignore[assignment]


Z3_MISSING = (
    "z3-solver is not installed. `prove` is an optional analysis behind an "
    "optional dependency:\n"
    "    uv run --with z3-solver python -m duly_assurance prove rulepacks/*/pack.yaml\n"
    "or `uv sync --extra prove`."
)

# Deterministic resource ceiling. Not a timeout: z3's rlimit counts solver
# work, not wall-clock time, so the same query gives the same answer on a
# fast machine and a slow one. A repo invariant, not a nicety.
RLIMIT = 40_000_000

PROVED_DISJOINT = "PROVED-DISJOINT"
NOT_PROVED = "NOT-PROVED"
OUT_OF_FRAGMENT = "OUT-OF-FRAGMENT"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class PairResult:
    attribute: str
    priority: int
    left: str
    right: str
    verdict: str
    reason: str | None = None
    witness: list[tuple[str, str]] = field(default_factory=list)
    witness_exact: bool = True
    overrides: str | None = None  # "B overrides A" when the pack says so

    @property
    def fatal(self) -> bool:
        """Only a *same-priority* overlap with no authored exception fails.

        At differing priorities the kernel's tiebreak already picks a winner
        deterministically, so an overlap there is information, not ambiguity.
        """
        return (
            self.verdict == NOT_PROVED
            and self.overrides is None
            and self.priority >= 0
        )


@dataclass
class CoverageResult:
    attribute: str
    covered: bool
    verdict: str
    reason: str | None = None
    witness: list[tuple[str, str]] = field(default_factory=list)
    witness_exact: bool = True


@dataclass
class ReachResult:
    rule_id: str
    reachable: bool
    verdict: str
    reason: str | None = None


@dataclass
class PackReport:
    path: str
    name: str
    version: str
    ontology: str | None
    pairs: list[PairResult] = field(default_factory=list)
    coverage: list[CoverageResult] = field(default_factory=list)
    reachability: list[ReachResult] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def fatal(self) -> bool:
        return any(p.fatal for p in self.pairs) or self.error is not None


# ---------------------------------------------------------------------------
# Witness normalization
# ---------------------------------------------------------------------------


class Witness:
    """Turns a satisfying assignment into a stable, readable one.

    Z3 models are not canonical: two runs, two versions, or two machines may
    each return a different satisfying assignment. Rather than trust the
    solver's choice, the normalizer walks the symbols in sorted order and
    *pins* each one to the first value from a static candidate ladder that
    keeps the query satisfiable. The result depends only on satisfiability
    answers and the ladder — both of which are properties of the pack, not
    of the solver's search — so the printed witness is stable.

    The ladders are drawn from the pack's own vocabulary (its numeric
    literals, its effective dates, its calendar bounds), which also makes
    the witness readable: `45`, not `8317/193`.
    """

    def __init__(self, packs: list[dict]):
        self.numbers = self._number_ladder(packs)
        self.dates = self._date_ladder(packs)

    @staticmethod
    def _number_ladder(packs: list[dict]) -> list[Decimal]:
        seeds = {Decimal(0), Decimal(1)}
        for pack in packs:
            seeds.update(numeric_literals(pack))
        out: set[Decimal] = set()
        for s in seeds:
            for delta in (Decimal(0), Decimal("0.01"), Decimal(1)):
                out.add(s + delta)
                out.add(s - delta)
        return sorted(out, key=lambda d: (abs(d), d))

    @staticmethod
    def _date_ladder(packs: list[dict]) -> list[_dt.date]:
        """The pack's own dates first, the lower bound only as a last resort.

        Preferring the pack's vocabulary keeps a date witness meaningful: an
        evaluation point of 2015-10-03 says something about the rulebase,
        1900-01-01 only says the ladder started there.
        """
        seeds: set[_dt.date] = set()
        for pack in packs:
            seeds.update(date_literals(pack))
        out: set[_dt.date] = set()
        for s in seeds:
            for delta in (0, 1, -1, 2, 3):
                d = s + _dt.timedelta(days=delta)
                if DATE_MIN <= d < DATE_MAX:
                    out.add(d)
        ladder = sorted(out)
        if DATE_MIN not in out:
            ladder.append(DATE_MIN)
        return ladder

    def pin(self, solver, encodings: list[PackEncoding], keys: list[str]) -> tuple[list, bool]:
        """Pin every symbol in `keys`; return (assignments, exact)."""
        symbols = {}
        variables = {}
        exists = {}
        for enc in encodings:
            for key in keys:
                if key in enc.symbols and key in enc.vars:
                    symbols.setdefault(key, enc.symbols[key])
                    variables.setdefault(key, enc.vars[key])
                    if key in enc.exists:
                        exists.setdefault(key, enc.exists[key])

        # A derived value is a function of the inputs, so once every input is
        # pinned the model has no freedom left in it — pinning it would be
        # redundant, and failing to pin it says nothing about determinism.
        determined = set()
        for enc in encodings:
            determined |= {
                enc._dkey(c)
                for c in enc.concluded_attributes()
                if c not in enc.value_gaps
            }

        exact = True
        # Existence first, preferring a populated case: a witness that names
        # concrete values reads better than one that says everything is
        # absent. A failed pin means asserting existence was unsatisfiable,
        # which is itself the answer — no second query needed.
        present: dict[str, bool] = {}
        for key in sorted(k for k in symbols if k in exists):
            present[key] = self._try(solver, exists[key])
        for key in sorted(symbols):
            sym, var = symbols[key], variables[key]
            if key in determined or not present.get(key, True):
                continue
            if not self._pin_value(solver, sym, var):
                exact = False

        if solver.check() != z3.sat:  # pragma: no cover - pins never remove models
            return [], False
        model = solver.model()

        rows = []
        for key in sorted(symbols):
            sym, var = symbols[key], variables[key]
            if key in exists and not _model_bool(model, exists[key]):
                absent = (
                    "(no conclusion)" if sym.origin == "derived" else "(no fact asserted)"
                )
                rows.append((sym.label, absent))
                continue
            rows.append((sym.label, _render(sym, model.eval(var, model_completion=True))))
        return rows, exact

    def _pin_value(self, solver, sym, var) -> bool:
        if sym.kind == "boolean":
            return self._try(solver, z3.Not(var)) or self._try(solver, var)
        if sym.kind == "date":
            return any(self._try(solver, var == d.toordinal()) for d in self.dates)
        if sym.kind in ("string", "code"):
            return any(self._try(solver, var == i) for i in range(len(sym.values)))
        return any(self._try(solver, var == z3.RealVal(str(n))) for n in self.numbers)

    @staticmethod
    def _try(solver, term) -> bool:
        solver.push()
        solver.add(term)
        ok = solver.check() == z3.sat
        solver.pop()
        if ok:
            solver.add(term)
        return ok


def _model_bool(model, term) -> bool:
    return z3.is_true(model.eval(term, model_completion=True))


def _render(sym, value) -> str:
    if sym.kind == "boolean":
        return "true" if z3.is_true(value) else "false"
    if sym.kind == "date":
        return _dt.date.fromordinal(value.as_long()).isoformat()
    if sym.kind in ("string", "code"):
        idx = value.as_long()
        values = sym.values
        name = values[idx] if 0 <= idx < len(values) else OTHER
        return name if name == OTHER else f'"{name}"'
    frac = value.as_fraction()
    if frac.denominator == 1:
        return str(frac.numerator)
    dec = Decimal(frac.numerator) / Decimal(frac.denominator)
    return format(dec.normalize(), "f")


def _solver(*terms):
    s = z3.Solver()
    s.set("rlimit", RLIMIT)
    for t in terms:
        s.add(t)
    return s


# ---------------------------------------------------------------------------
# The analyses
# ---------------------------------------------------------------------------


def analyze_pack(path: Path, pack: dict, registry, *, all_pairs: bool = False) -> PackReport:
    meta = pack["pack"]
    ontology = None
    if meta.get("ontology"):
        ontology = f"{meta['ontology']}@{meta.get('ontologyVersion')}"
    report = PackReport(
        path=str(path), name=meta["name"], version=meta["version"], ontology=ontology
    )

    universe = Universe(registry)
    try:
        universe.observe(pack)
        universe.finalize()
        enc = PackEncoding(pack, universe)
    except OutOfFragment as exc:
        report.error = str(exc)
        return report

    report.assumptions = list(enc.assumption_labels())
    report.notes = list(universe.notes) + list(enc.notes)
    for curie, reason in sorted(enc.applicability_gaps.items()):
        report.notes.append(f"{curie}: applicability widened to a free variable — {reason}")
    for curie, reason in sorted(enc.value_gaps.items()):
        if curie not in enc.applicability_gaps:
            report.notes.append(f"{curie}: value widened to a free variable — {reason}")

    witness = Witness([pack])
    domain = enc.domain()

    _reachability(enc, domain, report)
    _pairs(enc, domain, report, witness, all_pairs=all_pairs)
    _coverage(enc, pack, domain, report, witness)
    return report


def _reachability(enc: PackEncoding, domain: list, report: PackReport) -> None:
    for rule in enc.rules:
        r = enc.encodings[rule["id"]]
        if r.fires is None:
            report.reachability.append(
                ReachResult(rule["id"], False, OUT_OF_FRAGMENT, r.out_of_fragment)
            )
            continue
        result = _solver(*domain, r.fires).check()
        if result == z3.unsat:
            report.reachability.append(
                ReachResult(rule["id"], False, NOT_PROVED, "no input makes this rule fire")
            )
        elif result == z3.sat:
            report.reachability.append(ReachResult(rule["id"], True, PROVED_DISJOINT))
        else:
            report.reachability.append(
                ReachResult(rule["id"], False, OUT_OF_FRAGMENT, "solver returned unknown")
            )


def _pairs(
    enc: PackEncoding,
    domain: list,
    report: PackReport,
    witness: Witness,
    *,
    all_pairs: bool,
) -> None:
    by_attr: dict[str, list[dict]] = {}
    for rule in enc.rules:
        by_attr.setdefault(rule["then"]["attribute"], []).append(rule)

    for attribute in sorted(by_attr):
        group = by_attr[attribute]
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if not all_pairs and a["priority"] != b["priority"]:
                    continue
                report.pairs.append(_pair(enc, domain, witness, attribute, a, b))


def _pair(enc, domain, witness, attribute, a, b) -> PairResult:
    priority = a["priority"] if a["priority"] == b["priority"] else -1
    override = None
    if b["id"] in (a.get("overrides") or []):
        override = f"{a['id']} overrides {b['id']}"
    elif a["id"] in (b.get("overrides") or []):
        override = f"{b['id']} overrides {a['id']}"

    ea, eb = enc.encodings[a["id"]], enc.encodings[b["id"]]
    for e in (ea, eb):
        if e.fires is None:
            return PairResult(
                attribute, priority, a["id"], b["id"], OUT_OF_FRAGMENT,
                reason=f"{e.rule_id}: {e.out_of_fragment}", overrides=override,
            )

    solver = _solver(*domain, ea.fires, eb.fires)
    result = solver.check()
    if result == z3.unsat:
        return PairResult(
            attribute, priority, a["id"], b["id"], PROVED_DISJOINT, overrides=override
        )
    if result == z3.unknown:
        return PairResult(
            attribute, priority, a["id"], b["id"], OUT_OF_FRAGMENT,
            reason="solver returned unknown (resource limit or an undecided theory)",
            overrides=override,
        )
    keys = enc.closure(set(ea.symbols) | set(eb.symbols) | {"asOf:effective"})
    widened = enc.widened_in(keys)
    if widened:
        # SAT over a widened space proves nothing: the assignment may not be
        # reachable. Reporting it as an overlap would be a guess.
        return PairResult(
            attribute, priority, a["id"], b["id"], OUT_OF_FRAGMENT,
            reason=(
                "an assignment firing both rules exists, but it rests on a "
                "widened symbol, so it may be unreachable: " + "; ".join(widened)
            ),
            overrides=override,
        )
    rows, exact = witness.pin(solver, [enc], keys)
    return PairResult(
        attribute, priority, a["id"], b["id"], NOT_PROVED,
        reason="both rules fire under this assignment",
        witness=rows, witness_exact=exact, overrides=override,
    )


def _coverage(enc, pack, domain, report, witness) -> None:
    declared = [d["attribute"] for d in pack.get("decisions") or []]
    attributes = declared or enc.concluded_attributes()
    for attribute in sorted(set(attributes)):
        if not enc.rules_for(attribute):
            report.coverage.append(
                CoverageResult(
                    attribute, False, OUT_OF_FRAGMENT,
                    reason="declared as a decision but no rule in this pack concludes it",
                )
            )
            continue
        try:
            term = enc.coverage_term(attribute)
        except OutOfFragment as exc:
            report.coverage.append(
                CoverageResult(attribute, False, OUT_OF_FRAGMENT, reason=str(exc))
            )
            continue
        solver = _solver(*domain, z3.Not(term))
        result = solver.check()
        if result == z3.unsat:
            report.coverage.append(CoverageResult(attribute, True, PROVED_DISJOINT))
            continue
        if result == z3.unknown:
            report.coverage.append(
                CoverageResult(
                    attribute, False, OUT_OF_FRAGMENT, reason="solver returned unknown"
                )
            )
            continue

        # An uncovered region reachable only by evaluating outside every
        # concluding rule's effective window is a different (and much less
        # interesting) finding from a live-rulebase gap. Ask for the live one
        # first; fall back only when there is none.
        reason = None
        solver.push()
        solver.add(enc.in_force_term(attribute))
        if solver.check() != z3.sat:
            solver.pop()
            reason = (
                "the only uncovered region is an evaluation point outside every "
                "concluding rule's effective window"
            )
        keys = enc.closure(
            {k for r in enc.rules_for(attribute) for k in enc.encodings[r["id"]].symbols}
            | {"asOf:effective"}
        )
        widened = enc.widened_in(keys)
        if widened:
            report.coverage.append(
                CoverageResult(
                    attribute, False, OUT_OF_FRAGMENT,
                    reason=(
                        "an uncovered assignment exists, but it rests on a widened "
                        "symbol, so it may be unreachable: " + "; ".join(widened)
                    ),
                )
            )
            continue
        rows, exact = witness.pin(solver, [enc], keys)
        report.coverage.append(
            CoverageResult(
                attribute, False, NOT_PROVED, reason=reason,
                witness=rows, witness_exact=exact,
            )
        )


# ---------------------------------------------------------------------------
# Equivalence
# ---------------------------------------------------------------------------


@dataclass
class EquivalenceResult:
    attribute: str
    verdict: str
    reason: str | None = None
    witness: list[tuple[str, str]] = field(default_factory=list)
    witness_exact: bool = True
    left_value: str | None = None
    right_value: str | None = None


@dataclass
class TraceResult:
    """Whether two packs produce the same receipt rule trace everywhere."""

    verdict: str
    reason: str | None = None
    witness: list[tuple[str, str]] = field(default_factory=list)
    witness_exact: bool = True
    differences: list[str] = field(default_factory=list)
    shared_rules: int = 0


@dataclass
class EquivalenceReport:
    name_a: str
    name_b: str
    decisions: list[EquivalenceResult] = field(default_factory=list)
    trace: TraceResult | None = None
    only_a: list[str] = field(default_factory=list)
    only_b: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        if self.error:
            return 2
        verdicts = [d.verdict for d in self.decisions]
        if self.trace is not None:
            verdicts.append(self.trace.verdict)
        if NOT_PROVED in verdicts:
            return 1
        if OUT_OF_FRAGMENT in verdicts or not verdicts:
            return 2
        return 0


def _joint(pack_a: dict, pack_b: dict, registry):
    universe = Universe(registry)
    universe.observe(pack_a)
    universe.observe(pack_b)
    universe.finalize()
    enc_a = PackEncoding(pack_a, universe, tag="A")
    enc_b = PackEncoding(pack_b, universe, tag="B")
    return universe, enc_a, enc_b


def equivalence_report(
    pack_a: dict, pack_b: dict, registry, attributes: list[str] | None = None
) -> EquivalenceReport:
    """Compare two packs over the input space, at two levels.

    **Decision equivalence** asks whether the two packs conclude the same
    value for an attribute. **Trace equivalence** asks whether the same rules
    apply, the same rule wins, and the same defeat chain is recorded — the
    receipt fields `spec/dmn.md`'s fixture-based suite compares.

    The second level is not decoration. A change can leave every decision
    identical and still change every receipt: `> disclosed` becoming
    `>= disclosed` makes the cure rule fire (and defeat the default) exactly
    when the two amounts are equal, and conclude the same `0.00` either way.
    A tool that only compared decisions would call that pair equivalent.

    The two packs share the *input* universe — attribute facts and the
    evaluation point — and keep separate derived namespaces, because a
    derived value is something a pack computes, not something the case
    supplies.
    """
    report = EquivalenceReport(pack_a["pack"]["name"], pack_b["pack"]["name"])
    try:
        universe, enc_a, enc_b = _joint(pack_a, pack_b, registry)
    except OutOfFragment as exc:
        report.error = str(exc)
        return report

    report.assumptions = sorted(
        set(enc_a.assumption_labels()) | set(enc_b.assumption_labels())
    )
    ids_a = {r["id"] for r in pack_a["rules"]}
    ids_b = {r["id"] for r in pack_b["rules"]}
    report.only_a = sorted(ids_a - ids_b)
    report.only_b = sorted(ids_b - ids_a)

    domain = enc_a.domain() + enc_b.domain()
    witness = Witness([pack_a, pack_b])
    input_keys = sorted(universe.symbols)

    if attributes is None:
        attributes = sorted(
            {r["then"]["attribute"] for r in pack_a["rules"]}
            & {r["then"]["attribute"] for r in pack_b["rules"]}
        )
    for attribute in attributes:
        report.decisions.append(
            _decision_equivalence(
                attribute, enc_a, enc_b, domain, witness, input_keys
            )
        )
    report.trace = _trace_equivalence(
        sorted(ids_a & ids_b), enc_a, enc_b, domain, witness, input_keys
    )
    return report


def _decision_equivalence(attribute, enc_a, enc_b, domain, witness, input_keys):
    try:
        defined_a, value_a = enc_a.decision_value(attribute)
        defined_b, value_b = enc_b.decision_value(attribute)
    except OutOfFragment as exc:
        return EquivalenceResult(attribute, OUT_OF_FRAGMENT, reason=str(exc))

    sym_a = enc_a.symbols[enc_a._dkey(attribute)]
    sym_b = enc_b.symbols[enc_b._dkey(attribute)]
    if sym_a.kind != sym_b.kind:
        return EquivalenceResult(
            attribute, OUT_OF_FRAGMENT,
            reason=(
                f"the two packs conclude {attribute} with different value kinds "
                f"({sym_a.kind} vs {sym_b.kind})"
            ),
        )
    if sym_a.kind in ("string", "code") and sym_a.values != sym_b.values:
        return EquivalenceResult(
            attribute, OUT_OF_FRAGMENT,
            reason=(
                f"the two packs give {attribute} different value domains "
                f"({', '.join(sym_a.values)} vs {', '.join(sym_b.values)}) — "
                f"the finite-domain indices are not comparable"
            ),
        )

    disagree = z3.Or(
        defined_a != defined_b,
        z3.And(defined_a, defined_b, value_a != value_b),
    )
    solver = _solver(*domain, disagree)
    result = solver.check()
    if result == z3.unsat:
        return EquivalenceResult(
            attribute, PROVED_DISJOINT,
            reason="the two packs conclude the same value on every input the fragment can express",
        )
    if result == z3.unknown:
        return EquivalenceResult(
            attribute, OUT_OF_FRAGMENT, reason="solver returned unknown"
        )

    rows, exact = witness.pin(solver, [enc_a, enc_b], input_keys)
    model = solver.model()
    left = (
        _render(sym_a, model.eval(value_a, model_completion=True))
        if _model_bool(model, defined_a) else "(no decision)"
    )
    right = (
        _render(sym_b, model.eval(value_b, model_completion=True))
        if _model_bool(model, defined_b) else "(no decision)"
    )
    return EquivalenceResult(
        attribute, NOT_PROVED, reason="the two packs disagree under this assignment",
        witness=rows, witness_exact=exact, left_value=left, right_value=right,
    )


def _trace_equivalence(shared, enc_a, enc_b, domain, witness, input_keys) -> TraceResult:
    """Same rules apply, same rule wins, same defeat chain — everywhere.

    Rules are matched by id, which is the handle the receipt cites. Priority
    numbers are deliberately *not* compared: `spec/dmn.md` M2 establishes that
    compiled priorities are derived from hit policy and row order, so what
    must match is the outcome of the tiebreak, not the numbers feeding it.
    """
    if not shared:
        return TraceResult(
            OUT_OF_FRAGMENT, reason="the two packs share no rule id, so no trace to compare"
        )
    claims: list[tuple[str, object]] = []
    try:
        for rid in shared:
            ea, eb = enc_a.encodings[rid], enc_b.encodings[rid]
            for label, term_a, term_b in (
                ("applies", ea.fires, eb.fires),
                ("wins its attribute", ea.wins, eb.wins),
            ):
                if term_a is None or term_b is None:
                    reason = ea.out_of_fragment or eb.out_of_fragment or "no term"
                    return TraceResult(
                        OUT_OF_FRAGMENT, reason=f"rule {rid} ({label}): {reason}"
                    )
                claims.append((f"{rid} {label}", term_a != term_b))
            for other in shared:
                if other == rid:
                    continue
                claims.append(
                    (
                        f"{rid} defeats {other}",
                        enc_a.defeats(rid, other) != enc_b.defeats(rid, other),
                    )
                )
    except OutOfFragment as exc:
        return TraceResult(OUT_OF_FRAGMENT, reason=str(exc))

    solver = _solver(*domain, z3.Or(*[t for _label, t in claims]))
    result = solver.check()
    if result == z3.unsat:
        return TraceResult(
            PROVED_DISJOINT,
            reason=(
                "the same rules apply, the same rule wins, and the same defeat "
                "chain is recorded on every input the fragment can express"
            ),
            shared_rules=len(shared),
        )
    if result == z3.unknown:
        return TraceResult(OUT_OF_FRAGMENT, reason="solver returned unknown")

    rows, exact = witness.pin(solver, [enc_a, enc_b], input_keys)
    model = solver.model()
    differences = [label for label, term in claims if _model_bool(model, term)]
    return TraceResult(
        NOT_PROVED,
        reason="the two packs record different rule traces under this assignment",
        witness=rows, witness_exact=exact, differences=differences,
        shared_rules=len(shared),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _witness_lines(rows: list[tuple[str, str]], exact: bool, indent: str) -> list[str]:
    out = [f"{indent}witness:"]
    width = max((len(label) for label, _ in rows), default=0)
    for label, value in rows:
        out.append(f"{indent}  {label.ljust(width)}  {value}")
    if not exact:
        out.append(
            f"{indent}  (one or more values came from the solver rather than the "
            f"pack's own vocabulary; see spec/pack-verification.md)"
        )
    return out


def render(report: PackReport, *, verbose: bool = False) -> str:
    lines: list[str] = []
    head = f"pack {report.name} {report.version}"
    if report.ontology:
        head += f"  (ontology {report.ontology})"
    lines.append(head)
    lines.append(f"  source: {report.path}")
    if report.error:
        lines.append(f"  {OUT_OF_FRAGMENT}: {report.error}")
        return "\n".join(lines)

    unreachable = [r for r in report.reachability if r.verdict == NOT_PROVED]
    oof = [r for r in report.reachability if r.verdict == OUT_OF_FRAGMENT]
    lines.append("")
    lines.append(f"  rules: {len(report.reachability)}")
    if unreachable:
        for r in unreachable:
            lines.append(f"    UNREACHABLE  {r.rule_id}  ({r.reason})")
    else:
        lines.append("    every rule is reachable: some input makes it fire")
    for r in oof:
        lines.append(f"    {OUT_OF_FRAGMENT}  {r.rule_id}: {r.reason}")

    lines.append("")
    if not report.pairs:
        lines.append("  same-priority pairs concluding one attribute: none")
    else:
        lines.append(f"  rule pairs concluding one attribute: {len(report.pairs)}")
        for p in report.pairs:
            prio = f"priority {p.priority}" if p.priority >= 0 else "mixed priority"
            lines.append(f"    {p.verdict}  {p.left} / {p.right}")
            lines.append(f"      {p.attribute}, {prio}")
            if p.reason:
                lines.append(f"      {p.reason}")
            if p.overrides and p.verdict == NOT_PROVED:
                lines.append(
                    f"      resolved by an authored exception: {p.overrides} — the "
                    f"overridden rule is suppressed whenever both fire, so the "
                    f"kernel is never ambiguous here"
                )
            elif p.overrides:
                lines.append(f"      (the pack also declares: {p.overrides})")
            if p.witness:
                lines.extend(_witness_lines(p.witness, p.witness_exact, "      "))

    lines.append("")
    lines.append("  coverage of the pack's decision attributes:")
    for c in report.coverage:
        if c.covered:
            lines.append(f"    COVERED      {c.attribute}")
            lines.append("      every input in the fragment reaches some conclusion")
        elif c.verdict == OUT_OF_FRAGMENT:
            lines.append(f"    {OUT_OF_FRAGMENT}  {c.attribute}")
            lines.append(f"      {c.reason}")
        else:
            lines.append(f"    UNCOVERED    {c.attribute}")
            lines.append(f"      {c.reason or 'no rule concludes it under this assignment'}")
            lines.extend(_witness_lines(c.witness, c.witness_exact, "      "))

    if report.notes:
        lines.append("")
        lines.append("  notes:")
        for note in report.notes:
            lines.append(f"    - {note}")
    if verbose and report.assumptions:
        lines.append("")
        lines.append("  domain assumptions:")
        for a in report.assumptions:
            lines.append(f"    - {a}")
    return "\n".join(lines)


def report_json(report: PackReport) -> dict:
    """The machine-readable form of a pack report — `--json`'s payload, and
    what a second consumer serialises rather than re-deriving (the demo's rule
    studio renders it in the browser)."""
    return {
        "pack": report.name,
        "version": report.version,
        "path": report.path,
        "ontology": report.ontology,
        "error": report.error,
        "pairs": [
            {
                "attribute": p.attribute,
                "priority": p.priority,
                "rules": [p.left, p.right],
                "verdict": p.verdict,
                "reason": p.reason,
                "overrides": p.overrides,
                "witness": [{"symbol": s, "value": v} for s, v in p.witness],
                "witnessExact": p.witness_exact,
            }
            for p in report.pairs
        ],
        "coverage": [
            {
                "attribute": c.attribute,
                "verdict": "COVERED" if c.covered else c.verdict,
                "reason": c.reason,
                "witness": [{"symbol": s, "value": v} for s, v in c.witness],
                "witnessExact": c.witness_exact,
            }
            for c in report.coverage
        ],
        "reachability": [
            {"rule": r.rule_id, "reachable": r.reachable, "verdict": r.verdict,
             "reason": r.reason}
            for r in report.reachability
        ],
        "assumptions": report.assumptions,
        "notes": report.notes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _registry(path: str):
    """The ontology registry, when the deployment has one.

    Enums sharpen every answer — a closed `permissible_values` set turns a
    string symbol's domain from "these literals plus anything else" into
    exactly the permitted values — but the tool works without one, inferring
    kinds from use. A missing directory is not an error.
    """
    from duly_conformance.registry import load_repo_registry

    root = Path(path)
    if not root.is_dir():
        return None
    return load_repo_registry(root)


def _load(path: str) -> dict | None:
    """Load and validate a pack, reporting a refusal rather than tracebacking."""
    try:
        return _ir.load_pack(Path(path))
    except (_ir.PackValidationError, OSError) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance prove",
        description=(
            "Prove same-priority rules disjoint and find uncovered input regions. "
            "Validation-time only: nothing here reaches a receipt."
        ),
    )
    parser.add_argument("packs", nargs="+", help="pack.yaml paths")
    parser.add_argument(
        "--ontologies", default="ontologies",
        help="ontology registry directory (default: ontologies); enums sharpen the analysis",
    )
    parser.add_argument(
        "--all-pairs", action="store_true",
        help="also check pairs the kernel never questions, at differing priorities",
    )
    parser.add_argument("--verbose", action="store_true", help="print domain assumptions")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if z3 is None:
        print(Z3_MISSING, file=sys.stderr)
        return 2

    registry = _registry(args.ontologies)
    reports = []
    for raw in args.packs:
        pack = _load(raw)
        if pack is None:
            return 2
        reports.append(
            analyze_pack(Path(raw), pack, registry, all_pairs=args.all_pairs)
        )

    if args.json:
        print(json.dumps({"packs": [report_json(r) for r in reports]},
                         indent=2, sort_keys=True))
    else:
        for i, report in enumerate(reports):
            if i:
                print()
            print(render(report, verbose=args.verbose))
        print()
        print(_summary(reports))
    return 1 if any(r.fatal for r in reports) else 0


def _summary(reports: list[PackReport]) -> str:
    proved = sum(1 for r in reports for p in r.pairs if p.verdict == PROVED_DISJOINT)
    unproved = [p for r in reports for p in r.pairs if p.verdict == NOT_PROVED]
    oof = sum(1 for r in reports for p in r.pairs if p.verdict == OUT_OF_FRAGMENT)
    uncovered = sum(
        1 for r in reports for c in r.coverage if not c.covered and c.verdict == NOT_PROVED
    )
    fatal = [p for p in unproved if p.fatal]
    by_override = [p for p in unproved if p.overrides is not None]
    by_priority = [p for p in unproved if p.overrides is None and p.priority < 0]
    resolution = ", ".join(
        part
        for part in (
            f"{len(by_override)} resolved by an authored `overrides`" if by_override else "",
            f"{len(by_priority)} resolved by differing priority" if by_priority else "",
            f"{len(fatal)} UNRESOLVED" if fatal else "",
        )
        if part
    )
    out = [
        f"{len(reports)} pack(s): {proved} pair(s) PROVED-DISJOINT, "
        f"{len(unproved)} NOT-PROVED"
        + (f" ({resolution})" if resolution else "")
        + f", {oof} OUT-OF-FRAGMENT; {uncovered} uncovered decision attribute(s)."
    ]
    if fatal:
        out.append("unresolved ambiguity:")
        out.extend(f"  {p.left} / {p.right} on {p.attribute}" for p in fatal)
    return "\n".join(out)


def main_equivalent(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m duly_assurance prove-equivalent",
        description=(
            "Prove two packs conclude the same value for an attribute over the "
            "whole input space, not over a fixture list."
        ),
    )
    parser.add_argument("pack_a")
    parser.add_argument("pack_b")
    parser.add_argument(
        "--attribute", action="append", default=None,
        help="attribute CURIE to compare (repeatable; default: every attribute both packs conclude)",
    )
    parser.add_argument("--ontologies", default="ontologies")
    parser.add_argument("--verbose", action="store_true", help="print domain assumptions")
    args = parser.parse_args(argv)

    if z3 is None:
        print(Z3_MISSING, file=sys.stderr)
        return 2

    registry = _registry(args.ontologies)
    pack_a, pack_b = _load(args.pack_a), _load(args.pack_b)
    if pack_a is None or pack_b is None:
        return 2
    report = equivalence_report(pack_a, pack_b, registry, args.attribute)
    print(render_equivalence(report, args.pack_a, args.pack_b, verbose=args.verbose))
    return report.exit_code


def render_equivalence(
    report: EquivalenceReport, path_a: str, path_b: str, *, verbose: bool = False
) -> str:
    lines = [f"{report.name_a}  ({path_a})", f"{report.name_b}  ({path_b})"]
    if report.error:
        lines.append("")
        lines.append(f"  {OUT_OF_FRAGMENT}: {report.error}")
        return "\n".join(lines)

    if report.only_a or report.only_b:
        lines.append("")
        lines.append("  rules present in only one pack (not compared):")
        for rid in report.only_a:
            lines.append(f"    {report.name_a}: {rid}")
        for rid in report.only_b:
            lines.append(f"    {report.name_b}: {rid}")

    lines.append("")
    lines.append("  decision equivalence — do the packs conclude the same value?")
    for result in report.decisions:
        lines.append("")
        if result.verdict == PROVED_DISJOINT:
            lines.append(f"    PROVED-EQUIVALENT  {result.attribute}")
            lines.append(f"      {result.reason}")
        elif result.verdict == OUT_OF_FRAGMENT:
            lines.append(f"    {OUT_OF_FRAGMENT}    {result.attribute}")
            lines.append(f"      {result.reason}")
        else:
            lines.append(f"    NOT-PROVED         {result.attribute}")
            lines.append(f"      {result.reason}")
            lines.append(f"      {report.name_a}: {result.left_value}")
            lines.append(f"      {report.name_b}: {result.right_value}")
            lines.extend(_witness_lines(result.witness, result.witness_exact, "      "))
    if not report.decisions:
        lines.append("    (the two packs conclude no attribute in common)")

    trace = report.trace
    if trace is not None:
        lines.append("")
        lines.append(
            "  trace equivalence — same rules applied, same winner, same defeat chain?"
        )
        lines.append("")
        if trace.verdict == PROVED_DISJOINT:
            lines.append(f"    PROVED-EQUIVALENT  {trace.shared_rules} shared rule id(s)")
            lines.append(f"      {trace.reason}")
        elif trace.verdict == OUT_OF_FRAGMENT:
            lines.append(f"    {OUT_OF_FRAGMENT}    {trace.reason}")
        else:
            lines.append(f"    NOT-PROVED         {trace.shared_rules} shared rule id(s)")
            lines.append(f"      {trace.reason}")
            for diff in trace.differences:
                lines.append(f"      differs: {diff}")
            lines.extend(_witness_lines(trace.witness, trace.witness_exact, "      "))

    if verbose and report.assumptions:
        lines.append("")
        lines.append("  domain assumptions:")
        for a in report.assumptions:
            lines.append(f"    - {a}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
