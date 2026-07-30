"""Z3 encoding of the rule IR — the fragment `prove` reasons inside.

This module turns a rule pack into SMT: one boolean term per rule saying
"this rule fires", plus a symbolic evaluator that defines each derived
attribute from the rules that conclude it, exactly the way
`kernel/duly_kernel/engine.py` does. Nothing here evaluates a case, emits a
receipt, or influences adjudication: the encoding is validation-time only.

Read `spec/pack-verification.md` for the fragment, the per-operator
encoding table, and the assumptions the encoding makes explicit. The
short version:

- **Booleans** are Z3 `Bool`.
- **decimal / money** are Z3 `Real`. Currency is not modeled.
- **date** is a Z3 `Int` (proleptic Gregorian ordinal), bounded to
  [1900-01-01, 2200-01-01).
- **string / code** are Z3 `Int` indices into a per-symbol finite domain,
  built from the ontology enum when there is one and from the literals the
  pack compares against otherwise, plus an "any other value" sentinel when
  the code set is open. Only symbol-vs-literal equality is encoded.
- Anything outside that raises `OutOfFragment`, naming the construct. The
  encoding never guesses: an honest refusal is the point.

Soundness direction: every approximation here *widens* the input space
(free variables for things the encoding cannot pin down), so UNSAT — the
"proved" answer — stays a proof, while SAT is a *candidate* witness that
may or may not be reachable. `PackEncoding.approximations` records every
widening so a witness can be labeled honestly.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from duly_kernel import expr as _expr
from duly_kernel import ir as _ir

try:  # pragma: no cover - exercised by the import guard in prove.py
    import z3
except ImportError:  # pragma: no cover
    z3 = None  # type: ignore[assignment]


__all__ = [
    "OutOfFragment",
    "Symbol",
    "Universe",
    "PackEncoding",
    "DATE_MIN",
    "DATE_MAX",
    "OTHER",
]


class OutOfFragment(Exception):
    """A construct falls outside the encoded fragment.

    Carries the reason verbatim into the report: an OUT-OF-FRAGMENT verdict
    must name what could not be encoded, never merely that something could
    not be.
    """


# Date bounds. Dates are bounded integers so a witness is always a real
# calendar date and so lexicographic normalization terminates.
DATE_MIN = _dt.date(1900, 1, 1)
DATE_MAX = _dt.date(2200, 1, 1)

# Rendered for the sentinel index of an open code set.
OTHER = "«any other value»"

# Enumerating a calendar wider than this is refused rather than attempted.
CALENDAR_DAY_CAP = 4000

_ORDERED_KINDS = {"decimal", "money", "date"}
_ENCODED_KINDS = {"boolean", "decimal", "money", "date", "string", "code"}


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """One input or derived quantity in the encoding.

    `key` is stable and sortable, which is what makes report ordering and
    witness normalization deterministic.
    """

    key: str
    label: str
    kind: str
    origin: str  # "attribute" | "derived" | "asOf"
    curie: str | None = None
    pack: str | None = None  # set for derived symbols (pack-local namespace)
    domain: tuple[str, ...] = ()  # string/code: ordered literal domain
    open_domain: bool = False  # string/code: an "any other value" slot exists
    enum_closed: bool = False  # domain came from a closed ontology enum

    @property
    def values(self) -> tuple[str, ...]:
        return self.domain + ((OTHER,) if self.open_domain else ())


@dataclass
class Term:
    """A typed intermediate in the expression encoding.

    A string literal has no Z3 representation of its own — it only means
    something against a symbol's domain — so it travels as `literal` until
    an equality consumes it.
    """

    kind: str
    z: object = None
    symbol: str | None = None
    literal: str | None = None


# ---------------------------------------------------------------------------
# Value-kind resolution
# ---------------------------------------------------------------------------


def _slot(registry, pack: dict, curie: str):
    """The ontology slot for `curie` under the pack's pinned ontology."""
    if registry is None:
        return None
    meta = pack.get("pack") or {}
    name, version = meta.get("ontology"), meta.get("ontologyVersion")
    if not name or not version:
        return None
    ontology = registry.get(name, version)
    if ontology is None:
        return None
    found = ontology.find_slot(curie)
    return found[1] if found else None


def _walk(node) -> list:
    """Every node in `node`, parents before children."""
    out = [node]
    if isinstance(node, _expr.Unary):
        out += _walk(node.operand)
    elif isinstance(node, _expr.Binary):
        out += _walk(node.left) + _walk(node.right)
    elif isinstance(node, _expr.Call):
        for a in node.args:
            out += _walk(a)
    return out


def _rule_exprs(rule: dict) -> list[tuple[str, object]]:
    """(source, AST) for every expression in a rule: guards then value."""
    out = []
    for cond in rule.get("when") or []:
        out.append((cond, _expr.parse(cond)))
    value = rule["then"].get("value") or {}
    if isinstance(value, dict) and "expr" in value:
        out.append((value["expr"], _expr.parse(value["expr"])))
    return out


# ---------------------------------------------------------------------------
# The shared input universe
# ---------------------------------------------------------------------------


class Universe:
    """The input space two encodings can share.

    Attribute symbols and the evaluation point are *inputs* — they belong to
    the case, not to a pack — so equivalence between two packs is a question
    about the same universe. Derived symbols are pack-local and live on the
    `PackEncoding`.

    Usage is two-phase: `observe()` every pack, then `finalize()`, then build
    encodings. The two phases exist because a string symbol's domain is the
    union of the literals *every* pack compares it against.
    """

    def __init__(self, registry=None):
        self.registry = registry
        self.symbols: dict[str, Symbol] = {}
        self._kind_hints: dict[str, set[str]] = {}
        self._literals: dict[str, set[str]] = {}
        self._entity_types: set[str] = set()
        self._final = False
        self.notes: list[str] = []

    # -- phase 1 ------------------------------------------------------------

    def observe(self, pack: dict) -> None:
        """Record the attribute symbols, kinds and literals `pack` uses."""
        if self._final:  # pragma: no cover - programming error
            raise RuntimeError("Universe already finalized")
        for rule in pack["rules"]:
            var_keys: dict[str, str] = {}
            for name, binding in rule["given"].items():
                (bkind, ref), = binding.items()
                if bkind == "entityType":
                    self._entity_types.add(ref)
                    continue
                if bkind == "attribute":
                    key = f"attr:{ref}"
                    self._ensure_attribute(pack, key, ref)
                elif bkind == "asOf":
                    key = "asOf:effective"
                    self._ensure_asof()
                else:  # derived — pack-local, resolved by PackEncoding
                    continue
                var_keys[name] = key
            for _src, node in _rule_exprs(rule):
                self._scan(node, var_keys)

    def _ensure_attribute(self, pack: dict, key: str, curie: str) -> None:
        if key in self.symbols:
            return
        slot = _slot(self.registry, pack, curie)
        kind = slot.kind if slot is not None else None
        sym = Symbol(key=key, label=curie, kind=kind or "?", origin="attribute", curie=curie)
        if slot is not None and slot.enum is not None:
            sym.domain = tuple(sorted(slot.enum.values))
            sym.open_domain = bool(slot.enum.open_code_set)
            sym.enum_closed = not slot.enum.open_code_set
        elif kind in ("string", "code") or kind is None:
            sym.open_domain = True
        self.symbols[key] = sym

    def _ensure_asof(self) -> None:
        if "asOf:effective" not in self.symbols:
            self.symbols["asOf:effective"] = Symbol(
                key="asOf:effective",
                label="asOf.effective",
                kind="date",
                origin="asOf",
            )

    def _scan(self, node, var_keys: dict[str, str]) -> None:
        """Collect string literals per symbol and kind hints for symbols the
        ontology did not type."""
        for n in _walk(node):
            if not isinstance(n, _expr.Binary):
                continue
            if n.op in ("==", "!="):
                for a, b in ((n.left, n.right), (n.right, n.left)):
                    if isinstance(a, _expr.Var) and isinstance(b, _expr.Lit):
                        key = var_keys.get(a.name)
                        if key is None:
                            continue
                        if isinstance(b.value, _expr.StringV):
                            self._literals.setdefault(key, set()).add(b.value.value)
                            self._hint(key, "string")
                        elif isinstance(b.value, _expr.BoolV):
                            self._hint(key, "boolean")
                        elif isinstance(b.value, _expr.DecimalV):
                            self._hint(key, "decimal")
            if n.op in ("<", "<=", ">", ">="):
                for a, b in ((n.left, n.right), (n.right, n.left)):
                    if isinstance(a, _expr.Var) and isinstance(b, _expr.Lit):
                        key = var_keys.get(a.name)
                        if key is not None and isinstance(b.value, _expr.DecimalV):
                            self._hint(key, "decimal")
            if n.op in ("and", "or"):
                for side in (n.left, n.right):
                    if isinstance(side, _expr.Var):
                        key = var_keys.get(side.name)
                        if key is not None:
                            self._hint(key, "boolean")
        for n in _walk(node):
            if isinstance(n, _expr.Unary) and n.op == "not" and isinstance(n.operand, _expr.Var):
                key = var_keys.get(n.operand.name)
                if key is not None:
                    self._hint(key, "boolean")
            if isinstance(n, _expr.Call) and n.func == "days_between":
                for a in n.args:
                    if isinstance(a, _expr.Var):
                        key = var_keys.get(a.name)
                        if key is not None:
                            self._hint(key, "date")

    def _hint(self, key: str, kind: str) -> None:
        self._kind_hints.setdefault(key, set()).add(kind)

    # -- phase 2 ------------------------------------------------------------

    def finalize(self) -> None:
        """Settle every symbol's kind and finite domain."""
        if self._final:
            return
        # Every rule carries an effective window, so the evaluation point is
        # always an input — declared here rather than lazily so two encodings
        # sharing a universe provably share the same variable.
        self._ensure_asof()
        for key, sym in self.symbols.items():
            if sym.kind == "?":
                hints = self._kind_hints.get(key, set())
                if len(hints) == 1:
                    sym.kind = next(iter(hints))
                    self.notes.append(
                        f"{sym.label}: no ontology slot; kind {sym.kind!r} inferred from use"
                    )
                elif hints:
                    raise OutOfFragment(
                        f"attribute {sym.label} has no ontology slot and is used "
                        f"inconsistently ({', '.join(sorted(hints))}) — kind cannot be settled"
                    )
                else:
                    raise OutOfFragment(
                        f"attribute {sym.label} has no ontology slot and no usage "
                        f"from which to infer a value kind"
                    )
            if sym.kind not in _ENCODED_KINDS:
                raise OutOfFragment(
                    f"{sym.label}: value kind {sym.kind!r} is outside the encoded "
                    f"fragment (encoded: {', '.join(sorted(_ENCODED_KINDS))})"
                )
            if sym.kind in ("string", "code"):
                observed = self._literals.get(key, set())
                extra = sorted(observed - set(sym.domain))
                if extra and sym.enum_closed:
                    self.notes.append(
                        f"{sym.label}: guard literal(s) {', '.join(repr(e) for e in extra)} "
                        f"are outside the ontology enum; kept in the domain "
                        f"(widening, never narrowing)"
                    )
                sym.domain = tuple(sorted(set(sym.domain) | observed))
        self._final = True

    @property
    def entity_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._entity_types))


# ---------------------------------------------------------------------------
# The encoding
# ---------------------------------------------------------------------------


@dataclass
class RuleEncoding:
    rule_id: str
    fires: object = None
    alive: object = None
    wins: object = None
    window: object = None
    out_of_fragment: str | None = None
    symbols: tuple[str, ...] = ()


class PackEncoding:
    """One pack, encoded against a shared `Universe`.

    Builds, per rule: `fires` (bindings resolve, effective window contains
    asOf, every `when` holds), `alive` (fires and no firing rule overrides
    it) and `wins` (alive and no alive higher-priority rule concludes the
    same attribute) — the kernel's own defeat order, symbolically. Derived
    attributes are then *defined* from their producers, stratum by stratum,
    so a guard on a derived value is reasoned about rather than approximated.
    """

    def __init__(self, pack: dict, universe: Universe, *, tag: str | None = None):
        if z3 is None:  # pragma: no cover
            raise RuntimeError("z3-solver is not installed")
        if not universe._final:  # pragma: no cover - programming error
            raise RuntimeError("Universe.finalize() must run before encoding")
        self.pack = pack
        self.name = pack["pack"]["name"]
        self.tag = tag or self.name
        self.universe = universe
        self.rules = list(pack["rules"])
        self.by_id = {r["id"]: r for r in self.rules}
        self.pack_order = {r["id"]: i for i, r in enumerate(self.rules)}
        self.strata = _ir.rule_strata(self.rules)
        self.calendars = _expr.parse_calendars(pack.get("calendars"))

        self.symbols: dict[str, Symbol] = dict(universe.symbols)
        self.vars: dict[str, object] = {}
        self.exists: dict[str, object] = {}
        self.assumptions: list[tuple[str, object]] = []
        self.approximations: list[str] = []
        self.notes: list[str] = []
        self.encodings: dict[str, RuleEncoding] = {}
        self._defined: dict[str, object] = {}  # concluded curie key -> Bool term
        # Attributes whose *applicability* or *value* could not be encoded
        # exactly. Both are widenings (a free variable stands in), so proofs
        # stay sound; a report that leans on either says so.
        self.applicability_gaps: dict[str, str] = {}
        self.value_gaps: dict[str, str] = {}
        self._counter = 0

        self._check_override_strata()
        self._declare_derived_symbols()
        self._declare_vars()
        self._encode_rules()

    # -- setup --------------------------------------------------------------

    def _fresh(self, prefix: str, sort: str):
        self._counter += 1
        name = f"{self.tag}!{prefix}!{self._counter}"
        if sort == "Int":
            return z3.Int(name)
        if sort == "Real":
            return z3.Real(name)
        return z3.Bool(name)

    def _dkey(self, curie: str) -> str:
        return f"derived:{self.tag}:{curie}"

    def _check_override_strata(self) -> None:
        """Refuse the one shape where the kernel's two defeat paths diverge.

        `_apply_defeat` suppresses an overridden rule globally; the derived
        binding resolver `_select_producer` sees only the firings settled so
        far. They agree unless a rule overrides a producer of an attribute
        that is consumed as a `derived` binding while sitting in a strictly
        higher stratum. No committed pack does this; if one ever does, the
        encoding says so instead of silently picking a reading.
        """
        consumed = set()
        for rule in self.rules:
            consumed.update(_ir.derived_attributes(rule))
        for rule in self.rules:
            for target in rule.get("overrides") or []:
                other = self.by_id.get(target)
                if other is None:
                    continue
                if (
                    other["then"]["attribute"] in consumed
                    and self.strata[rule["id"]] > self.strata[target]
                ):
                    raise OutOfFragment(
                        f"rule {rule['id']!r} overrides {target!r} from a higher "
                        f"stratum, and {other['then']['attribute']!r} is consumed as a "
                        f"derived binding — the kernel's `_apply_defeat` and "
                        f"`_select_producer` can disagree on this shape, so the "
                        f"encoding declines to pick one"
                    )

    def _declare_derived_symbols(self) -> None:
        """Give every *concluded* attribute a symbol, typed from its producers.

        Every concluded attribute gets one, not only those a `derived` binding
        consumes: the equivalence query asks for a decision attribute's value,
        and building that symbol lazily would make the encoding depend on the
        order the caller asks its questions in.
        """
        produced: dict[str, list[dict]] = {}
        for rule in self.rules:
            produced.setdefault(rule["then"]["attribute"], []).append(rule)

        # A `derived` binding whose attribute no rule concludes: the kernel's
        # producer lookup returns None, so every consumer is inapplicable.
        for rule in self.rules:
            for curie in _ir.derived_attributes(rule):
                if curie in produced or self._dkey(curie) in self._defined:
                    continue
                self._defined[self._dkey(curie)] = z3.BoolVal(False)
                self.notes.append(
                    f"{curie}: bound as `derived` but no rule concludes it — "
                    f"every consumer is unconditionally inapplicable"
                )

        guard_literals = self._derived_guard_literals()
        for curie in sorted(produced):
            key = self._dkey(curie)
            producers = produced[curie]
            kinds = {p["then"]["value"].get("kind") for p in producers}
            if len(kinds) != 1:
                self.value_gaps[curie] = (
                    f"concluded with more than one value kind "
                    f"({', '.join(sorted(str(k) for k in kinds))})"
                )
                continue
            kind = next(iter(kinds))
            if kind not in _ENCODED_KINDS:
                self.value_gaps[curie] = (
                    f"value kind {kind!r} is outside the encoded fragment"
                )
                continue
            sym = Symbol(
                key=key, label=f"{curie} (concluded)", kind=kind,
                origin="derived", curie=curie, pack=self.tag,
            )
            if kind in ("string", "code"):
                concluded = {
                    str(p["then"]["value"]["value"])
                    for p in producers
                    if "value" in p["then"]["value"]
                }
                slot = _slot(self.universe.registry, self.pack, curie)
                enum_values: set[str] = set()
                if slot is not None and slot.enum is not None:
                    enum_values = set(slot.enum.values)
                    sym.open_domain = bool(slot.enum.open_code_set)
                    sym.enum_closed = not slot.enum.open_code_set
                else:
                    sym.open_domain = True
                sym.domain = tuple(
                    sorted(enum_values | concluded | guard_literals.get(curie, set()))
                )
            self.symbols[key] = sym

    def _derived_guard_literals(self) -> dict[str, set[str]]:
        """String literals the pack compares `derived` bindings against.

        These must be in the symbol's domain or the encoding would narrow the
        input space — `category == "Unlisted"` would be read as unsatisfiable
        rather than as a value the domain simply had not enumerated.
        """
        out: dict[str, set[str]] = {}
        for rule in self.rules:
            names = {
                name: ref
                for name, binding in rule["given"].items()
                for kind, ref in [next(iter(binding.items()))]
                if kind == "derived"
            }
            if not names:
                continue
            for _src, node in _rule_exprs(rule):
                for n in _walk(node):
                    if not (isinstance(n, _expr.Binary) and n.op in ("==", "!=")):
                        continue
                    for a, b in ((n.left, n.right), (n.right, n.left)):
                        if (
                            isinstance(a, _expr.Var)
                            and a.name in names
                            and isinstance(b, _expr.Lit)
                            and isinstance(b.value, _expr.StringV)
                        ):
                            out.setdefault(names[a.name], set()).add(b.value.value)
        return out

    def _declare_vars(self) -> None:
        for key in sorted(self.symbols):
            sym = self.symbols[key]
            if sym.kind == "boolean":
                self.vars[key] = z3.Bool(f"v!{key}")
            elif sym.kind in ("decimal", "money"):
                self.vars[key] = z3.Real(f"v!{key}")
            elif sym.kind == "date":
                v = z3.Int(f"v!{key}")
                self.vars[key] = v
                self.assumptions.append(
                    (
                        f"{sym.label} is a calendar date in "
                        f"[{DATE_MIN.isoformat()}, {DATE_MAX.isoformat()})",
                        z3.And(v >= DATE_MIN.toordinal(), v < DATE_MAX.toordinal()),
                    )
                )
            else:  # string | code
                v = z3.Int(f"v!{key}")
                self.vars[key] = v
                n = len(sym.values)
                if n == 0:
                    raise OutOfFragment(
                        f"{sym.label}: no value domain could be built (closed enum "
                        f"with no permissible values and no guard literals)"
                    )
                self.assumptions.append(
                    (
                        f"{sym.label} takes one of: " + ", ".join(sym.values),
                        z3.And(v >= 0, v < n),
                    )
                )
            if sym.origin == "attribute":
                self.exists[key] = z3.Bool(f"e!{key}")
            elif sym.origin == "asOf":
                self.exists[key] = z3.BoolVal(True)

        for etype in self.universe.entity_types:
            key = f"entity:{etype}"
            self.exists[key] = z3.BoolVal(True)
        if self.universe.entity_types:
            self.assumptions.append(
                (
                    "the case carries exactly one entity of each entityType a rule "
                    "binds (" + ", ".join(self.universe.entity_types) + ")",
                    z3.BoolVal(True),
                )
            )

    # -- rule encoding ------------------------------------------------------

    def _encode_rules(self) -> None:
        for rule in self.rules:
            self.encodings[rule["id"]] = RuleEncoding(rule_id=rule["id"])

        levels = sorted(set(self.strata.values()))
        attr_stratum: dict[str, int] = {}
        for rule in self.rules:
            a = rule["then"]["attribute"]
            attr_stratum[a] = max(attr_stratum.get(a, 0), self.strata[rule["id"]])

        for level in levels:
            for rule in self.rules:
                if self.strata[rule["id"]] != level:
                    continue
                self._encode_fires(rule)
            for curie in sorted(a for a, s in attr_stratum.items() if s == level):
                self._define_derived(curie)

        self._encode_defeat()

    def _encode_fires(self, rule: dict) -> None:
        enc = self.encodings[rule["id"]]
        enc.window = self._window(rule)
        try:
            conds = [self._binding_resolved(rule, name, binding)
                     for name, binding in rule["given"].items()]
            conds.append(enc.window)
            env = self._env(rule)
            for src, node in [(c, _expr.parse(c)) for c in rule.get("when") or []]:
                term = self._encode(node, env)
                if term.kind != "boolean":
                    raise OutOfFragment(
                        f"when expression {src!r} is not boolean under rule-IR typing"
                    )
                conds.append(term.z)
            enc.fires = z3.And(*conds) if conds else z3.BoolVal(True)
            enc.symbols = tuple(sorted(self._env_keys(rule)))
        except OutOfFragment as exc:
            enc.out_of_fragment = str(exc)
            enc.fires = None

    def _binding_resolved(self, rule: dict, name: str, binding: dict):
        (bkind, ref), = binding.items()
        if bkind == "entityType":
            return self.exists[f"entity:{ref}"]
        if bkind == "attribute":
            return self.exists[f"attr:{ref}"]
        if bkind == "asOf":
            return z3.BoolVal(True)
        key = self._dkey(ref)
        return self._defined.get(key, z3.BoolVal(False))

    def _window(self, rule: dict):
        asof = self.vars["asOf:effective"]
        parts = []
        frm = _as_date(rule.get("effectiveFrom"))
        to = _as_date(rule.get("effectiveTo"))
        if frm is not None:
            parts.append(asof >= frm.toordinal())
        if to is not None:
            parts.append(asof < to.toordinal())
        return z3.And(*parts) if parts else z3.BoolVal(True)

    def _env(self, rule: dict) -> dict[str, str]:
        """Variable name -> symbol key, for this rule."""
        env: dict[str, str] = {}
        for name, binding in rule["given"].items():
            (bkind, ref), = binding.items()
            if bkind == "attribute":
                env[name] = f"attr:{ref}"
            elif bkind == "derived":
                env[name] = self._dkey(ref)
            elif bkind == "asOf":
                env[name] = "asOf:effective"
        return env

    def _env_keys(self, rule: dict) -> set[str]:
        return set(self._env(rule).values())

    # -- derived definitions -------------------------------------------------

    def _define_derived(self, curie: str) -> None:
        """Define `curie`'s applicability and value from its producing rules.

        Both halves degrade independently. If a producer's guard is outside
        the fragment, applicability becomes a free boolean; if a producer's
        `then.value` is, the value becomes a free variable. Each is a
        widening, recorded in `applicability_gaps` / `value_gaps` so a
        witness that depends on it can be labeled.
        """
        key = self._dkey(curie)
        if key in self._defined:
            return
        producers = self.rules_for(curie)
        usable = [r for r in producers if self.encodings[r["id"]].fires is not None]
        if len(usable) != len(producers):
            missing = [r["id"] for r in producers if self.encodings[r["id"]].fires is None]
            self.applicability_gaps[curie] = (
                f"rule(s) {', '.join(missing)} are outside the fragment"
            )
            self.value_gaps.setdefault(curie, self.applicability_gaps[curie])
            self._defined[key] = self._fresh("undef", "Bool")
            if key in self.symbols:
                self.exists[key] = self._defined[key]
            return

        alive = {r["id"]: self._alive_term(r) for r in usable}
        self._defined[key] = z3.Or(*[alive[r["id"]] for r in usable])
        if key in self.symbols:
            # Definedness is this symbol's "exists": a witness must never print
            # a value for an attribute the pack reached no conclusion on.
            self.exists[key] = self._defined[key]
        if curie in self.value_gaps or key not in self.vars:
            return

        ordered = sorted(usable, key=lambda r: (-r["priority"], self.pack_order[r["id"]]))
        try:
            values = [
                (self._wins_term(r, ordered, alive), self._then_value(r)) for r in ordered
            ]
        except OutOfFragment as exc:
            self.value_gaps[curie] = str(exc)
            return
        expr = values[-1][1]
        for cond, val in reversed(values[:-1]):
            expr = z3.If(cond, val, expr)
        self.assumptions.append(
            (
                f"{curie} takes the value the pack's own rules conclude for it",
                z3.Implies(self._defined[key], self.vars[key] == expr),
            )
        )

    def _alive_term(self, rule: dict):
        enc = self.encodings[rule["id"]]
        overriders = [
            self.encodings[r["id"]].fires
            for r in self.rules
            if rule["id"] in (r.get("overrides") or [])
            and self.encodings[r["id"]].fires is not None
        ]
        if not overriders:
            return enc.fires
        return z3.And(enc.fires, z3.Not(z3.Or(*overriders)))

    def _wins_term(self, rule: dict, ordered: list[dict], alive: dict):
        """Alive, and nothing ahead of it in the kernel's winner order is."""
        idx = ordered.index(rule)
        ahead = [alive[r["id"]] for r in ordered[:idx]]
        if not ahead:
            return alive[rule["id"]]
        return z3.And(alive[rule["id"]], z3.Not(z3.Or(*ahead)))

    def _then_value(self, rule: dict):
        spec = rule["then"]["value"]
        curie = rule["then"]["attribute"]
        sym = self.symbols[self._dkey(curie)]
        if "expr" in spec:
            term = self._encode(_expr.parse(spec["expr"]), self._env(rule))
            if term.literal is not None:
                return self._index_of(sym, term.literal)
            return term.z
        if sym.kind == "boolean":
            return z3.BoolVal(bool(spec["value"]))
        if sym.kind == "money":
            return z3.RealVal(str(spec["amount"]))
        if sym.kind == "decimal":
            return z3.RealVal(str(spec["value"]))
        if sym.kind == "date":
            return z3.IntVal(_dt.date.fromisoformat(str(spec["value"])).toordinal())
        return self._index_of(sym, str(spec["value"]))

    def _index_of(self, sym: Symbol, literal: str):
        values = sym.values
        if literal in values:
            return z3.IntVal(values.index(literal))
        if sym.open_domain:
            return z3.IntVal(values.index(OTHER))
        raise OutOfFragment(
            f"{sym.label}: literal {literal!r} is outside the closed value domain "
            f"({', '.join(values)})"
        )

    def _encode_defeat(self) -> None:
        by_attr: dict[str, list[dict]] = {}
        for rule in self.rules:
            by_attr.setdefault(rule["then"]["attribute"], []).append(rule)
        for curie, group in by_attr.items():
            usable = [r for r in group if self.encodings[r["id"]].fires is not None]
            if not usable:
                continue
            alive = {r["id"]: self._alive_term(r) for r in usable}
            ordered = sorted(usable, key=lambda r: (-r["priority"], self.pack_order[r["id"]]))
            for r in usable:
                enc = self.encodings[r["id"]]
                enc.alive = alive[r["id"]]
                enc.wins = self._wins_term(r, ordered, alive)

    # -- expression encoding -------------------------------------------------

    def _encode(self, node, env: dict[str, str]) -> Term:
        if isinstance(node, _expr.Lit):
            return self._encode_lit(node.value)
        if isinstance(node, _expr.Var):
            key = env.get(node.name)
            if key is None:
                raise OutOfFragment(f"variable {node.name!r} is not a bound input")
            sym = self.symbols[key]
            return Term(kind=sym.kind, z=self.vars[key], symbol=key)
        if isinstance(node, _expr.Unary):
            return self._encode_unary(node, env)
        if isinstance(node, _expr.Binary):
            return self._encode_binary(node, env)
        if isinstance(node, _expr.Call):
            return self._encode_call(node, env)
        raise OutOfFragment(f"unsupported expression node {type(node).__name__}")

    def _encode_lit(self, value) -> Term:
        if isinstance(value, _expr.BoolV):
            return Term(kind="boolean", z=z3.BoolVal(value.value))
        if isinstance(value, _expr.DecimalV):
            return Term(kind="decimal", z=z3.RealVal(str(value.value)))
        if isinstance(value, _expr.StringV):
            return Term(kind="string", literal=value.value)
        raise OutOfFragment(f"literal of kind {type(value).__name__} is not encoded")

    def _encode_unary(self, node, env) -> Term:
        term = self._encode(node.operand, env)
        if node.op == "not":
            if term.kind != "boolean":
                raise OutOfFragment("'not' applied to a non-boolean")
            return Term(kind="boolean", z=z3.Not(term.z))
        if node.op == "-":
            if term.kind not in ("decimal", "money"):
                raise OutOfFragment(f"unary '-' applied to {term.kind}")
            return Term(kind=term.kind, z=-term.z)
        raise OutOfFragment(f"unary operator {node.op!r} is not encoded")

    def _encode_binary(self, node, env) -> Term:
        if node.op in ("and", "or"):
            left, right = self._encode(node.left, env), self._encode(node.right, env)
            if left.kind != "boolean" or right.kind != "boolean":
                raise OutOfFragment(f"'{node.op}' applied to a non-boolean")
            joiner = z3.And if node.op == "and" else z3.Or
            return Term(kind="boolean", z=joiner(left.z, right.z))
        left, right = self._encode(node.left, env), self._encode(node.right, env)
        if node.op in ("==", "!="):
            return self._encode_equality(node.op, left, right)
        if node.op in ("<", "<=", ">", ">="):
            return self._encode_order(node.op, left, right)
        return self._encode_arith(node.op, left, right)

    def _encode_equality(self, op: str, left: Term, right: Term) -> Term:
        lit_side, var_side = None, None
        if left.literal is not None and right.literal is not None:
            eq = z3.BoolVal(left.literal == right.literal)
            return Term(kind="boolean", z=eq if op == "==" else z3.Not(eq))
        if left.literal is not None:
            lit_side, var_side = left, right
        elif right.literal is not None:
            lit_side, var_side = right, left
        if lit_side is not None:
            if var_side.symbol is None or var_side.kind not in ("string", "code"):
                raise OutOfFragment(
                    f"string literal {lit_side.literal!r} compared against a "
                    f"{var_side.kind} expression"
                )
            sym = self.symbols[var_side.symbol]
            values = sym.values
            if lit_side.literal in values:
                eq = var_side.z == values.index(lit_side.literal)
            else:
                # Every literal a guard compares against is in the domain by
                # construction, so this is a `then.value` literal outside the
                # symbol's value set: the sentinel stands for *some* other
                # value, never for this named one.
                eq = z3.BoolVal(False)
            return Term(kind="boolean", z=eq if op == "==" else z3.Not(eq))
        if left.kind in ("string", "code") or right.kind in ("string", "code"):
            raise OutOfFragment(
                "string/code equality between two symbols is not encoded — the "
                "finite-domain encoding gives each symbol its own 'any other "
                "value' slot, so symbol-to-symbol equality outside the enumerated "
                "values cannot be represented faithfully"
            )
        if left.kind != right.kind:
            raise OutOfFragment(
                f"cannot compare {left.kind} with {right.kind} (rule-IR typing)"
            )
        eq = left.z == right.z
        return Term(kind="boolean", z=eq if op == "==" else z3.Not(eq))

    def _encode_order(self, op: str, left: Term, right: Term) -> Term:
        if left.literal is not None or right.literal is not None:
            raise OutOfFragment("ordering comparison against a string literal is not encoded")
        if left.kind != right.kind:
            raise OutOfFragment(
                f"cannot order {left.kind} against {right.kind} (rule-IR typing)"
            )
        if left.kind not in _ORDERED_KINDS:
            raise OutOfFragment(
                f"ordering comparison on {left.kind} values is not encoded "
                f"(encoded: {', '.join(sorted(_ORDERED_KINDS))})"
            )
        table = {
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
        }
        return Term(kind="boolean", z=table[op](left.z, right.z))

    def _encode_arith(self, op: str, left: Term, right: Term) -> Term:
        if left.literal is not None or right.literal is not None:
            raise OutOfFragment(f"arithmetic operator {op!r} applied to a string")
        kinds = (left.kind, right.kind)
        if op in ("+", "-"):
            if kinds == ("decimal", "decimal"):
                out = "decimal"
            elif kinds == ("money", "money"):
                out = "money"
            else:
                raise OutOfFragment(f"cannot apply {op!r} to {kinds[0]} and {kinds[1]}")
            return Term(kind=out, z=(left.z + right.z) if op == "+" else (left.z - right.z))
        if op == "*":
            if kinds == ("decimal", "decimal"):
                out = "decimal"
            elif kinds in (("money", "decimal"), ("decimal", "money")):
                out = "money"
            else:
                raise OutOfFragment(f"cannot apply '*' to {kinds[0]} and {kinds[1]}")
            return Term(kind=out, z=left.z * right.z)
        if op == "/":
            if kinds not in (("decimal", "decimal"), ("money", "decimal")):
                raise OutOfFragment(f"cannot apply '/' to {kinds[0]} and {kinds[1]}")
            if not z3.is_rational_value(right.z) or right.z.as_fraction() == 0:
                raise OutOfFragment(
                    "division by a non-literal (or zero) divisor is not encoded — "
                    "the kernel raises on a zero divisor, and SMT real division "
                    "is total, so the two would disagree exactly where it matters"
                )
            return Term(kind=kinds[0], z=left.z / right.z)
        raise OutOfFragment(f"arithmetic operator {op!r} is not encoded")

    def _encode_call(self, node, env) -> Term:
        func = node.func
        if func == "date":
            (arg,) = node.args
            if not (isinstance(arg, _expr.Lit) and isinstance(arg.value, _expr.StringV)):
                raise OutOfFragment("date() takes a string literal")
            return Term(kind="date", z=z3.IntVal(
                _dt.date.fromisoformat(arg.value.value).toordinal()
            ))
        if func == "days_between":
            a, b = (self._encode(x, env) for x in node.args)
            if a.kind != "date" or b.kind != "date":
                raise OutOfFragment("days_between() takes two dates")
            return Term(kind="decimal", z=z3.ToReal(b.z - a.z))
        if func == "abs":
            (a,) = (self._encode(x, env) for x in node.args)
            if a.kind not in ("decimal", "money"):
                raise OutOfFragment(f"abs() applied to {a.kind}")
            return Term(kind=a.kind, z=z3.If(a.z >= 0, a.z, -a.z))
        if func in ("min", "max"):
            a, b = (self._encode(x, env) for x in node.args)
            if a.kind != b.kind:
                raise OutOfFragment(f"{func}() arguments differ in kind")
            if a.kind not in _ORDERED_KINDS:
                raise OutOfFragment(f"{func}() applied to unordered {a.kind} values")
            pick = (a.z <= b.z) if func == "min" else (a.z >= b.z)
            return Term(kind=a.kind, z=z3.If(pick, a.z, b.z))
        if func == "add_business_days":
            return self._encode_business_days(node, env)
        raise OutOfFragment(f"function {func!r} is not encoded")

    def _encode_business_days(self, node, env) -> Term:
        start_node, count_node, cal_node = node.args
        start = self._encode(start_node, env)
        if start.kind != "date":
            raise OutOfFragment("add_business_days() first argument must be a date")
        if not (isinstance(count_node, _expr.Lit) and isinstance(count_node.value, _expr.DecimalV)):
            raise OutOfFragment(
                "add_business_days() is encoded only for a literal business-day "
                "count — a computed count would need the calendar walk itself to "
                "be symbolic"
            )
        count = count_node.value.value
        if count != count.to_integral_value() or count < 0:
            raise OutOfFragment("add_business_days() count must be a non-negative integer")
        cal_name = cal_node.value.value  # validate_pack proved this is a literal
        calendar = self.calendars[cal_name]
        span = (calendar.coverage_to - calendar.coverage_from).days
        if span > CALENDAR_DAY_CAP:
            raise OutOfFragment(
                f"calendar {cal_name!r} covers {span} days, above the "
                f"{CALENDAR_DAY_CAP}-day enumeration cap"
            )

        # The calendar is pack data over a bounded window, so the function is a
        # finite table. Enumerate it: the solver gets exactly the walk the
        # kernel performs, not an approximation of it.
        table: list[tuple[int, int]] = []
        day = calendar.coverage_from
        while day < calendar.coverage_to:
            try:
                cur, remaining = day, int(count)
                while remaining:
                    cur += _dt.timedelta(days=1)
                    if calendar.is_business_day(cur):
                        remaining -= 1
                table.append((day.toordinal(), cur.toordinal()))
            except _expr.ExprCalendarError:
                pass  # the walk leaves coverage: the kernel raises, no decision
            day += _dt.timedelta(days=1)
        if not table:  # pragma: no cover - a calendar this narrow is refused above
            raise OutOfFragment(f"calendar {cal_name!r} admits no in-coverage walk")

        # The table is exact but repetitive: `n` business days later is a
        # small, slowly-varying offset. Grouping start dates by that offset
        # and compressing each group into contiguous intervals says the same
        # thing in a fraction of the clauses, which the solver notices.
        by_offset: dict[int, list[int]] = {}
        for day, result_day in table:
            by_offset.setdefault(result_day - day, []).append(day)
        offsets = {k: _intervals(sorted(v)) for k, v in by_offset.items()}
        clauses = sum(len(v) for v in offsets.values())

        result = self._fresh("abd", "Int")
        in_range = z3.Or(*[
            _within(start.z, lo, hi)
            for k in sorted(offsets)
            for lo, hi in offsets[k]
        ])
        self.assumptions.append(
            (
                f"add_business_days(..., {int(count)}, {cal_name!r}) is applied only to "
                f"dates whose walk stays inside the calendar's coverage "
                f"[{calendar.coverage_from.isoformat()}, "
                f"{calendar.coverage_to.isoformat()}) — outside it the kernel raises "
                f"and the run yields no decision",
                in_range,
            )
        )
        self.assumptions.append(
            (
                f"add_business_days(..., {int(count)}, {cal_name!r}) equals the pack "
                f"calendar's own walk ({len(table)} start dates, {clauses} intervals)",
                z3.And(*[
                    z3.Implies(
                        z3.Or(*[_within(start.z, lo, hi) for lo, hi in offsets[k]]),
                        result == start.z + k,
                    )
                    for k in sorted(offsets)
                ]),
            )
        )
        return Term(kind="date", z=result)

    # -- queries -------------------------------------------------------------

    def domain(self) -> list:
        """Every assumption term, for adding to a solver."""
        return [term for _label, term in self.assumptions]

    def assumption_labels(self) -> list[str]:
        return [label for label, _term in self.assumptions]

    def concluded_attributes(self) -> list[str]:
        return sorted({r["then"]["attribute"] for r in self.rules})

    def rules_for(self, attribute: str) -> list[dict]:
        return [r for r in self.rules if r["then"]["attribute"] == attribute]

    def decision_value(self, attribute: str):
        """(defined, value) terms for the pack's surviving conclusion.

        Raises OutOfFragment when either half was widened — an equivalence
        claim must not rest on a free variable.
        """
        if not self.rules_for(attribute):
            raise OutOfFragment(f"no rule in {self.name} concludes {attribute}")
        if attribute in self.applicability_gaps:
            raise OutOfFragment(
                f"{attribute}: applicability not encoded — "
                f"{self.applicability_gaps[attribute]}"
            )
        if attribute in self.value_gaps:
            raise OutOfFragment(
                f"{attribute}: value not encoded — {self.value_gaps[attribute]}"
            )
        key = self._dkey(attribute)
        return self._defined[key], self.vars[key]

    def defeats(self, winner: str, loser: str):
        """The term "`winner` defeats `loser` on this receipt".

        Mirrors `_apply_defeat` exactly: an authored `overrides` defeats a
        rule that fired, and the priority tiebreak defeats every other alive
        rule in the winner's (entity, attribute) group.
        """
        a, b = self.by_id.get(winner), self.by_id.get(loser)
        ea, eb = self.encodings.get(winner), self.encodings.get(loser)
        if a is None or b is None or ea is None or eb is None:
            return z3.BoolVal(False)
        if ea.fires is None or eb.fires is None:
            raise OutOfFragment(
                f"defeat between {winner} and {loser} is not encoded: "
                f"{(ea if ea.fires is None else eb).out_of_fragment}"
            )
        parts = []
        if loser in (a.get("overrides") or []):
            parts.append(z3.And(ea.fires, eb.fires))
        if (
            a["then"]["attribute"] == b["then"]["attribute"]
            and ea.wins is not None
            and eb.alive is not None
        ):
            parts.append(z3.And(ea.wins, eb.alive))
        if not parts:
            return z3.BoolVal(False)
        return z3.Or(*parts)

    def widened_in(self, keys) -> list[str]:
        """The widened attributes among `keys`, if any.

        A satisfying assignment that leans on a widened symbol is a
        *candidate* witness, not a counterexample: the free variable stands
        for something the encoding could not pin down, so the assignment may
        be unreachable. Callers use this to downgrade such a result to
        OUT-OF-FRAGMENT rather than claim an overlap they cannot demonstrate.
        """
        out = []
        for key in keys:
            sym = self.symbols.get(key)
            if sym is None or sym.curie is None:
                continue
            reason = self.applicability_gaps.get(sym.curie) or self.value_gaps.get(
                sym.curie
            )
            if reason:
                out.append(f"{sym.curie}: {reason}")
        return sorted(set(out))

    def closure(self, keys) -> list[str]:
        """`keys` plus every symbol reachable through derived dependencies.

        A witness that says "the derived category was ZeroTolerance" without
        saying which fact made it so is half a witness. Expanding the key set
        through each derived attribute's producers closes that gap.
        """
        seen = set(keys)
        queue = list(seen)
        while queue:
            key = queue.pop()
            sym = self.symbols.get(key)
            if sym is None or sym.origin != "derived" or sym.curie is None:
                continue
            for rule in self.rules_for(sym.curie):
                for k in self.encodings[rule["id"]].symbols:
                    if k not in seen:
                        seen.add(k)
                        queue.append(k)
        return sorted(seen)

    def in_force_term(self, attribute: str):
        """"The evaluation point sits inside some concluding rule's window"."""
        windows = [
            self.encodings[r["id"]].window
            for r in self.rules_for(attribute)
            if self.encodings[r["id"]].window is not None
        ]
        return z3.Or(*windows) if windows else z3.BoolVal(False)

    def coverage_term(self, attribute: str):
        """The term "some rule concludes `attribute`"."""
        if not self.rules_for(attribute):
            raise OutOfFragment(f"no rule in {self.name} concludes {attribute}")
        if attribute in self.applicability_gaps:
            raise OutOfFragment(
                f"{attribute}: {self.applicability_gaps[attribute]}"
            )
        return self._defined[self._dkey(attribute)]


def _intervals(days: list[int]) -> list[tuple[int, int]]:
    """A sorted list of integers as maximal contiguous [lo, hi] runs."""
    out: list[tuple[int, int]] = []
    for day in days:
        if out and day == out[-1][1] + 1:
            out[-1] = (out[-1][0], day)
        else:
            out.append((day, day))
    return out


def _within(term, lo: int, hi: int):
    return term == lo if lo == hi else z3.And(term >= lo, term <= hi)


def _as_date(v) -> _dt.date | None:
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v)
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return _expr.parse_datetime(s).date()


def numeric_literals(pack: dict) -> list[Decimal]:
    """Every decimal literal the pack mentions, for witness normalization."""
    out: set[Decimal] = set()
    for rule in pack["rules"]:
        for _src, node in _rule_exprs(rule):
            for n in _walk(node):
                if isinstance(n, _expr.Lit) and isinstance(n.value, _expr.DecimalV):
                    out.add(n.value.value)
        spec = rule["then"].get("value") or {}
        for field_name in ("value", "amount"):
            raw = spec.get(field_name)
            if isinstance(raw, (int, float, str)) and not isinstance(raw, bool):
                try:
                    out.add(Decimal(str(raw)))
                except Exception:  # noqa: BLE001 - not a number, ignore
                    pass
    return sorted(out)


def date_literals(pack: dict) -> list[_dt.date]:
    """Every date the pack mentions: rule windows, `date()` literals, calendar
    coverage bounds. The witness normalizer prefers these."""
    out: set[_dt.date] = set()
    for rule in pack["rules"]:
        for key in ("effectiveFrom", "effectiveTo"):
            d = _as_date(rule.get(key))
            if d is not None:
                out.add(d)
        for _src, node in _rule_exprs(rule):
            for n in _walk(node):
                if isinstance(n, _expr.Call) and n.func == "date" and n.args:
                    arg = n.args[0]
                    if isinstance(arg, _expr.Lit) and isinstance(arg.value, _expr.StringV):
                        try:
                            out.add(_dt.date.fromisoformat(arg.value.value))
                        except ValueError:  # pragma: no cover - validation catches it
                            pass
        spec = rule["then"].get("value") or {}
        if spec.get("kind") == "date" and isinstance(spec.get("value"), str):
            try:
                out.add(_dt.date.fromisoformat(spec["value"]))
            except ValueError:  # pragma: no cover
                pass
    for cal in _expr.parse_calendars(pack.get("calendars")).values():
        out.add(cal.coverage_from)
        out.add(cal.coverage_to - _dt.timedelta(days=1))
    return sorted(out)
