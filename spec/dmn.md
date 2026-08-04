# DMN decision tables as an authoring surface — v0 draft

[Rule IR](rule-ir.md) opens by calling itself "the neutral middle format for rules: authoring surfaces (YAML today, DMN later) compile into it". This document is that later. [`dmn/duly_dmn`](../dmn/duly_dmn/) compiles a DMN 1.3+ decision table into a rule-IR pack. Nothing downstream knows the difference: same IR, same kernel, same receipts, same replay.

The promise a decision table makes is that a **business analyst can read the rulebase**. The promise duly makes is that **every decision is defensible**. This compiler exists at the seam, and where the two promises pull apart it sides with the second one — loudly, in the author's face, at compile time. A DMN table that would compile into a rule duly cannot justify is a compile error, not a warning and not a best effort.

Runnable demonstration: [`dmn_demo.py`](dmn_demo.py) compiles [`dmn/examples/trid-fee-tolerance.dmn`](../dmn/examples/trid-fee-tolerance.dmn) and adjudicates the committed TRID starter facts twice — once under the compiled pack, once under the hand-written [`rulepacks/trid-fee-tolerance-us-federal`](../rulepacks/trid-fee-tolerance-us-federal/pack.yaml) — showing the same decision, the same rules fired, and the same defeat chain.

As with the fact contract and the conformance gate, everything below is a design decision with its rationale and the alternative that was rejected.

---

## M1. Decision tables only, and only the S-FEEL subset of their cells

The compiler accepts **decision tables**. A `<decision>` whose logic is a boxed expression — a literal expression, a context, an invocation, a relation, a function definition — is refused by name.

Inside a table, cells are compiled as **S-FEEL** (DMN 1.3 clause 10.3.1, the "Simplified FEEL" subset decision-table cells are actually defined over), and not one token more:

| Input cell (unary test) | Compiles to |
|---|---|
| `-` or empty | no condition, and *no binding* (see M4) |
| `"TransferTax"` | `feeType == "TransferTax"` |
| `= "TransferTax"` | `feeType == "TransferTax"` |
| `< 45`, `<= 45`, `> 45`, `>= 45` | `days < 45` … |
| `> disclosed` | `actual > disclosed` — the endpoint may be another column |
| `[1..5]`, `(0..10]`, `[0..10)`, `]0..10[` | `(x >= 1 and x <= 5)` … |
| `"A","B"` | `(x == "A" or x == "B")` |
| `not("A")` | `not (x == "A")` |
| `date("2026-03-15")` | `date("2026-03-15")` |

| Output cell | Compiles to |
|---|---|
| `"ZeroTolerance"` | a literal `then.value` |
| `0.00` | a literal, **lexeme preserved** — `0.00` never becomes `0.0` |
| `actual - disclosed` | `then.value.expr`, arithmetic over column bindings |

**Why S-FEEL and not FEEL:** FEEL is a full expression language with iteration, quantification, conditionals, contexts, ranges-as-values, temporal arithmetic and a builtin library. duly's expression language is deliberately tiny and typed (rule-ir.md, "Expression language"), and the gap is not an implementation backlog — it is a design position. A rule that needs `every fee in fees satisfies …` needs multi-entity binding, which the IR does not have and which rule-ir.md tracks as open question 1. Compiling such a cell would mean inventing semantics the kernel cannot execute.

**Why the refusal is loud:** the failure mode of a lenient compiler is a *dropped condition*, and a rule with a dropped condition fires more often than its author believes. That is confident wrongness with an audit trail attached — the single worst outcome this project can produce. Every unsupported construct raises, naming the construct, the decision, the row, the column, and the cell text:

```
[unsupported-expression] cell invokes the function 'sum'. The supported S-FEEL subset
permits no function invocation other than `date("YYYY-MM-DD")` — arithmetic and calendar
functions belong in the rule IR, not in a decision-table cell.
  at decision 'cure', row 1 (rule 'REFUSE-SFEEL-01'), column 'actual'
     [trid:actualAmountAtClosing]: '> sum(disclosed, 100)'
```

**Rejected:**

- *A permissive mode that skips cells it cannot compile.* See above; there is no safe direction to fail in. A skipped input cell widens a rule, a skipped output cell breaks it — and neither is visible on the receipt, which records the *compiled* rule, not the table.
- *Translating FEEL builtins into duly expression functions where names happen to line up* (`abs`, `min`, `max`, `date`). Except for `date(...)`, which is a literal form rather than a computation, the coincidence is superficial: FEEL's `min` is variadic and list-aware, duly's is binary and typed. A partial mapping with silently different edge behaviour is worse than none.
- *Compiling boxed expressions.* A literal expression is a rule with no table, so it carries no rows — and rows are where the citation convention lives (M3). A rule with no row has nowhere to put its authority.

## M2. Hit-policy mapping: three supported, four refused

| DMN hit policy | Compiles to | Notes |
|---|---|---|
| `UNIQUE` (`U`) | all rows at **priority 0** | must pass the disjointness check (M6) |
| `FIRST` (`F`) | **descending priorities in row order**, step 100, last row at 0 | |
| `PRIORITY` (`P`) | same as `FIRST` | refused when the output declares `outputValues` |
| `ANY` (`A`) | — | refused |
| `COLLECT` (`C`) | — | refused |
| `RULE ORDER` (`R`) | — | refused |
| `OUTPUT ORDER` (`O`) | — | refused |

**Why FIRST becomes priority and not `overrides`:** duly has two defeat mechanisms (rule-ir.md, "Defeasibility semantics"), and they mean different things. `overrides` is an *authored claim* — "this rule is an exception to that one" — that the receipt reports as a named defeat. Priority is the *mechanical tiebreak* for two rules that happen to conclude the same attribute. FIRST is mechanical: it says "the row nearer the top wins", which is exactly priority, and nothing about which rule is an exception to which. Synthesising `overrides` from row order would put a legal claim in the author's mouth.

This costs nothing on the receipt: the kernel's priority tiebreak populates the winner's `defeated` list too, so a FIRST table still produces `TRID-ZT-01 defeated TRID-DEF-00` in the audit chain. An author who *does* mean "exception" writes it in the `duly:overrides` annotation column, and it survives across tables — which row order cannot express.

**Why the priorities are round numbers with gaps:** the kernel compares priorities and never their spacing, so the step is cosmetic — but leaving gaps means a hand-written rule can be slotted between two compiled ones without renumbering. Compiled priorities are *not* stable identifiers; they are derived from row count and row position, so inserting a row renumbers the table. That is why they are the one thing the compiled pack does not reproduce from the hand-written TRID pack (see "Equivalence, exactly").

**Why `PRIORITY` with `outputValues` is refused rather than approximated:** under DMN, `PRIORITY` orders matches by the position of a row's *output value* in the output column's `outputValues` list — not by row position. Compiling it as row order would silently contradict a table that says otherwise, so a table declaring `outputValues` is refused with instructions (drop `outputValues`, or reorder the rows and use `FIRST`). Without `outputValues`, DMN gives `PRIORITY` no ordering at all and row order is the only ordering present.

**Why the other four are refused:** none of them is a scheduling gap; each asks for something the IR does not have.

- `COLLECT`, `RULE ORDER`, `OUTPUT ORDER` return a **list** of outputs, optionally aggregated. A duly decision is one value for one attribute on one entity. There is no list-valued conclusion in the IR and no aggregation operator in the expression language.
- `ANY` permits overlapping rows *provided they agree on the output*. duly resolves same-priority conclusions by refusing the pack outright and has no notion of "overlapping but agreeing", so compiling `ANY` would mean either fabricating an ordering the author did not write or dropping the agreement check the policy exists for.

**Rejected:** *compiling `COLLECT(SUM)` into a single rule whose `then.value.expr` sums the matching rows.* It reads plausible and it is wrong: which rows match is a per-case fact, so the sum is not expressible as a static expression, and the receipt would report one rule where the author wrote five.

## M3. Legal metadata rides in annotation columns; structural metadata rides in extension elements

DMN 1.3 added **rule annotation columns** — `<annotation name="…"/>` on the table, `<annotationEntry><text>…</text></annotationEntry>` per rule. That is the citation vehicle, and it is why 1.3 is the floor version.

The `duly:` annotation namespace is **closed**: an unrecognised `duly:*` column is a compile error, so `duly:citaton` fails instead of silently discarding a citation.

| Annotation column | Required | Becomes |
|---|---|---|
| `duly:ruleId` | **yes** | `rules[].id` |
| `duly:citation` | **yes** | `rules[].citation.text` |
| `duly:effectiveFrom` | **yes** | `rules[].effectiveFrom` |
| `duly:citationUrl` | no | `rules[].citation.url` |
| `duly:effectiveTo` | no | `rules[].effectiveTo` |
| `duly:version` | no (default `1.0.0`) | `rules[].version` |
| `duly:overrides` | no | `rules[].overrides` (comma-separated ids) |

Columns whose name does not start with `duly:` are free-form and ignored — a `Comment` or `Reviewed by` column stays an author's note.

**Why annotation columns and not extension elements, for these three:** a decision table's entire value proposition is that *the table is the artifact a reviewer reads*. A citation hidden in XML that no modeller renders would be a citation nobody reviews, which is the same as no citation. These are also per-row data, which is what an annotation column is for.

**Why `duly:ruleId` is required rather than derived.** A rule id is the handle every receipt cites, forever. Deriving it from row position (`TABLE-03`) would mean that inserting a row above it silently re-labels history: the same legal rule acquires a new id, or worse, an old id starts naming a different rule. Nothing in the audit chain would show it. So the id is authored — the one piece of DMN-side bookkeeping this compiler makes mandatory.

**Why an uncited row is an error and not an auto-`TODO(verify)`.** The repo's honesty convention (rulepacks/README.md) allows an unverified rule *provided it says what was not confirmed*. That marker is a human act: somebody looked, failed to confirm, and recorded it. A compiler writing `TODO(verify)` on an author's behalf produces a marker indistinguishable from a considered one, which degrades every genuine marker in the corpus. The same argument covers `duly:effectiveFrom`: defaulting to `1900-01-01` would be a claim about legal history nobody made.

A genuine presumption is still expressible — write `Default presumption` in the citation column, exactly as the hand-written packs do. The compiler requires an author to *say* it.

**What rides in extension elements instead.** Four things have no DMN vocabulary at all, and all four are per-decision rather than per-row, so a column would repeat them down every row:

```xml
<definitions …>
  <extensionElements>
    <duly:pack name="trid-fee-tolerance-dmn" version="2026.1.0"
               ontology="duly-mortgage-closing" ontologyVersion="0.1.0"/>
  </extensionElements>

  <decision id="toleranceCategory" name="trid:toleranceCategory">
    <question>Which tolerance category applied to this fee?</question>
    <extensionElements>
      <duly:decision entityType="trid:Fee" attribute="trid:toleranceCategory"
                     entityVar="fee" valueKind="code"
                     codeSystem="duly-starter-trid/tolerance-categories"
                     codeSystemVersion="0.1.0"/>
    </extensionElements>
```

- **`entityType`** — *the deepest impedance mismatch between the two models.* DMN decides over a flat input context; it has no notion of the **entity** a decision is *about*. duly's every conclusion is `{entity, attribute, value}`, and its receipts, conflict detection and abstention entries are all keyed by entity. There is no DMN element to hijack that would not be a lie about what it means.
- **`attribute`** — the CURIE the table concludes.
- **`valueKind`** (+ `currency`, `codeSystem`, `codeSystemVersion`) — DMN's `typeRef` offers `string`/`number`/`boolean`/`date`. duly needs `money` (which carries a currency) and `code` (which carries a code system and version, because a bare code with no system is exactly the ambiguity the [conformance gate](ontology-conformance.md) exists to reject). `number` cannot say either.
- **`entityVar`** — optional; defaults to the lower-cased local part of `entityType` (`trid:Fee` → `fee`).

Everything DMN *does* have a vocabulary for uses it: `<question>` becomes the decision's human question, `<description>` on `definitions` becomes the pack description, `<description>` on a rule becomes `rules[].description`, and the `label` attribute on an input column becomes the duly binding name.

**Rejected:**

- *Putting citations in `<extensionElements>` too.* Uniform, and invisible in every decision-table rendering. The point of the table is review.
- *Putting `entityType` in `<variable typeRef="trid:Fee"/>`.* `typeRef` names the type of the decision's *output*, not the subject it is about. Reusing it would make a valid DMN document mean something false.
- *Deriving the binding name from `<inputExpression>` alone, with no `label`.* Supported as the default (`trid:feeType` → `feeType`), but `label` wins: it is the column header a reviewer already reads, and it is what an output cell like `actual - disclosed` has to name.

## M4. A `-` cell removes the binding, not just the condition

This is the single most consequential semantic decision in the compiler, and the one most likely to surprise.

In DMN, an input column is part of the table's *signature*: every row is evaluated against every input, and `-` means "this row does not care what that input is". In duly, inputs arrive through `given` bindings, and **an unresolvable binding makes the rule inapplicable** (rule-ir.md, "Resolution semantics"). The two are not the same thing.

So a naive column-to-`given` mapping makes every row require every input's fact to *exist*. The catch-all default row of the TRID cure table — three `-` cells, no conditions — would quietly become "no cure is owed, **provided** we extracted the baseline disclosure, the closing amount, and the category". A fee whose Loan Estimate line was never extracted would get no conclusion at all instead of the presumption. The rule would look like a default and behave like a conditional.

The compiler therefore binds an input column for a row **iff** the cell is not `-`, **or** the column's name is referenced by another cell in that row (an endpoint like `> disclosed`, or the output expression). Everything else is left unbound.

On the TRID example this reproduces the hand-written pack's `given` blocks exactly:

- `TRID-DEF-00` (all cells `-`) binds only the entity — as authored.
- `TRID-ZT-01` binds `category` and `actual` from their cells, and `disclosed` because `> disclosed` and `actual - disclosed` name it — as authored.

**Rejected:** *binding every column on every row.* Turns defaults into conditionals, silently, in the direction of "no answer" — which at least fails safe, but fails safe by abstaining on cases the author wrote a rule for. *Binding only cells with conditions.* Breaks `> disclosed` and `actual - disclosed`, which need a binding the cell itself does not create.

## M5. One output column per table

DMN lets one table conclude several outputs at once. A duly rule's `then` concludes exactly one attribute for one entity, and the receipt's priority and defeat semantics are defined per attribute. A multi-output table is refused; split it into one `<decision>` per output.

**Why not split automatically:** the split would create rules the author never wrote, with ids the author never chose — and M3 has already established that ids are not the compiler's to invent. A three-row, two-output table would silently become six rules in the receipt.

## M6. UNIQUE is refused when disjointness cannot be proven

`UNIQUE` asserts that no two rows can ever both match. duly's pack validator makes the same claim checkable, and it accepts exactly two proofs for same-priority rules concluding one attribute (`_check_priority_ambiguity` in [kernel/duly_kernel/ir.py](../kernel/duly_kernel/ir.py)):

1. non-overlapping effective windows, or
2. contradictory **quoted-string equality guards on the same bound attribute** — `state == "US-NY"` versus `state == "US-FL"`.

Everything else is unprovable to it. In particular — and this catches people — **a numeric range is not a proof, a boolean split is not a proof, and a guard on a `derived` binding is not a proof.** The last one is not in CLAUDE.md's gotcha list and is worth stating: `_equality_guards` only considers `when` items whose variable resolves to an `attribute` binding, so `category == "ZeroTolerance"` on a `derived` column proves nothing, however string-equal it looks.

When rows in a `UNIQUE` table cannot be proven disjoint, the compiler **refuses**, naming the row pairs:

```
[unprovable-unique] hit policy UNIQUE claims these rows can never both match, but their
disjointness cannot be proven: rows 1 and 2 ('REFUSE-UNIQ-01' / 'REFUSE-UNIQ-02'). …
Either scope the rows with string equality cells, give them disjoint
duly:effectiveFrom/duly:effectiveTo windows, or — if you meant "the earlier row wins"
rather than "they never overlap" — use hit policy FIRST.
```

**Why refuse rather than emit pairwise `overrides`.** Emitting `overrides` would compile "these rows never overlap" into "row 1 beats row 2" — an ordering the author did not write and which `UNIQUE` explicitly disclaims. If the rows genuinely do overlap, DMN itself calls that a runtime error; duly would instead pick a winner and put a confident, defensible-looking receipt behind it. Substituting a total order for a mutual-exclusion claim is precisely the silent approximation this repo forbids. And the fix is one word: if ordering is what the author means, `FIRST` says so, and says so in the table where a reviewer can see it.

**Rejected:** *teaching the compiler to prove numeric-range disjointness itself* (`[0..10]` versus `> 10` is trivially disjoint). Tempting, and wrong at this layer: the *kernel* would still reject the pack, because the proof lives in `validate_pack`, which sees only compiled `when` strings. A compiler that emits packs the kernel rejects has compiled nothing. Making interval reasoning a proof is a rule-IR change — a real and defensible one — and it belongs in rule-ir.md, not here.

## M7. Byte-determinism, and zero new dependencies

Same DMN bytes in, byte-identical `pack.yaml` out, forever. A compiled pack's version ends up inside `rulePack.version` on receipts that must replay byte-for-byte for the life of the system; if the compiler's output could wobble, a receipt could stop reproducing with nothing in the audit chain to explain it.

What that costs, concretely: element document order everywhere (never a dict or set iteration); the emitter sorts nothing (the compiler already fixed the order, and re-sorting at emit time would hide an ordering bug rather than expose it); the `# Source:` header is repo-relative so two checkouts agree; no wall clock and no randomness anywhere. [`dmn/tests/test_determinism.py`](../dmn/tests/test_determinism.py) proves it, including a subprocess pair run under different `PYTHONHASHSEED`s.

The YAML is emitted by a small hand-written writer rather than `yaml.dump`, for three reasons: PyYAML cannot write the provenance header a generated file must carry, cannot keep `given` bindings on one line the way the authored packs do, and offers no byte-stability guarantee across its own releases. The risk that buys — a hand-written emitter can quote something wrongly — is retired by a round-trip test: every emitted document is parsed back with `yaml.safe_load` and must reconstruct the compiled dict exactly, so `0.00` staying a string and `2015-10-03` not becoming a `date` are asserted, not hoped for.

Dependencies: stdlib `xml.etree.ElementTree`, plus the kernel and PyYAML the repo already has. **No new runtime dependency** — the same posture the [conformance gate](ontology-conformance.md#c4-the-enforcing-validator-is-a-pure-python-interpreter-of-a-constrained-linkml-subset) took toward linkml-runtime, for the same reason.

DMN namespaces accepted: 1.3 (`…/20191111/MODEL/`), 1.4 (`…/20211108/MODEL/`), 1.5 (`…/20230324/MODEL/`). 1.1 and 1.2 are refused by name: rule annotation columns, the citation vehicle, do not exist before 1.3.

---

## Refusal classes

Every refusal carries a machine-readable class and a location. One minimal example per class is committed under [`dmn/examples/refusals/`](../dmn/examples/refusals/) and exercised by [`dmn/tests/test_refusals.py`](../dmn/tests/test_refusals.py), which asserts the message names the actual problem — not merely that something was raised.

| Class | Raised when | Example |
|---|---|---|
| `unsupported-dmn-version` | the `definitions` namespace is not DMN 1.3–1.5 | — |
| `malformed-document` | no `decision`, no `decisionTable`, missing `duly:pack`/`duly:decision`, unknown `duly:*` annotation, duplicate rule id, or a compiled pack the kernel rejects | — |
| `unsupported-hit-policy` | `ANY`/`COLLECT`/`RULE ORDER`/`OUTPUT ORDER`, or `PRIORITY` with `outputValues` | [`unsupported-hit-policy.dmn`](../dmn/examples/refusals/unsupported-hit-policy.dmn) |
| `unsupported-expression` | a cell outside S-FEEL, or a literal whose type contradicts the declared `valueKind`, or (given value kinds) a bare number tested against a `money` column | [`non-sfeel-cell.dmn`](../dmn/examples/refusals/non-sfeel-cell.dmn), [`money-vs-number.dmn`](../dmn/examples/refusals/money-vs-number.dmn) |
| `missing-citation` | a row with no `duly:citation` | [`uncited-row.dmn`](../dmn/examples/refusals/uncited-row.dmn) |
| `missing-effective-date` | a row with no `duly:effectiveFrom`, or a non-ISO date | [`undated-row.dmn`](../dmn/examples/refusals/undated-row.dmn) |
| `missing-rule-id` | a row with no `duly:ruleId` | — |
| `unprovable-unique` | `UNIQUE` rows whose disjointness the kernel cannot prove | [`unprovable-unique.dmn`](../dmn/examples/refusals/unprovable-unique.dmn) |
| `unsupported-table-shape` | more or fewer than one output column, or a table with no rows | [`multiple-outputs.dmn`](../dmn/examples/refusals/multiple-outputs.dmn) |
| `binding-error` | a column label that is not a duly identifier, is reserved, collides with the entity variable, or duplicates another column | — |

**One refusal needs help, and it is the only one that does.** Every class above is raised from the DMN document alone. A bare number tested against a money column is not: `> 200` on `trid:actualAmountAtClosing` is valid S-FEEL, renders to valid duly source (`actual > 200`), and produces a pack `validate_pack` **accepts**, because the rule IR does not type-check expressions at load time. It fails at adjudication, on the first real fact, with `cannot compare money with decimal` — silent until production, which is the failure mode this compiler exists to avoid.

The compiler cannot see it unaided: DMN's `typeRef` is the author's own declaration and duly's value kinds are not DMN's, so nothing in the document says that attribute is money. So `compile_definitions` takes an optional attribute-CURIE → value-kind mapping, which `python -m duly_dmn compile --ontologies DIR` builds from the ontologies the pack pins. Given it, the cell is refused by name; without it, the compiler says nothing rather than guessing — the same posture as ontology conformance being optional at the envelope seam.

The fix is never to quote the amount: duly has no money literal on purpose ([rule-ir.md](rule-ir.md), "A threshold is a rule, not a number in a guard"). Give the threshold its own table concluding a `money` value and compare against that column, which makes it cited and effective-dated as well.

## Equivalence, exactly

[`dmn/examples/trid-fee-tolerance.dmn`](../dmn/examples/trid-fee-tolerance.dmn) is the three rules of [`rulepacks/trid-fee-tolerance-us-federal/pack.yaml`](../rulepacks/trid-fee-tolerance-us-federal/pack.yaml) re-authored as two decision tables. [`dmn/tests/test_equivalence.py`](../dmn/tests/test_equivalence.py) adjudicates the committed [`starters/trid/facts`](../starters/trid/facts) with both packs and asserts they agree on:

- the decision value,
- `rulesFired` — the ids, **their order on the receipt**, each rule's citation and effective window, and each rule's `defeated` list,
- `inputFacts` — id and content hash,
- the pack's own [`expected.yaml`](../rulepacks/trid-fee-tolerance-us-federal/expected.yaml) cases, run against the compiled pack,
- and the off-effective-date behaviour: on 2015-10-02 both packs raise the *same* `AdjudicationError`.

The two receipts differ in exactly two places, and the test asserts the difference as precisely as it asserts the agreement:

- **`rulesFired[].priority`.** Compiled priorities are derived from hit policy and row order (M2); the hand-written pack's are its author's. Priority is a tiebreak *mechanism*; the outcome of the tiebreak is what is asserted.
- **`rulePack.name` / `rulePack.version`**, and therefore `receiptSha256`. Two packs, two identities. Making them collide would be a lie about provenance — and the point of a compiled pack is that a receipt can say where it came from.

**Byte-identical receipts across the two packs are therefore impossible by construction.** That is the honest result, and it is stated here rather than engineered around: a `duly:priority` annotation column would let an author force the numbers to match, and would do it by hollowing out the hit-policy mapping into decoration.

### What this equivalence does *not* prove

It is equivalence **over the committed fixtures**, not equivalence of the rules. The distinction is not academic, and it was measured rather than assumed. Perturbing the DMN source from `> disclosed` to `>= disclosed` — a genuine semantic change — and recompiling leaves the whole equivalence suite green, because the two differ only when the actual and disclosed amounts are exactly equal, and no committed fixture hits that boundary. A perturbation the fixtures *can* see (retyping one input cell from `"TransferTax"` to `"RecordingFee"`) fails 10 of the 12 tests, so the suite is not inert — it is fixture-bounded.

Two consequences worth stating plainly. A compiler bug confined to a boundary the fixtures miss would ship green. And `test_the_committed_compilation_is_what_the_dmn_compiles_to` is doing more work than it appears to: it is the only assertion that catches a source change whose effect the fixtures cannot observe, which is why the compiled pack is committed as an artifact rather than built on the fly.

**This is now closed, and closing it corrected the diagnosis above.** `python -m duly_assurance prove-equivalent` ([spec/pack-verification.md](pack-verification.md)) proves equivalence over the *input space* rather than a fixture list, at two levels: whether the two packs conclude the same value, and whether the same rules apply, the same rule wins, and the same defeat relation is recorded. Run against the hand-written TRID pack and `trid-fee-tolerance.pack.yaml`, both come back proved.

Run against the `>= disclosed` perturbation, the *trace* level fails and the *decision* level does not — and the decision level is right. With the two amounts exactly equal, the cure rule concludes `actual - disclosed`, which is the same `0.00` the default rule concludes. Both packs answer `0.00`; what differs is that `TRID-ZT-01` fires and defeats `TRID-DEF-00` instead of `TRID-DEF-00` standing unopposed. So the perturbation is a genuine semantic change to the **receipt**, not to the answer — the sentence above calling it "a genuine semantic change" is right, and imprecise about which semantics. Distinguishing those two is the whole thesis of this project, which is why the verifier reports both levels instead of collapsing them.

Two things above remain true. The suite is still fixture-bounded, so a compiler bug confined to a boundary the fixtures miss still ships green *in that suite* — `prove-equivalent` is a separate, manually-run check, not a replacement for it. And `test_the_committed_compilation_is_what_the_dmn_compiles_to` is still doing the heavy lifting for source changes the fixtures cannot observe, which is still why the compiled pack is committed as an artifact.

## What this deliberately does not do

- **Round-trip.** There is no `pack.yaml` → DMN direction, and no plan for one. The DMN file is the authored artifact and the pack is its compilation; a second authoring direction would create two sources of truth for one rulebase and an inevitable question about which one the receipt describes.
- **Execute DMN.** This is a compiler, not a DMN engine. Cells never evaluate at compile time; the kernel is the only thing that decides anything.
- **Calendar arithmetic.** `add_business_days` needs a pack-level `calendars:` block (rule-ir.md, "Calendars") and a quoted calendar name. A decision table has nowhere to put a holiday list, and a cell that invoked a calendar function would reference a calendar the DMN cannot declare. A pack needing business-day arithmetic is hand-written today.
- **Abstention policy.** `abstentionPolicy` is pack-level, versioned, and changes receipts. No DMN element corresponds to it and inventing one would put a floor in a table where nobody would look for it.
- **Multi-entity rules.** rule-ir.md open question 1. DMN's `COLLECT` and `every`/`some` are exactly what an author reaches for here, and all three are refused for the same underlying reason.
- **Wire the compiled pack into the demo, the golden corpus, or `rulepacks/`.** [`dmn/examples/trid-fee-tolerance.pack.yaml`](../dmn/examples/trid-fee-tolerance.pack.yaml) is a committed build artifact proving the compiler works, not a seventh rule pack. It duplicates rules that already ship; adding it to `rulepacks/` would double-count them in every corpus and impact number. An adopter compiling their own DMN writes it to `rulepacks/<name>/pack.yaml` and follows [rulepacks/README.md](../rulepacks/README.md) from step 2 — `expected.yaml` and a generator template are still theirs to write, and `python -m duly_dmn verify` is what keeps the committed pack and its `.dmn` from drifting apart.

## Open questions (v0)

1. ~~**Should a compiled pack record its provenance on the receipt?**~~ **Decided: no, and no field ever will.** The receipt schema is closed and has no extension point — [compatibility.md](compatibility.md) C2 states it normatively, with `rulePack.compiledFrom` as one of the three named candidates. There is no additive change to a document whose hash covers its whole body, and compiled-from provenance is producer-asserted metadata that a verifier would re-derive rather than trust. It lives in the pack, which already carries it as an emitted comment, and in a separately-hashed sidecar if it must be machine-readable. The backend-identity question it was waiting on is answered in the same document (C4): agreement between two evaluations is equality of `decision_digest()`, not of bytes.
2. **Should interval disjointness become a pack-validator proof?** `[0..10]` versus `> 10` is provably disjoint and the validator cannot see it (M6). Deciding yes is a rule-IR change that would relax `UNIQUE` compilation for free; deciding no keeps the validator's proof set small enough to audit by reading.
3. **Is `label` the right binding name, or should `given` names come from the CURIE always?** `label` is what the reviewer sees, but it is also user-editable in modellers, so renaming a column changes compiled expression text (not decisions) and therefore the pack's bytes. A CURIE-derived name would be stable and uglier.
4. **DMN's `inputValues` constraints are currently ignored.** They are a validation hint, not a condition, so ignoring them changes no decision — but a table that declares `inputValues` for a column and a cell outside it is arguably self-contradictory, and a compiler that says nothing is not helping.
