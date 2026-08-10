# Static pack verification — v0 draft

[Rule IR](rule-ir.md) makes rule packs checkable: same-attribute conclusions at one priority are a validation error unless the validator can *prove* the rules never both apply. The proof set it accepts is deliberately tiny — disjoint effective windows, or contradictory quoted-string equality guards on the same bound attribute — and everything else falls back to an authored `overrides` or a manufactured priority gap. [`assurance/duly_assurance/prove.py`](../assurance/duly_assurance/prove.py) is the larger proof system: it encodes a pack as SMT and asks Z3.

```bash
uv run --with z3-solver python -m duly_assurance prove \
    --ontologies examples/ontologies examples/rulepacks/*/pack.yaml
uv run --with z3-solver python -m duly_assurance prove-equivalent packA/pack.yaml packB/pack.yaml
```

Runnable demonstration: [`prove_demo.py`](prove_demo.py) — the eSign pack pair by pair, a toy pack whose rules genuinely overlap, the two disjointness claims the TILA pack states in prose, the recording pack's documented coverage hole found without being told about it, and the `>` versus `>=` perturbation [spec/dmn.md](dmn.md) measured its own equivalence suite as blind to.

**This is a validation-time analysis tool, and that is a hard boundary.** No solver output reaches a receipt. No subcommand changes any adjudication. `prove` is not on the adjudication path, is not a dependency of the kernel, and is not installed by default.

As with the fact contract, the DMN compiler, and the conformance gate, everything below is a design decision with its rationale and the alternative that was rejected.

---

## P1. `validate_pack` is not relaxed, and this document is not a proposal to relax it

The kernel's `_check_priority_ambiguity` stays exactly as it is. `prove` is additive: it never runs during adjudication, it never loosens what a pack must satisfy to load, and a pack that `validate_pack` refuses is still refused.

That is not timidity, it is where the proof has to live. The validator's judgment is inside the artifact that produces receipts, so relaxing it means the kernel accepts a pack on the strength of a proof performed by something else, somewhere else, at some earlier time. Every replay of every receipt from that pack then depends on a solver run nobody recorded and nothing pins. `spec/dmn.md` M6 makes the same argument from the other direction: a compiler that emits packs the kernel rejects has compiled nothing.

**What relaxing it would actually require**, if a future version wants it — this is a rule-IR change, and it is future work:

1. A *declared* proof obligation in the pack: something like `disjointness: proved` on a rule pair, or a pack-level `provenDisjoint` block naming pairs. The claim has to be in the versioned artifact, because everything that can change a decision must be versioned with the rulebase.
2. A pinned record of what discharged it — prover identity and version at minimum, ideally a proof artifact hash — for the same reason `engine.backend` sits inside the receipt hash.
3. A decision about what a replaying kernel does with a pack whose declared proofs it cannot re-verify. Trusting the declaration makes the receipt's replay guarantee conditional on an unauditable claim. Re-verifying makes the solver a kernel dependency, and `prove`'s whole posture is that it is not one.
4. Point 3 is the real question, and it is the same question as [spec/dmn.md](dmn.md) open question 1 and the M5 backend-identity question. It wants deciding alongside them, not before them.

Until then the honest arrangement is the current one: the kernel's proof set stays small enough to audit by reading, and `prove` is the thing an author runs to find out whether the `overrides` they are about to write is an authored legal exception or a workaround for a proof the validator cannot perform.

**Rejected:** *making `prove` a CI gate that fails on NOT-PROVED.* It already exits non-zero for the case that matters (below), but a same-priority pair with an authored `overrides` is a *correct* pack — `PKG-NOTE-31 overrides PKG-NOTE-30` in the eSign pack is exactly the default-and-exception pattern the IR is built around, and its rules genuinely overlap. Failing on it would train authors to delete the tool.

## P2. Three verdicts, and the third is a real answer

| Verdict | Means |
|---|---|
| `PROVED-DISJOINT` | The solver showed the two rules' applicability conditions cannot both hold. |
| `NOT-PROVED` | Here is a concrete assignment under which both fire. |
| `OUT-OF-FRAGMENT` | A named construct could not be encoded. No claim either way. |

`OUT-OF-FRAGMENT` always names what stopped it — `add_business_days() is encoded only for a literal business-day count`, `ordering comparison on string values is not encoded`, `value kind 'datetime' is outside the encoded fragment`. It is never a bare refusal, because a bare refusal is indistinguishable from a bug.

The rule the encoding obeys everywhere: **an approximation may only widen the input space, never narrow it.** Widening keeps UNSAT a proof (nothing satisfies the wider constraint, so nothing satisfies the narrower one either) at the cost of possibly-spurious SAT. So `PROVED-DISJOINT` is always sound, and a `NOT-PROVED` witness resting on a widened symbol is downgraded to `OUT-OF-FRAGMENT` rather than reported as an overlap: the assignment might not be reachable, and reporting it as one would be a guess.

**Rejected:** *a fourth verdict for "the solver returned unknown".* It is reported as `OUT-OF-FRAGMENT` with `solver returned unknown` as the reason, because from the reader's position the two are the same fact — the tool could not answer — and a taxonomy that distinguishes them invites the reading that one of them is closer to a proof.

## P3. Exit codes, and why non-zero would mean a kernel bug

`prove` exits non-zero for exactly one thing: a `NOT-PROVED` pair at the *same priority* with no `overrides` between its rules.

Every other finding — an `OUT-OF-FRAGMENT` verdict, an uncovered decision region, an overlap at differing priorities, an overlap resolved by an authored exception — exits zero. Those are information. A differing-priority overlap in particular is *normal*: priority is the mechanical tiebreak, and defaults overlap their exceptions by construction.

Here is the part worth stating plainly. **The failing case cannot arise from a pack that loads.** `validate_pack` already refuses any same-priority pair concluding one attribute unless it can prove disjointness syntactically or the author wrote an `overrides` — so the only same-priority pairs `prove` ever sees are ones the kernel already blessed. For `prove` to exit non-zero on one, Z3 would have to refute a proof `validate_pack` accepted. That is a soundness bug in the kernel's `_equality_guards` reasoning, not an authoring mistake.

So the exit code is a **differential check between two proof systems**, not a routine gate. It does not fire today across the six committed packs. It exists so that it could not stop being true silently. (`assurance/tests/test_prove.py::test_validate_pack_already_refuses_an_unproven_same_priority_pair` pins the argument.)

`prove-equivalent` exits 0 when everything asked was proved, 1 when a disagreement was found, and 2 when it could not answer.

## P4. The fragment

Types are resolved from the pack's pinned ontology when one is available, and inferred from use otherwise; a symbol that can be neither typed nor inferred is a loud pack-level `OUT-OF-FRAGMENT`, never a guess.

| Value kind | Encoded as | Faithful? |
|---|---|---|
| `boolean` | Z3 `Bool` | exactly |
| `decimal` | Z3 `Real` | see "Decimals are not reals" below |
| `money` | Z3 `Real` (the amount) | **currency is not modeled** — see below |
| `date` | Z3 `Int`, the proleptic Gregorian ordinal, bounded to `[1900-01-01, 2200-01-01)` | exactly, inside the bounds |
| `string` | Z3 `Int` index into a per-symbol finite domain | exactly, for equality |
| `code` | same as `string`; the index is the code's `value` field | value field only — `codeSystem` is not modeled |
| `datetime` | — | **not encoded** |
| `entityRef` | — | **not encoded** |

**String and code domains.** A symbol's domain is the ontology enum's `permissible_values` when the slot has a closed enum, plus every string literal the pack compares that symbol against, plus a per-symbol `«any other value»` sentinel when the code set is open (`openCodeSet: true`, e.g. ISO 3166-2 subdivisions) or when there is no enum at all. A literal outside a closed enum is kept in the domain anyway — widening, never narrowing.

Restricting a closed-enum symbol to its permitted values is an *assumption that the [conformance gate](ontology-conformance.md) holds* — that no fact carries an out-of-enum code. That assumption is enforced in CI over every committed fact, which is why it is worth making; it is stated here rather than buried because it is load-bearing for both coverage results and disjointness proofs on enum-typed attributes.

The sentinels are per symbol, and that is why **string-to-string comparison between two symbols is refused**: `«any other value»` for one symbol and `«any other value»` for another are different unknown strings, and no single finite encoding can represent both "they might be equal" and "they might differ" at once. Refusing is the only honest option.

| Operator | Encoding | Notes |
|---|---|---|
| `and` `or` `not` | Z3 `And` / `Or` / `Not` | exact |
| `==` `!=` on booleans, numbers, dates | Z3 `=` | exact |
| `==` `!=`, symbol vs string literal | index equality | exact; a literal outside the domain is `False` |
| `==` `!=`, code vs string literal | index equality on the code's value | matches the kernel's `_eq` |
| `==` `!=`, string symbol vs string symbol | — | **refused** (see above) |
| `<` `<=` `>` `>=` on `decimal`/`money`/`date` | Z3 ordering | exact |
| `<` `<=` `>` `>=` on `string`/`code` | — | **refused**: the index preserves equality, not lexicographic order |
| `+` `-` | Z3 `+` / `-` | typed per rule-IR: `decimal±decimal`, `money±money` |
| `*` | Z3 `*` | `decimal*decimal`, `money*decimal`; nonlinear when neither side is a numeral, and an `unknown` answer becomes `OUT-OF-FRAGMENT` |
| `/` | Z3 `/`, **only** when the divisor is a nonzero numeral | otherwise refused: the kernel raises on a zero divisor and SMT real division is total, so the two would disagree exactly where it matters |
| unary `-` | Z3 negation | exact |
| `date("YYYY-MM-DD")` | `IntVal(ordinal)` | exact |
| `days_between(a, b)` | `ToReal(b - a)` | exact — dates are day ordinals, so the subtraction *is* the day count |
| `abs(x)` | `If(x >= 0, x, -x)` | exact |
| `min(a,b)` / `max(a,b)` | `If(a <= b, a, b)` / `If(a >= b, a, b)` | exact, on ordered kinds |
| `add_business_days(d, n, "cal")` | the calendar's own walk, enumerated | see below |

### `add_business_days` is enumerated, not modeled

The calendar is pack data over a declared, bounded coverage window ([rule-ir.md](rule-ir.md), "Calendars"), so `add_business_days(d, n, cal)` for a literal `n` is a **finite function**. The encoder walks it exactly as `duly_kernel.expr` does, for every covered start date, then compresses the result: start dates are grouped by their offset (`result - start`, a small slowly-varying integer) and each group's dates are collapsed into contiguous intervals. The TILA pack's 727 in-coverage start dates become 235 intervals across a handful of offsets, and the whole analysis runs in under half a second.

The solver therefore reasons over the *same* 12 CFR 1026.2(a)(6) business days the kernel walks — Saturdays counting, Sundays and 5 U.S.C. 6103(a) holidays not — rather than over an idealization of them. That is what lets `RESC-FUND-STAY` (`today <= deadline`) and `RESC-FUND-EXP` (`today > deadline`) come back `PROVED-DISJOINT` over a *computed* deadline.

Two refusals and one assumption:

- **A non-literal count is refused.** Encoding `add_business_days(d, n, cal)` for symbolic `n` needs the walk itself to be symbolic, which is a different and much larger encoding.
- **A coverage window above 4,000 days is refused** rather than enumerated. The cap is arbitrary and stated; a pack that hits it gets a named `OUT-OF-FRAGMENT`, not a slow answer.
- **Start dates are assumed in coverage.** Outside it the kernel raises `ExprCalendarError` and the run produces no decision at all, so restricting the input space to in-coverage walks is restricting it to runs that *have* a decision to reason about. The assumption is printed under `--verbose` rather than left implicit.

### Decimals are not reals

duly's money is a decimal string precisely so that decimal semantics — exact `0.1`, no binary rounding — govern arithmetic. The encoding maps `decimal` and `money` to Z3 `Real`, which is exact *rational* arithmetic: every decimal literal maps to its exact rational value, so no rounding is introduced and nothing is lost to floating point.

What the mapping does not preserve is **scale**. In the kernel, `Decimal("0.10")` and `Decimal("0.1")` are equal in comparison but distinguishable in serialization; in the encoding they are one rational. This matters for exactly one thing, and it is worth naming: a `prove-equivalent` result of "these two packs conclude the same value" means the same *numeric* value, not the same rendered decimal string. Two packs concluding `0.1` and `0.10` are proved equivalent here and would produce different receipt bytes. If a future check needs byte equality of money values, scale has to be tracked alongside the rational — it is not tracked today.

The other gap is **currency**: a `money` symbol is encoded as its amount, and nothing represents its ISO 4217 code. The kernel raises `ExprTypeError` on a cross-currency comparison, which the encoding does not model. In practice every committed pack is single-currency; a pack whose disjointness *depends* on a currency mismatch would be silently mis-analyzed here, which is why it is stated rather than left to be discovered.

## P5. The encoding is a symbolic interpreter, not a guard-pattern matcher

The interesting failure of `_equality_guards` is not that it only accepts strings. It is that it only accepts `when` items whose variable resolves to an **`attribute`** binding, so a guard on a `derived` value proves nothing however string-equal it looks (CLAUDE.md's first gotcha; [spec/dmn.md](dmn.md) M6 states it too). A tool that inspected guards more cleverly would inherit the same wall.

So `prove` does not inspect guards. It builds, per rule and mirroring `kernel/duly_kernel/engine.py`:

- `fires(R)` — every binding resolves, `asOf.effective` is inside the effective window, and every `when` holds;
- `alive(R)` — `fires(R)` and no firing rule lists `R` in its `overrides`;
- `wins(R)` — `alive(R)` and no alive rule ahead of it in the kernel's winner order (priority descending, then pack order) concludes the same attribute;

and then *defines* each concluded attribute from its producers, stratum by stratum in `rule_strata` order: `defined(A) = Or(alive(R))` over producers, and `value(A)` as the nested `If` chain over `wins(R)`. A rule consuming `A` as a `derived` binding reads those definitions.

The consequence is the point: a guard on a derived value is reasoned about rather than approximated, so `band == "High"` versus `band == "Low"` on a derived binding comes back `PROVED-DISJOINT` — a proof the kernel cannot express at all.

**Existence is modeled explicitly.** Each attribute symbol carries an `exists` boolean, because a rule with an unresolvable binding is inapplicable, and "the fact was never asserted" is a distinct and frequently *decisive* region of the input space. It is what makes the coverage analysis say something true about missing evidence rather than assuming every fact is present. Entity existence is assumed (`the case carries exactly one entity of each entityType a rule binds`) and printed as an assumption: the v0 kernel restricts a case to one entity per type anyway, and a case with no entity at all is a degenerate witness that would crowd out every informative one.

**One shape is refused outright.** The kernel has two defeat paths: `_apply_defeat` suppresses an overridden rule globally, while `_select_producer` — which resolves a `derived` binding — sees only the firings settled at that point. They coincide unless a rule overrides a producer of a consumed derived attribute *from a strictly higher stratum*. No committed pack does this. If one ever does, the encoding raises `OUT-OF-FRAGMENT` naming both rules rather than quietly picking a reading.

**Rejected:** *treating derived values as free variables.* Sound (it widens), and it would have made every derived-guard pair `OUT-OF-FRAGMENT` and every coverage result about a derived attribute uninformative — which is most of the interesting ones, since defaults and exceptions compose through derived attributes.

## P6. Coverage: which questions the rulebase cannot answer

For each attribute the pack declares as a decision, `prove` asks whether any input in the fragment leaves it with no conclusion: `And(domain, Not(Or(alive(R) for R concluding A)))`.

`UNIQUE` decision tables from the [DMN compiler](dmn.md) are the natural consumer — a `UNIQUE` table with no default row is exactly a table with holes, and the compiler proves the rows disjoint but says nothing about whether they are *exhaustive*.

Two refinements make the answer useful rather than merely true:

- **An uncovered region reachable only outside every concluding rule's effective window is labeled as such.** Evaluating the TRID pack on 2015-10-02 reaches no conclusion because no rule is in force yet — true, and not what an author wants to hear first. `prove` asks for a live-rulebase gap first and falls back to the pre-effective one only when there is none, saying which it found. For `trid:toleranceCureAmount` the pre-effective region is the *only* hole, which is a much stronger statement than a bare `UNCOVERED`.
- **The witness closes over derived dependencies.** A witness saying "the derived category was `ZeroTolerance`" without saying which fact made it so is half a witness, so the symbol set is expanded transitively through each derived attribute's producers.

Coverage is a statement about *whether some rule concludes*, not about which one wins or whether the conclusion is right. It is the completeness half of a rulebase, and nothing more.

**Rejected:** *reporting coverage per rule ("this rule is unreachable") only.* Reachability is reported too — a rule no input can fire is dead weight in something a compliance reader has to review — but it is a strictly weaker question. Every rule in every committed pack is reachable, and three of the six packs still have coverage holes.

## P7. Equivalence, at two levels, because one of them is not enough

[spec/dmn.md](dmn.md) states a measured gap: its equivalence suite compares two packs over the committed fixtures, and perturbing the DMN source from `> disclosed` to `>= disclosed` leaves all twelve tests green, because the two differ only when the amounts are exactly equal and no fixture hits that boundary.

`prove-equivalent` answers over the input space instead. Both packs share the *input* universe — attribute facts and the evaluation point — and keep separate derived namespaces, because a derived value is something a pack computes, not something the case supplies. It reports two things:

- **Decision equivalence**, per attribute: `Or(definedA != definedB, And(definedA, definedB, valueA != valueB))` is UNSAT.
- **Trace equivalence**, over rule ids present in both packs: `fires`, `wins`, and the full `defeats` relation agree everywhere. `defeats(R, S)` mirrors `_apply_defeat` — an authored `overrides` defeating a rule that fired, plus the priority tiebreak defeating every other alive rule in the winner's group.

Priorities are deliberately **not** compared. [spec/dmn.md](dmn.md) M2 establishes that compiled priorities come from hit policy and row order rather than from an author, so what must match is the outcome of the tiebreak, not the numbers feeding it.

### The perturbation, and what it actually is

Trace equivalence catches the `>=` perturbation, at `actual == disclosed` and only there. Decision equivalence does not — and here is the finding worth recording rather than engineering around: **that perturbation changes no decision at all.** With the amounts equal, the cure rule concludes `actual - disclosed`, which is the same `0.00` the default rule concludes. Both packs answer `0.00`.

What changes is the receipt: `TRID-ZT-01` fires instead of `TRID-DEF-00`, and defeats it. So `spec/dmn.md` is right that it is a genuine semantic change and slightly imprecise about which semantics — it is a change to the audit chain, not to the answer. That distinction is exactly the one duly exists to make, so it is worth having the tool report at both levels rather than collapsing them.

A perturbation the fixtures *can* see (retyping one input cell from `"TransferTax"` to `"RecordingFee"`) fails at both levels, and the decision witness names the fee type that separates the two packs.

**Rejected:**

- *Comparing receipt bytes.* Impossible by construction and correctly so — a receipt pins its pack's name and version, so two packs are two identities ([spec/dmn.md](dmn.md), "Equivalence, exactly"). Equivalence between rulebases is a claim about decisions and traces; the tool makes it at exactly that level.
- *Matching rules by position or by guard text instead of by id.* The id is the handle every receipt cites, forever. Rules present in only one pack are named in the report rather than silently skipped.

## P8. Determinism

The repo forbids wall-clock and unseeded nondeterminism, and a report is an artifact somebody diffs.

**Solver resource use is bounded by `rlimit`, not a timeout.** z3's `rlimit` counts solver work deterministically, so the same query gives the same answer on a fast machine and a slow one. A wall-clock timeout would make `OUT-OF-FRAGMENT` depend on the machine — a nondeterministic verdict is worse than a slow one.

**Witnesses are normalized against a static candidate ladder.** Z3 models are not canonical: two runs, two versions, or two machines may each return a different satisfying assignment, and printing whichever one came back would make the report wobble. Instead the normalizer walks the symbols in sorted key order and *pins* each to the first value from a fixed ladder that keeps the query satisfiable. The ladder is drawn from the pack's own vocabulary — its numeric literals and their neighbours, its effective dates and calendar bounds and *their* neighbours, its enum values in order — so the result depends only on satisfiability answers, which are properties of the pack rather than of the solver's search.

It also makes witnesses readable. `toy:balance 10000`, not `20001/2`. Existence is pinned before values and prefers a *populated* case, because a witness naming concrete facts explains more than one saying everything is absent. A derived value is skipped: it is a function of the inputs, so once they are pinned it has no freedom left. In the rare case a ladder cannot pin a symbol, the value falls back to the model's and the witness says so in a footnote rather than presenting a solver-chosen number as a normalized one.

`assurance/tests/test_prove.py` holds the report byte-identical across repeated runs and across three `PYTHONHASHSEED` values in separate subprocesses, and the demo's output likewise.

## P9. z3-solver is optional, and stays optional

`z3-solver` sits in a `prove` extra with a `z3` pytest marker, exactly as `docling` sits behind `extraction` and `linkml` behind its own marker. Importing `duly_assurance.prove` without z3 installed does not raise; running it prints the install line and exits 2.

The reason is the same one that kept the DMN compiler and the conformance gate on zero new runtime dependencies: nothing on the path from a document to a receipt may acquire a dependency that a deployment has to vet, and a 36 MB solver binary is a real thing to vet. `prove` is a tool an author runs, not a component a decision passes through.

`--ontologies` is optional and has **no path default** (it also reads `DULY_ONTOLOGIES`). It used to default to `ontologies`, duly's own directory relative to the working directory, which is right in this repository and wrong everywhere else — the third instance of that defect, after the conformance gate and what-if. Without a registry the analysis still runs, inferring kinds from use and reporting `OUT-OF-FRAGMENT` for what it cannot infer; **that report is the honest degradation**, and it is why `prove` needed no equivalent of what-if's absent-registry note. A path that *is* given and does not exist is refused, because it was typed on purpose.

## Open questions (v0)

1. ~~**Should a proved-disjoint pair be recordable in the pack?**~~ **Partly decided.** The blocking question — what a replaying kernel does with a declared proof it cannot re-verify — is answered in [compatibility.md](compatibility.md) C2: **nothing.** A declared proof is an annotation, for humans and for `prove`; `validate_pack` still proves disjointness itself or demands an explicit `overrides`, so a pack author cannot widen kernel behaviour by asserting a proof. The receipt never carries one, for the same reason it carries no other producer assertion. What remains open is only whether the pack gains the annotation at all, which is now an ergonomics question about P1's sketch rather than a soundness one.
2. ~~**Should `prove` run in CI over `examples/rulepacks/`?**~~ **Decided:** yes, but not as a pack-PR gate. It runs in [`.github/workflows/optional-deps.yml`](../.github/workflows/optional-deps.yml), a separate workflow whose `pull_request` trigger is path-filtered to the directories whose claims it protects — `examples/rulepacks/**` deliberately not among them. The reasoning is the one P3 gives: `validate_pack` already refuses any pack with an unproven same-priority overlap and no `overrides`, so a pack that *loads* cannot make `prove` fail. It can only fail if Z3 refutes a proof `_equality_guards` accepted, which is a kernel soundness bug — so the run belongs on changes to `kernel/` and on every merge to `main`, and a pack-only PR pays nothing for an optional dependency it cannot affect.
3. **Should coverage holes be an authored declaration rather than a report line?** `county-recording-us` *means* to have one (an unknown jurisdiction gets no recordability presumption), and `resc:rescissionApplies` *means* to have one (a missing dwelling fact must not resolve). Both are documented in prose today. A `coverage: partial` declaration naming the intended holes would turn "the report has three UNCOVERED lines" into "the report has an UNCOVERED line the pack did not declare", which is the difference between a finding and a diff. It is additive and it is a rule-IR change.
4. **Scale-preserving money equivalence.** P4 states the gap: `0.1` and `0.10` are one rational here and two receipt byte-strings in reality. Tracking scale alongside the rational is possible; no consumer needs it yet.
5. **Should the fragment grow to `datetime`?** Nothing in the IR's `when` vocabulary needs it today — no committed pack compares datetimes — and adding it means deciding how to encode timezone-aware instants against date ordinals. Deferred until a pack wants it.
6. **Multi-entity rules.** [rule-ir.md](rule-ir.md) open question 1. The encoding assumes one entity per type exactly as the kernel does; quantified bindings would need quantified formulas, and the decidable fragment that keeps `PROVED` a proof would have to be re-established.
