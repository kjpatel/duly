# What-if queries — v0 draft

A receipt answers "what was decided, and why". [`prove`](pack-verification.md) answers "what is true of the rulebase". Neither answers the question an operator actually has, which is **what would have had to be true for this to come out differently** — the latest date the notice could have gone out, the largest fee that owes no cure, the earliest day the money may move.

[`whatif/duly_whatif`](../whatif/duly_whatif) answers it by freeing exactly one input of a decided case and solving the pack backwards.

```bash
uv run --with z3-solver python -m duly_whatif --ontologies examples/ontologies \
    --case examples/golden/cases/notice-ny-0001 --free nc:noticeMailedDate --target true
uv run --with z3-solver python -m duly_whatif --ontologies examples/ontologies \
    --case examples/golden/cases/resc-0001 --free asOf --target true --extremal min
```

`--ontologies` is **optional and has no default** (it also reads
`DULY_ONTOLOGIES`). Without one the tool still runs, inferring value kinds
from the pack's own use, and *says so in the report's notes* — because that
answer is weaker in a way nothing else would show: a code symbol's domain
becomes the literals the pack happens to mention plus anything else, which
is exactly the quantifier an `UNSATISFIABLE` verdict ranges over. Some packs
need one outright: an attribute the pack never *reads* has no usage to infer
from, so the encoding refuses and the tool exits `UNSUPPORTED` naming it.

Runnable demonstration: [`whatif_demo.py`](whatif_demo.py) — the latest compliant mailing date with its next-day refutation, the TRID maximum with no cure, TILA's earliest funding date over a computed rescission deadline, a flip, a coverage hole found by freeing a code, and the contradiction guard firing against a deliberately broken encoding.

**This is a validation-time analysis tool, and that is a hard boundary.** No solver output reaches a receipt. No subcommand changes any adjudication. What-if is not on the adjudication path, is not a dependency of the kernel, and is not installed by default — the same posture, and for the same reasons, as `prove`.

As with the fact contract, the DMN compiler, the conformance gate and the static verifier, everything below is a design decision with its rationale and the alternative that was rejected.

---

## W1. The soundness argument runs backwards from `prove`'s, and that is the whole design

`prove` rests on an invariant stated in [pack-verification.md](pack-verification.md) P2: **an approximation may only widen the input space, never narrow it.** Widening keeps UNSAT a proof — nothing satisfies the wider constraint, so nothing satisfies the narrower one either — at the cost of possibly-spurious SAT. `prove` pays that cost by downgrading a witness that leans on a widened symbol to OUT-OF-FRAGMENT.

**This tool lives on SAT.** Its entire product is satisfying assignments: *here is a value that produces the outcome you asked for*. So the property that makes `prove` sound makes a raw solver answer untrustworthy here. A widened symbol can hand back an assignment the real kernel would never reproduce, and there is no downgrade available — "possibly unreachable" is not an answer to "what date should I put on the notice".

Only one thing recovers soundness, and it is not a cleverer encoding:

> **The solver proposes. The kernel disposes.**
>
> Every value this tool returns has been run through `duly_kernel.api.adjudicate`, on a reconstructed and content-re-addressed fact set, and the resulting decision compared against the target. An unverified value is never returned.

That is why the encoding's widenings are *tolerable* here rather than fatal. A spurious SAT does not become a wrong answer; it becomes a `SolverKernelContradiction`. The tool cannot quietly be wrong in the SAT direction, because the kernel is downstream of every claim.

This mirrors the repo's own architecture rather than departing from it. `prove` is validation-time only because a proof about a rulebase must not become a hidden premise of a receipt. A what-if answer is one step further from the receipt still: it is a *proposal about a hypothetical run*, and the kernel remains the only thing that decides.

**Rejected:** *trusting the solver and skipping the kernel run.* It is faster, it is what a constraint tool normally does, and it would be wrong here for a reason that is structural rather than incidental — the encoding is deliberately approximate in the direction that makes SAT unreliable, and the whole product is SAT.

## W2. Two verdicts, and they are NOT equally strong

| Verdict | Means | Verified? |
|---|---|---|
| `SATISFIABLE` | Here are values of the freed input that produce the target. | **Yes** — the kernel ran on each and agreed. |
| `UNSATISFIABLE` | No value produces the target. | **No**, except over a finite domain (below). |
| `UNSUPPORTED` | A named construct put the question outside the fragment. No claim either way. | n/a |

The asymmetry is the most important thing this tool has to communicate, so it is printed in the output on every UNSATISFIABLE verdict rather than left in this document:

> A satisfying answer is checked pointwise: the kernel is handed the proposed case and agrees. **"No value works" has no point to check**, so nothing was verified against the kernel — it rests entirely on the SMT encoding being a faithful reading of the pack. Treat it as a strong hint to look, not as a proof that there is nothing to find.

`UNSATISFIABLE` is exactly as strong as `prove`'s `PROVED-DISJOINT`, and no stronger: both are UNSAT claims resting on the encoding. The difference is that `prove` returns nothing else, so its whole surface carries that caveat uniformly, while here two verdicts sit side by side and only one of them has been checked. Printing them in the same voice would be the dishonest option.

**One exception, and it is a real one.** A freed `boolean`, `string` or `code` has finitely many values, so "no value works" *can* be checked pointwise — by checking every point. The tool does exactly that: every member of a finite domain gets its own kernel run, satisfying or not, and both verdicts are verified. Such a report is marked `complete`, and the renderer drops the caveat, because there it would be false modesty.

**Rejected:** *a single verdict vocabulary shared with `prove`.* `PROVED` / `NOT-PROVED` reads as though the tool proved something in both directions. It does not, and the words would hide the one distinction a user most needs.

## W3. Extremal answers are boundary-verified, and even that is not maximality

The interesting answer is rarely "some value works". It is the extremal one: the *latest* compliant mailing date, the *largest* fee owing no cure, the *earliest* permitted funding date. Those come from Z3's `Optimize`.

An extremal claim is verified at its boundary — the extremal value produces the target, **and one step beyond it does not**, both according to the kernel:

```
    largest value reaching the target: 2026-04-24
      kernel confirms  2026-04-24 -> true
      kernel refutes   2026-04-25 -> false
```

Worth stating precisely rather than implying, because it is the seam where this tool's guarantee stops: those two kernel runs establish that the value works and that the next one along does not. They do **not** establish that nothing *further* out works. That last part is the maximality claim, it is an UNSAT claim, and like every UNSAT claim here it rests on the encoding. The output says so under every extremal.

For a `flip` the extremal is the **nearest** value rather than the most extreme one — how little would have had to change — and the verified boundary is the step back *toward* today's value, which must not flip.

**When the satisfying region has no extremal that way**, the tool does not return "unbounded" and stop; that would be an unverified claim, which is the one thing it must not return. A region unbounded one way is reported from its other, finite end (*every value from 3176.76 upward owes no cure*), boundary and all. A region unbounded both ways is reported with today's own value as the witness — deterministic, already in the case, and still kernel-verified.

## W4. A solver/kernel contradiction is a loud error, never a dropped answer

When the kernel refutes something the solver claimed, the tool raises `SolverKernelContradiction`, carrying **both** artifacts: what the solver claimed, and the fact set, evaluation point and decision the kernel produced. The CLI exits 3.

It is not a filter. A candidate that fails verification is never silently skipped and never silently returned, because both of those turn a defect into a wrong answer. Reaching this state means the encoding and the kernel disagree about the rule IR, which is a bug in one of them and is not something a user can work around.

**The guard is tested by firing it.** `whatif/tests/test_whatif.py` injects two broken encodings — the solver is handed a perturbed pack while the kernel keeps running the real one — and requires the raise. Both now run on the toolkit's own fixture pack, so the proof survives the deletion of the teaching content; the shapes are unchanged. The first is worth understanding, because it shows why verifying the answer alone is not enough:

- Perturbing the fixture pack's exception guard from `score < minimum` to `<= minimum` moves the permitted boundary by one. The solver answers 51.
- **The kernel confirms 51 is permitted.** The answer check passes. A tool that verified only its answer would return a wrong value that passed its own test.
- The boundary check is what catches it: the solver claims 50 is not permitted, the kernel says it is, and the tool refuses to answer.

The second injection retypes the category guard from `"restricted"` to `"ordinary"` — the same shape as the perturbation [pack-verification.md](pack-verification.md) P7 records as failing at both levels — so the solver concludes no score owes the fee, and the kernel refutes the first value handed to it.

**Rejected:** *logging the contradiction and returning the next candidate.* It converts a soundness bug into an intermittent wrong answer, which is strictly worse than a crash — and the crash is actionable, since it arrives with both artifacts attached.

## W5. The encoding is `prove`'s, and it was not extended

Symbols, value kinds, finite string/code domains, the `fires`/`alive`/`wins` interpreter, derived-attribute definitions and the exact `add_business_days` enumeration all come from [`assurance/duly_assurance/smt.py`](../assurance/duly_assurance/smt.py) unchanged. **No line of it was modified for this track**, and `assurance/tests -m z3` is unaffected.

That is deliberate and it is the load-bearing decision in the package. Two encodings of one IR would agree until they didn't, and the disagreement would surface as a wrong answer to a user rather than as a test failure. `whatif/tests/test_whatif.py::test_the_encoding_is_the_one_prove_uses` asserts the identity of the imported classes so that a future divergence has to be deliberate.

The fragment is therefore exactly [pack-verification.md](pack-verification.md) P4's, including its two stated gaps, which are inherited verbatim:

- **Currency is not modeled.** A `money` symbol is its amount; nothing represents the ISO 4217 code. A freed money value carries the currency the case's own fact carries, and a pack whose behaviour turned on a currency mismatch would be mis-analysed here exactly as it is there.
- **Decimal scale is not preserved.** `0.1` and `0.10` are one rational in the encoding and two receipt byte strings in reality. The answers this tool prints are rendered from the grid (W6), not from the encoding's rational, so a returned value has a definite scale — but an equality the solver reasoned about was numeric, not textual.

What *is* added lives entirely in `whatif/`: pinning every input but one, restricting a freed decimal to its grid, keeping a freed evaluation point inside the pinned facts' truth windows, and the verification layer.

## W6. A freed decimal is searched on its decimal grid — the one narrowing, and it is why UNSAT is weaker here

`smt.py` maps `decimal` and `money` to Z3 `Real`. For `prove` that is right: it widens, and widening is safe there.

For a what-if it produces answers that cannot exist. The largest amount owing no cure under `actual > disclosed` has no maximum over the reals — the supremum is `disclosed` itself only because the region is closed there, and the mirror-image query (*the smallest amount that DOES owe a cure*) has an infimum of `disclosed + ε` that no fact could carry and no kernel run could verify. An extremal that cannot be written into a fact is not an answer.

So a freed `decimal` or `money` input is pinned to its **decimal grid**: the scale the case's own value carries (`--scale` overrides). duly's money is a decimal string precisely so decimal semantics govern it, so the grid is where the answers actually live.

This is a **narrowing**, and it is the only one. It is safe for the SAT direction — a grid value is a real value, so the kernel verifies it like any other — and it is *not* safe for the UNSAT direction, which is stated in the output rather than buried: an `UNSATISFIABLE` verdict on a freed decimal means **"no value at this scale"**, and the report says so in those words.

**Rejected:** *searching over the reals and rounding the answer.* Rounding an infimum produces a value that either fails verification (`disclosed`, which owes nothing) or is not extremal, and the tool would have to choose which lie to tell.

## W7. Exactly one freed input, and the evaluation point counts as one

A query frees **one** input. Freeing two turns a boundary into a frontier, and a frontier has no extremal to report or to verify at — the answer would be a region, and this tool's contract is built on handing the kernel points.

The freeable inputs are an attribute the pack reads, or `asOf` — the evaluation point. Freeing the evaluation point is not a special case bolted on: `asOf.effective` is already a first-class symbol in `smt.py`'s encoding and already a parameter of `adjudicate`, so it is an input to the run in exactly the sense a fact is, and it verifies the same way. It is also what makes the flagship TILA question askable at all, since "when may I disburse?" is a question about the evaluation date rather than about any document.

**Rejected:** *freeing several inputs and reporting a Pareto frontier.* Every point on it would need its own kernel run to satisfy the contract, the count is unbounded, and the interesting operator question is nearly always one-dimensional.

## W8. What-if varies a value; it never invents a fact

Freeing an attribute the case does not assert is a named refusal, not a synthesised fact.

The reason is duly's premise rather than implementation convenience. A `GroundedFact` points at a document span or a named attestation; that grounding is what makes the receipt worth anything. A value a solver proposed is grounded in nothing, and minting one would require inventing the entity it attaches to, the assertion kind, the confidence and the provenance — four guesses, each of which can change the decision (a machine assertion below the pack's floor abstains; the notice pack's floor for `nc:noticeMailedDate` is 0.9). Asking "what if this document had said X" is a real question; asking "what if a document I do not have said X" is a different one, and the honest way to ask it is to assert the hypothetical fact and re-run.

Where the tool *does* substitute, it obeys content addressing: a changed value produces a new `contentHash` and a new `id`, nothing is mutated in place, and the caller's fact list is left byte-identical (`test_a_what_if_leaves_the_case_it_reasoned_about_untouched`).

## W9. Liveness is the kernel's own, not a second implementation

Which facts actually bind — after supersession, effective windows, the pack's `abstentionPolicy` and conflict resolution — is decided by importing the kernel's own helpers, and every attribute with no live fact is pinned **absent** rather than left free.

That matters more than it sounds. "The fact was never asserted" is a distinct and frequently decisive region of the input space, and a what-if that let the solver assume a missing fact into existence would answer a question about a case that does not exist. A second implementation of liveness would be the same latent defect as a second SMT encoder, so there is not one.

The rule reaches the evaluation point's *parse*, and that is where it was broken. A case's `asOfEffective` is read with the kernel's own `normalize_point`, so a bare date and the midnight-Z instant are one point here exactly as they are in the kernel. What-if used to read the field with `date.fromisoformat` and traceback on the instant — which duly's own freezer writes, `duly_review.golden` copying the receipt's `date-time`-typed `asOf.effective` into the case it seals. A second implementation of a *parse* is the same defect as a second implementation of liveness, in a smaller costume: it agreed with the kernel on every generated case and disagreed on every review-exported one. A point that genuinely is not a date is now a diagnostic naming the field and the file, not a traceback.

A freed *evaluation point* additionally stays inside every pinned fact's truth window. `smt.py` does not model fact windows — it reasons about a rulebase, where facts are free — so that constraint lives in `whatif/`, and it is what keeps the `exists` pins consistent with the dates the solver is allowed to consider.

## W10. Determinism, without a normalization ladder

The repo forbids wall-clock reads and unseeded nondeterminism, and a report is an artifact somebody diffs.

`prove` needs a candidate ladder because it prints a whole *witness*, and Z3 models are not canonical. This tool does not need one: the freed symbol is the only degree of freedom, and the question itself pins which of its values to report. An `Optimize` optimum is unique even when the model around it is not, so the answer is a property of the constraint set rather than of the solver's search. A finite domain is enumerated in the symbol's own stored order.

Solver work is bounded by `rlimit` rather than a wall-clock timeout, for the reason [pack-verification.md](pack-verification.md) P8 gives: a verdict must not depend on how fast the machine is.

`whatif/tests/test_whatif.py` holds the JSON output byte-identical across three `PYTHONHASHSEED` values in separate subprocesses, for four differently-shaped queries.

## W11. The open code set's residual region is verified, not asserted

`smt.py` gives an open code set (`openCodeSet: true`, e.g. ISO 3166-2) a single `«any other value»` slot standing for every unenumerated value at once. That slot is not a value a fact could carry, so returning it as an answer would return something unverified.

Instead the region is verified with one deterministic representative value and reported as a region:

```
      any value other than "US-CA", "US-FL", "US-NY"  ->  true
        (an open code set has no enumerable residual, so this region was
         verified with one representative value: «any-other-value»)
```

The label is deliberately not a plausible-looking code. Printing `US-TX` would suggest the tool had reasoned about Texas; it reasoned about "not one of the three the pack names", and the representative is there to make the claim checkable rather than to name an answer.

This is how freeing `nc:governingState` on `notice-ny-0001` surfaces a genuine coverage hole in the notice pack: no state the pack knows makes a twelve-day notice compliant, and every state it does not know does — because nothing concludes a minimum, so the deficiency rule cannot bind its derived input and the default presumption stands. `prove`'s coverage analysis reports the same hole from the other direction.

## W12. z3-solver is optional, and stays optional

What-if shares the `prove` extra and the `z3` pytest marker. Importing `duly_whatif` without z3 installed does not raise; running it prints the install line and exits 2.

Same reason as `prove`: nothing on the path from a document to a receipt may acquire a dependency a deployment has to vet, and a 36 MB solver binary is a real thing to vet. What-if is a tool an operator runs, not a component a decision passes through.

---

## What this deliberately does not do

- **It does not put anything in a receipt.** A what-if is a proposal about a run that did not happen. There is no artifact, no hash, and no audit-chain entry — asking "what would have happened" must not create a record that looks like something having happened.
- **It does not free more than one input at a time** (W7).
- **It does not invent facts, entities or grounding** (W8). An attribute the case does not assert is a refusal.
- **It does not model currency, and does not preserve decimal scale in the solver's reasoning** (W5), because the encoding it reuses does not.
- **It does not answer over `datetime` or `entityRef` inputs**, which are outside `smt.py`'s fragment. The refusal names the kind.
- **It does not prove maximality** (W3). It verifies the extremal and the step beyond it; that nothing further out works is an encoding-level claim.
- **It does not make `UNSATISFIABLE` a verified answer** except over a finite domain (W2). This is the single most important limitation and it is repeated in the tool's own output.
- **It does not flip a non-boolean decision without a target** (W3). "Anything other than 192.74" is a region, and an extremal over a region is not a question with one answer.
- **It does not change what a pack must satisfy to load.** Like `prove`, it is additive; `validate_pack` is untouched.

## Open questions (v0)

1. **Should a verified what-if boundary be recordable anywhere?** Today it is transient by design (`does not do`, first bullet). But "the latest compliant mailing date for this policy is 2026-04-24, kernel-verified at both sides" is exactly the sort of thing an operator wants to hand to a colleague. Anything durable needs an identity, a pinned pack version, and a decision about what a replaying kernel does with it — which is the same shape as [pack-verification.md](pack-verification.md) open question 1 and [dmn.md](dmn.md) open question 1, and wants deciding with them.
2. **Should the decimal grid come from the ontology rather than from the fact?** W6 takes the scale from the value the case carries, which is a good default and an arbitrary one: two facts for one attribute could carry different scales. A `scale` (or `minorUnits`) annotation on the ontology slot would make it a property of the domain instead. Additive, and nothing needs it yet.
3. **Two freed inputs, reported as a frontier?** W7 rejects it for v0 on verification grounds. A bounded variant — free two, report the extremal of one with the other pinned to each of a finite domain's values — stays inside the contract and would answer "which state *and* which mailing date". Not attempted.
4. **Should what-if run in CI over the golden corpus?** It is fast, and a boundary that moved without a pack change would mean the encoding and the kernel had drifted — which is precisely what the contradiction guard detects. The argument against is the same one as `prove`'s: it makes an optional dependency a required CI install. Not decided.
5. **Freeing the knowledge point.** `asOf.knowledge` is echoed on the receipt but does not filter facts in v0 (`kernel/duly_kernel/engine.py`), so freeing it would be answering a question the kernel does not yet ask. Deferred until the bitemporal store projection lands.
