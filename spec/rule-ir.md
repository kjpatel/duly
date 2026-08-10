# Rule IR — v0 draft

The rule intermediate representation (IR) is the neutral middle format for rules: authoring surfaces (YAML today, DMN later) compile into it; evaluation backends (the reference interpreter today, Soufflé/clingo later) execute it. Rule packs are written against the IR, never against an engine.

This v0 uses YAML directly as the IR serialization. One file per pack.

## Pack file layout

```yaml
pack:
  name: termination-notice-us-states
  version: "2026.2.0"
  idPrefix: NC          # optional; the rule-id family this pack mints (see "Rule ids")
  ontology: duly-starter-notice
  ontologyVersion: "0.1.0"
  description: State-by-state cancellation/nonrenewal notice compliance.

abstentionPolicy:     # optional; confidence floors for machine-asserted facts (see below)
  minConfidence: 0.75
  attributes:
    nc:noticeMailedDate: 0.9

calendars:            # optional; named business-day calendars for date arithmetic (see "Calendars")
  tila-precise:
    excludedWeekdays: [Sunday]
    coverage: { from: "2026-01-01", to: "2028-01-01" }
    holidays: ["2026-05-25", "2026-07-04"]

decisions:            # the questions this pack can answer (consumed by UIs)
  - attribute: nc:noticeCompliant
    entityType: nc:TerminationNotice
    question: "Was this termination notice compliant?"
    phrasing:         # optional; how the answer is worded (see "Decision phrasing")
      - when: { value: false }
        verdict: "Not compliant"
        tone: neg

rules:
  - id: NC-DEF-00
    ...
```

## Rule fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable identifier, unique within the pack (e.g. `RESC-FUND-STAY`). Follows the convention below; **never** renamed. |
| `version` | yes | Semver of this rule. |
| `priority` | yes | Integer; used for conflict resolution (higher wins). Defaults/presumptions sit low (0), specific rules higher. |
| `citation` | yes | `{text, url?}` — legal source. Defaults may cite `"Default presumption"`. |
| `description` | no | One plain-English sentence stating what the rule holds. Used verbatim by report renderers; write it for a compliance reader. |
| `effectiveFrom` / `effectiveTo` | from: yes | ISO dates. The rule participates only when `asOf.effective` falls in `[effectiveFrom, effectiveTo)`. Omitted `effectiveTo` = open-ended. |
| `given` | yes | Variable bindings (see below). |
| `when` | no | List of boolean expressions, ANDed. Omitted/empty = always true (this is how default rules work). |
| `then` | yes | The conclusion: `{entity: <var>, attribute: <CURIE>, value: <literal or expr>}`. |
| `overrides` | no | List of rule ids this rule defeats when it fires. |

## Rule ids

```
<PREFIX>-<TOPIC>[-<QUALIFIER>…][-NN]        RESC-FUND-STAY, PKG-NOTE-31, NC-NY-NONRENEWAL-01
```

Uppercase letters and hyphens, with an optional **trailing two-digit sequence number** that means nothing except "the next id in this family". A pack declares its family once as `pack.idPrefix`; every id it mints starts with it.

**A rule id is a handle, not a claim.** This is the whole argument. Everything an id is tempted to encode already has a home on the rule — the statute is in `citation`, the date is in `effectiveFrom`, the threshold is in `then.value`, the jurisdiction is in the `when` guard — and an id that repeats one of them becomes *false* when that field changes. The difference is that the field can be corrected and the id cannot: ids are inside `rulesFired` on every receipt that cited them, and receipts are content-addressed and immutable by construction. `NY-NR-45` names New York's 45-day nonrenewal notice; the day the legislature moves to 60, the pack gets a new effective-dated rule and the old id goes on saying 45 in 76 committed receipts, forever. There is no cheap fix, which is why the rule is *don't*, not *rename it later*.

Three parts are machine-checked by `validate_pack`, and the rest is style left to review — the split is deliberate, because a check that pretends to more certainty than it has is the failure mode this repo spends most of its effort avoiding:

| Checked | What it rejects | What it cannot see |
|---|---|---|
| No digits outside the trailing `NN` | `TX-RON-2018` (a year), `CA-DTT-11933` (a statute section), `CA-SB2-75` (a bill number), `NY-NR-45-LEGACY` (digits mid-id) | — |
| `NN` must not equal a number in the rule's own `when` or `then.value` | `NY-NR-45` concluding 45 days; `CA-NR-75` concluding 75 | a semantic number the body never mentions — `CA-TOPSPACE-25` for 2.5 inches passes, because `25 ≠ 2.5` |
| Every id starts with `pack.idPrefix` | a second scheme growing inside one pack | nothing, when the pack declares no prefix |

`NN = 00` is exempt from the echo check: `-00` is the default-rule slot repo-wide and a default very often concludes zero, so the coincidence carries no claim.

**Opting in.** The checks run only for packs that declare `pack.idPrefix` — declaring one *is* the opt-in. Every pack in this repo declares one, and `examples/tests/test_example_rule_ids.py` fails if a new one does not. An adopter porting a rulebase whose ids are already in their own receipts is not forced to rename what this section argues cannot be renamed; they leave `idPrefix` off, or adopt the convention for new packs only.

**Grandfathering.** The 46 rule ids committed before this convention existed are exempt, listed by pack in [`kernel/duly_kernel/rule_ids.py`](../kernel/duly_kernel/rule_ids.py) — an explicit list, not a date cutoff or a heuristic, so the exemption is finite and countable. 17 of the 46 would fail the convention today: five jurisdiction-first county ids, five year-suffixed RON ids, and seven notice ids carrying day counts. `examples/tests/test_example_rule_ids.py` pins both numbers and asserts that every non-conforming committed id is on the list, so the list can only grow in a diff that says so.

**Rejected:**

- *Renaming the offenders.* `NY-NR-45` appears in 76 golden receipts. Renaming would rewrite the audit chain to make the repo look tidier — precisely the mutation the content-addressing invariant exists to prevent. The convention is forward-looking or it is nothing.
- *Deriving ids from row or file position* (`PACK-03`). Inserting a rule above would silently re-label history; the same objection `spec/dmn.md` gives for requiring an authored `duly:ruleId`.
- *Jurisdiction-first ids* (`NY-NR-01`). A jurisdiction-first id claims the jurisdiction is the rule's primary key, but the pack is the unit of versioning and the receipt already pins `rulePack.name`; meanwhile rules that span jurisdictions (`RON-COMP-01`) have nowhere to sit. Jurisdiction belongs in a `TOPIC` segment: `NC-NY-NONRENEWAL-01`.
- *A global id registry across packs.* Ids need to be unique within a pack, because a receipt cites `rulePack` and `rulesFired` together. Cross-pack uniqueness would need coordination no adopter can join.

## `given` — variable bindings

Each entry binds a name usable in `when` / `then`:

```yaml
given:
  mailed:   { attribute: nc:noticeMailedDate }        # value of the asserted fact with this attribute
  minDays:  { derived: nc:requiredMinimumNoticeDays } # value concluded by another rule in this run
  notice:   { entityType: nc:TerminationNotice }      # the entity id itself (for use in then.entity)
  today:    { asOf: effective }                       # the evaluation date itself (see below)
```

**The `asOf` binding** binds the calendar date (UTC) of the run's `asOf.effective` point as a `date` value, so a rule can compare a computed date against "now as evaluated" — e.g. a funding rule that holds until a computed deadline passes: `today > deadline`. `effective` is the only dial exposed in v0 (`knowledge` says what was *known*, not what was *true*; no rule semantics need it yet). The binding always resolves, records **no premise** on the receipt — the receipt's top-level `asOf` already pins the value — and is exactly as replayable as everything else: same `asOf`, same answer.

**Rejected:** *a `now()` expression function.* A function call looks like it might read a clock; a binding makes the data flow visible in `given`, where every other input to the rule is declared. There is deliberately no wall-clock anything — the value comes from the caller-supplied evaluation point, never the machine.

Resolution semantics (v0 simplifications, deliberate):

- At most **one entity per entityType** and **one live fact per attribute** per case. Two live facts asserting the same attribute is a *conflict*: the run records an abstention with reason `conflict` and rules needing that binding are inapplicable.
- A rule is **applicable** iff every `given` binding resolves and every `when` expression is true and the rule is effective at `asOf.effective`. An unresolvable binding makes the rule silently inapplicable (it is not an error — most rules in a pack won't apply to most cases).
- `derived` bindings create rule dependencies. Evaluation runs to a fixpoint in dependency order; cycles are a pack-validation error.

## Expression language

Small, typed, deterministic. Used in `when` items and `then.value.expr`.

- Literals: integers and decimals (`45`, `0.1`), strings in double quotes (`"US-NY"`), `true`, `false`, dates via `date("2026-09-01")`.
- Operators: `+ - * /`, comparisons `== != < <= > >=`, boolean `and or not`, parentheses.
- Functions: `days_between(a, b)` → decimal days from date a to date b; `abs(x)`, `min(a,b)`, `max(a,b)`; `add_business_days(d, n, "cal")` → the `n`-th business day after date `d` under the pack calendar named `"cal"` (see "Calendars" below).
- Typing follows fact value kinds: `date`, `decimal`, `money`, `boolean`, `string`, `code`. Money arithmetic requires matching currencies (`money - money → money`; `money * decimal → money`). Comparing a `code` var to a string compares the code's `value` field. No implicit conversions; type errors fail the run loudly.
- **There is no money literal.** `amount > 200.00 USD` does not parse and `amount > 200` is a type error, because money is an amount *and* a currency and a bare number is only the first. A money threshold is concluded by its own rule and bound with `derived:` — see below.

`then.value` is either a literal fact value (`{kind: boolean, value: false}`) or a computed one (`{kind: money, currency: USD, expr: "actual - disclosed"}`).

### A threshold is a rule, not a number in a guard

The missing money literal is a constraint on one value kind, but the pattern it forces is the one every committed pack already follows for *all* of them: no `when:` guard in this repository contains an inline numeric literal. Thresholds are concluded by a rule and compared as bound values.

```yaml
# the constant, with its own citation and effective window
- id: EXP-LIMIT-00
  citation: { text: "Acme Expense Policy §4.2" }
  effectiveFrom: "2026-01-01"
  then: { entity: claim, attribute: ex:unapprovedSpendLimit,
          value: { kind: money, amount: "200.00", currency: "USD" } }

# the rule that measures against it
- id: EXP-TRAVELCAP-01
  given:
    amount: { attribute: ex:amount }
    limit:  { derived: ex:unapprovedSpendLimit }   # <- bound, not written inline
  when: [ "amount > limit" ]
```

Three things this buys, none of which are available to an inline literal. The threshold **carries its own citation**, so a reader can check the number against its authority. It is **independently effective-dated**: when the limit rises, you add one rule with a new `effectiveFrom` and the rule that compares against it never changes — inline, you would clone the whole exception and close the old one's window. And it **appears in the receipt's derivation**, so whoever reads the decision sees which limit applied without opening the pack.

Worked end to end in [examples/minimal-integration](../examples/minimal-integration/). The kernel's type error names this idiom directly, and — given the pinned ontology's value kinds — the [DMN compiler](dmn.md) refuses a decision-table cell that compares a money column to a bare number, because that cell compiles cleanly and then fails at adjudication.

## Calendars

A pack that does business-day arithmetic carries its calendar as **pack-embedded data**:

```yaml
calendars:
  tila-precise:                    # referenced by name from expressions
    description: >-
      12 CFR 1026.2(a)(6) precise business days: Sundays and 5 U.S.C.
      6103(a) holidays out; Saturdays count.
    excludedWeekdays: [Sunday]     # weekday names, Monday..Sunday
    coverage: { from: "2026-01-01", to: "2028-01-01" }   # [from, to)
    holidays:                      # explicit DATES, with source comments
      - "2026-05-25"  # Memorial Day (last Monday in May)
      - "2026-07-04"  # Independence Day (Saturday — no observance shift)
      # ...
```

`add_business_days(d, n, "tila-precise")` steps forward from `d` one calendar day at a time, counting every day whose weekday is not in `excludedWeekdays` and whose date is not in `holidays`; the `n`-th counted day is the result. `d` itself never counts ("following" semantics), `n = 0` returns `d`, and negative or fractional `n` is a type error. **The function hardcodes no convention** — whether Saturdays count, which holidays exist, and whether observed-holiday shifting applies are entirely the calendar's data. The calendar name must be a quoted string literal naming a declared calendar; pack validation checks this statically (unknown calendar, non-literal name, or wrong arity is a `PackValidationError`), and validation also checks the block itself (weekday names, ISO dates, holidays inside coverage).

**Coverage is a hard boundary, not a hint.** Every day the walk examines — start date included — must fall inside the half-open `coverage` window. A computation that touches an uncovered day fails the run loudly (`ExprCalendarError`) rather than silently treating an unlisted holiday as a business day: a calendar that only lists 2026's holidays must not quietly compute wrong answers for 2031. Extending coverage means adding dates and bumping the pack version.

**Why pack-embedded:** everything that can change a decision must be versioned with the rulebase (the same argument as abstention floors). The calendar is inside the pack file, so it is inside `rulePack.version` on every receipt, replays byte-for-byte forever, and needs no new registry machinery, no external artifact, and no fetch at evaluation time. The accepted trade: two packs using the same jurisdiction's calendar duplicate the dates. A shared *versioned* calendar registry (referenced by name + version, pinned on the receipt like `schemaRef` pins ontologies) is the future-work shape when duplication starts to hurt; the block syntax was chosen so packs can migrate mechanically.

**Rejected:**

- *Computing holidays from formulas in the kernel* (e.g. "last Monday in May"). The formula set is jurisdiction- and era-specific (Juneteenth exists only from 2021; observance shifting applies to some regimes and expressly not to others) — encoding it in engine code makes legal content invisible to `rulePack.version`. Dates-as-data with source comments keep the legal claim reviewable where the rules are reviewed.
- *Engine or deployment calendar configuration.* Same objection as engine-config abstention floors: two byte-identical replays could disagree because an ops file changed.
- *Silently clamping or wrapping out-of-coverage walks.* A wrong deadline with a plausible shape is the worst failure mode this system exists to prevent; the loud error is the feature.

## Defeasibility semantics

Two mechanisms, both recorded on the receipt:

1. **`overrides`** (explicit exceptions): if rule R is applicable and fires, every rule listed in `R.overrides` has its conclusions suppressed for this run, and R's receipt entry records `defeated: [those ids]`. This is the default-and-exception pattern: `NC-DEF-00` presumes compliance; `NC-NR-01` overrides it when the notice-period arithmetic fails.
2. **Priority** (conflict tiebreak): if two applicable rules conclude the *same attribute for the same entity* and neither overrides the other, the higher `priority` wins and the receipt records the loser as defeated. Equal priority on a same-attribute conflict is a pack-validation error — packs must be unambiguous. Exceptions, where the validator can *prove* the rules never both apply: disjoint effective windows (rule versioning), or contradictory equality guards on the same bound attribute (jurisdiction scoping — `state == "US-NY"` vs `state == "US-FL"`).

## Abstention policy

A pack may declare confidence floors for machine-asserted facts:

```yaml
abstentionPolicy:        # optional; absent = no confidence filtering
  minConfidence: 0.75    # required when the block is present: the default floor
  attributes:            # optional per-attribute overrides (CURIE -> floor)
    nc:noticeMailedDate: 0.9
  routeTo: notice-review # optional; the review queue abstentions route to (see "Routing")
```

Semantics, applied by the kernel at fact-binding time (before conflict detection, so an excluded fact neither binds nor conflicts):

- A machine-asserted fact participates only if `confidence.score >= floor`, where the floor is the attribute's override when one exists, else `minConfidence`. A fact **at** the floor binds; abstention is strictly `score < floor`.
- An excluded fact is invisible to bindings — rules needing that attribute are silently inapplicable, exactly as if the fact were missing — and the run records an abstention entry with reason `low_confidence` (shape below).
- **Human-asserted facts** (`assertion.kind == "human"`) are never confidence-filtered. Calibrated confidence is a property of extractors; a reviewer's attestation is the correction channel the policy routes *to*, so filtering it would deadlock the review loop.
- A machine-asserted fact carrying **no `confidence` field fails closed** under an active policy: it is excluded, and the entry says so in `details`. The contract calls confidence "required in practice for machine assertions"; a pack that opts into confidence floors must not be bypassable by omitting the score. Packs without a policy accept such facts unchanged (v0 behavior).
- The filter's scope is the **case, not the question**: it runs over the case's whole live-fact projection before evaluation, so a run's entries are identical whichever of the pack's decisions is adjudicated, and a receipt may carry a `low_confidence` entry for an attribute none of that decision's rules consult. The entry records what was excluded from the evaluation's fact universe, not which rules would have bound the fact.

The policy is part of the pack and versioned with it: changing a floor is a pack version bump, so a decision replayed under the old pack version reproduces the old outcome — the same discipline as changing a rule.

**Receipt entry** (extends the `abstentions` list additively; `conflict` entries are unchanged):

```json
{
  "entity": "notice:HO-77401-NY:2026-07-25",
  "attribute": "nc:noticeMailedDate",
  "reason": "low_confidence",
  "facts": ["urn:duly:fact:sha256:…"],
  "confidence": { "score": 0.85, "method": "platt" },
  "threshold": {
    "minConfidence": 0.9,
    "source": "attribute",
    "pack": "termination-notice-us-states",
    "packVersion": "2026.3.0"
  }
}
```

`threshold.source` is `attribute` (an override applied) or `default`; `pack`/`packVersion` pin where the floor came from, so the entry routes and audits without the pack file in hand. `confidence` echoes the excluded fact's score and method; it is absent (and `details` explains) when the fact carried no confidence.

### Routing

The policy block may declare an optional `routeTo`: a plain string naming the review queue (or actor) this pack's abstentions go to. When present, the kernel copies it verbatim into **every** abstention entry the run emits — `low_confidence` exclusions and `conflict` entries alike — as the entry's `routedTo` field (already allowed by the receipt schema). Routing says where an abstention goes, not why it happened, so one destination covers both reasons; a pack that wants routed conflicts but no confidence filtering can declare `minConfidence: 0`.

**Why on the pack, decided at adjudication time:** receipts are content-hashed and immutable, so anything that appears on the receipt must be known when the kernel runs. The pack is the only versioned artifact in hand at that moment, and routing is adjudication policy in exactly the sense the floors are — changing where abstentions go is a pack version bump that replays. `routeTo` is deliberately just a name, not an endpoint: the receipt records *which* queue was responsible; how that queue is hosted is deployment configuration, which must never leak into receipt bytes.

**Backward compatibility:** `routeTo` is optional and additive. A pack without it — including every pack that predates the field — produces byte-identical receipts to the pre-routing kernel; a pack with no `abstentionPolicy` at all leaves conflict entries unrouted too. Consumers (the review queue's `enqueue_receipt`) accept unrouted entries, so routing is a labeling convenience, not a gate.

**Rejected:**

- *Routing decided by the review queue at enqueue time (not on the receipt).* Workable — and still supported, since `routedTo` is optional — but then the receipt cannot answer "who was responsible for this abstention?", which is an audit question, not an ops question.
- *Deployment-level routing tables.* Same objection as engine-config floors: invisible to `rulePack.version`, so two byte-identical replays could have routed differently with no trace.
- *Per-attribute routing.* No consumer yet; the per-attribute `attributes` map shows how it would be added additively if one appears.

**Why pack-level, and why here:** abstention is policy, not data (grounded-facts D5) — the fact never carries an abstained flag, and the same fact may clear one pack's floor and not another's. The pack is the only artifact that is already versioned, effective-dated at selection time, and pinned on every receipt, so floors that live in the pack are floors that replay.

**Rejected:**

- *Engine or deployment configuration.* A floor outside the pack is invisible to `rulePack.version` on the receipt: two byte-identical replays could disagree because an ops setting changed. Everything that can change a decision must be versioned with the rulebase.
- *Per-rule thresholds.* Floors express trust in extraction per attribute, not per rule; per-rule floors would let two rules in one run disagree about whether the same fact participated, making "which facts were consumed" ill-defined on the receipt.
- *Per-decision thresholds.* D5 anticipates a fact clearing the floor for one decision and not another, but that granularity belongs with the calibration module (M3), which will know per-decision error targets. The v0 shape is forward-compatible: a decision-scoped block can be added additively.
- *Method-aware floors* (e.g. a floor that only trusts `conformal` scores). Deferred with calibration; `confidence.method` is already on the fact and echoed on the entry, so nothing is lost by waiting.

## Decision phrasing

A decision already carries the human `question` a UI asks. It may also carry the phrasing of the **answer**:

```yaml
decisions:
  - attribute: trid:toleranceCureAmount
    entityType: trid:Fee
    question: "Does this fee increase require a tolerance cure?"
    phrasing:                            # optional; first matching case wins
      - when: { amount: positive }
        verdict: "Cure required"         # the headline
        detail: "{money} tolerance cure" # one supporting clause, no terminal period
        tone: warn                       # pos | neg | warn | "" (default "")
      - verdict: "No cure required"
        detail: "{money}"
        tone: pos
```

**Why in the pack.** A decision value is a CURIE-attributed code, date, or money amount; turning it into a sentence takes domain knowledge — that a positive cure amount is a warning and a zero one is not, that a rescission right is a hold on the file rather than good news. That knowledge lives with the rules, and it belongs to whoever wrote them. Before this block, a pack that concluded a new non-boolean attribute rendered as a raw `attribute = value` string until someone edited the demo's `_determination()`, which meant every new pack had a mandatory core-code change hidden in a directory pack authors never open. Phrasing in the pack removes the last such change.

**One renderer, for every surface.** `duly_kernel.phrasing.determination(receipt, facts, pack)` resolves a decision's wording, and it is the only thing that does: the demo's answer line and the audit report's headline verdict are two callers of one function. Putting the renderer beside the validator (`duly_kernel.ir`, which rejects an unknown placeholder or guard where the pack loads) is what makes that possible — a renderer in a UI package can only be reached by the UI. The alternative is not hypothetical: while phrasing lived in the demo, the report renderer had a heuristic of its own — any boolean attribute whose local name contained "compliant" was rendered "Compliant"/"Not compliant" — so the same decision came out worded one way in the browser and another way in the PDF an examiner reads, and the pack's own wording lost to a guess about an attribute name. Phrasing being *presentation* is why it may live anywhere; it does not follow that it may live in several places.

**Cases.** `phrasing` is an ordered list; the first case whose `when` guards all hold supplies the wording. Guards (all optional, all ANDed):

| Guard | Holds when |
|---|---|
| `value: true` / `value: false` | the decision value is that boolean |
| `value: ZeroTolerance` | the decision value's `value` equals that literal (codes, strings) |
| `amount: positive` / `nonPositive` | the decision's money amount is / is not `> 0` |
| `abstained: lowConfidence` / `none` | the run did / did not exclude a fact below the confidence floor |
| `fact: {attribute: X, equals: Y}` | the case asserts a fact for `X` whose value is `Y`; `equals: "{value}"` compares it to the decision value |
| `fact: {attribute: X, present: true}` | a fact for `X` exists at all |

**Templates.** `verdict` and `detail` are strings, or a **list of alternatives** — the first whose every placeholder resolves is used, which is how a pack says "phrase it this way when the inputs are there, that way when they are not":

```yaml
detail:
  - "{daysBetween:noticeMailedDate,policyExpirationDate} days notice given, {derived:requiredMinimumNoticeDays|int} required"
  - "No applicable rule found the notice deficient"
```

Placeholders: `{value}` (the decision value), `{money}` (amount and currency), `{caveat}` (the "presumption only — … excluded below the confidence floor" sentence, unresolvable when nothing was excluded), `{fact:<attribute>}`, `{derived:<attribute>}` (a value concluded by another rule in the same run), `{daysBetween:<from>,<to>}`. Formats: `|day` (an ISO date's day part), `|int`. `validate_pack` rejects an unknown placeholder, an unknown format, an unknown guard, or a tone outside the four values — so a typo fails where the pack is loaded, not in a UI test.

**Fallback, and why it stays — and why it belongs to the renderer.** A decision with no matching case — or no `phrasing` at all — is not an error. `determination()` returns nothing, and each surface words the gap in its own idiom: the demo renders a boolean Yes/No (so a simple pack declares nothing at all) and flags anything else `generic`, showing `attribute = value`; the audit report names the attribute it is reporting on (`permitted: no`, `250.00 USD`), because a document with a masthead cannot answer "Yes". That split is deliberate. A shared renderer that also chose the fallback would be publishing wording no pack author wrote, in every medium at once — which is the defect this block exists to remove, reintroduced one level up. Honest degradation is the point: an unphrased code should look unphrased.

**Presentation only.** Phrasing never enters a receipt, a fact, an envelope, or any hashed body — it is read by a renderer from the pack the caller already has. This is not a style preference: fact and receipt hashes are SHA-256 over canonical JSON of the whole body, so a wording key added in place would change every hash and break replay. Wording must therefore be free to improve; a decision's *meaning* is `decision.value`, which is hashed, and only that.

**Rejected:**

- *Phrasing in the UI* (the status quo ante). It made every pack a two-repository change, put legal wording in the one place lawyers do not review, and — the part that only showed up later — left every non-UI renderer to invent its own wording, which the audit report duly did.
- *A general expression language for phrasing.* The guard and placeholder vocabularies are closed and small on purpose. The pack already has a real expression language for things that change the answer; a second one for things that change the sentence would be a second thing to verify, with none of the same stakes.
- *Localization (`phrasing.en`, `phrasing.es`).* Additive when a consumer needs it — a language key nests above the case list without touching anything here. Nothing in the repo has a second locale, and inventing one would produce unreviewed legal wording in a language no maintainer reads.

## Receipt mapping

The interpreter emits a `DecisionReceipt` per `duly_core`'s `decision-receipt` schema:

- `rulesFired`: every rule whose conclusion survived, with its `citation`, `priority`, effective window, and `defeated` list.
- `derivation`: built from binding provenance — fact bindings become `{factId}` premises; `derived` bindings become nested derivation nodes.
- `inputFacts`: every fact consumed anywhere in the derivation, pinned by id + contentHash.
- `abstentions`: conflict entries (reason `conflict`) followed by low-confidence exclusions (reason `low_confidence`, see "Abstention policy"), each list internally sorted for determinism.
- `asOf`: echoed from the evaluation request. Facts participate only if their `effectiveFrom/effectiveTo` window (when present) contains `asOf.effective`.

## Complete example — NY nonrenewal pack (matches `spec/examples/`)

```yaml
pack:
  name: termination-notice-us-states
  version: "2026.2.0"
  ontology: duly-starter-notice
  ontologyVersion: "0.1.0"

decisions:
  - attribute: nc:noticeCompliant
    entityType: nc:TerminationNotice
    question: "Was this termination notice compliant?"

rules:
  - id: NC-DEF-00
    version: "1.0.0"
    priority: 0
    citation: { text: "Default presumption" }
    effectiveFrom: "1900-01-01"
    given:
      notice: { entityType: nc:TerminationNotice }
    then:
      entity: notice
      attribute: nc:noticeCompliant
      value: { kind: boolean, value: true }

  - id: NY-NR-45
    version: "1.1.0"
    priority: 100
    citation:
      text: "N.Y. Ins. Law § 3425(d)(1)"
      url: "https://www.nysenate.gov/legislation/laws/ISC/3425"
    effectiveFrom: "1986-01-01"
    given:
      notice:     { entityType: nc:TerminationNotice }
      noticeType: { attribute: nc:noticeType }
      state:      { attribute: nc:governingState }
    when:
      - noticeType == "Nonrenewal"
      - state == "US-NY"
    then:
      entity: notice
      attribute: nc:requiredMinimumNoticeDays
      value: { kind: decimal, expr: "45" }

  - id: NC-NR-01
    version: "1.0.2"
    priority: 200
    citation:
      text: "N.Y. Ins. Law § 3425(d)(1)"
      url: "https://www.nysenate.gov/legislation/laws/ISC/3425"
    effectiveFrom: "1986-01-01"
    given:
      notice:     { entityType: nc:TerminationNotice }
      expiration: { attribute: nc:policyExpirationDate }
      mailed:     { attribute: nc:noticeMailedDate }
      minDays:    { derived: nc:requiredMinimumNoticeDays }
    when:
      - days_between(mailed, expiration) < minDays
    then:
      entity: notice
      attribute: nc:noticeCompliant
      value: { kind: boolean, value: false }
    overrides: [NC-DEF-00]
```

Evaluating this pack against the four facts in `spec/examples/` with `asOf.effective = 2026-07-25` must reproduce `spec/examples/receipt-ny-nonrenewal-notice.json`: decision `nc:noticeCompliant = false`, `NY-NR-45` firing on the state and notice-type facts, `NC-NR-01` firing on the two date facts plus the derived minimum, defeating `NC-DEF-00`.

## Resolved in v0

- **Fact effective windows vs. rule-selection date.** "Evaluate under the rules as of date X" and "which facts were true at X" are two different dials, and conflating them breaks replay: evaluating a July notice under December's rules must not filter out the notice facts. v0 resolution: *event assertions* (a notice was mailed, an amount was disclosed) carry **no** effective window — they are timelessly true once made — and the `asOf.effective` dial therefore selects rule versions. Facts that genuinely have bounded truth (a payoff good-through date, a quote validity window) still carry windows and are filtered. A first-class separation of the two dials is v1 work.
- **Versioned rules are not ambiguous.** Two rules concluding the same attribute at the same priority are permitted when their effective windows are disjoint — that is exactly how a rule's history is represented (`NY-NR-45-LEGACY` / `NY-NR-45`). The ambiguity check considers window overlap.

## Open questions (v0)

1. ~~Multi-entity binding (two fees on one loan)~~ — **deferred past v1.0** ([compatibility.md](compatibility.md) C5). The restriction is one entity per `entityType` per case, and v1.0 states it as a boundary rather than promising quantified bindings: no committed pack needs them (the TRID pack's one-fee-entity-per-case workaround is documented at the site), and they were not a change that milestone could absorb — [pack-verification.md](pack-verification.md) open question 6 states the real cost, which is re-establishing the decidable fragment that keeps `prove`'s `PROVED` a proof. What makes deferral safe rather than debt is C3: quantified bindings arrive as a **new semantics version** whose kernel also implements this one, so packs written against v1.0 keep loading, deciding identically, and replaying.
2. Should `overrides` be allowed across packs? v0: no — packs are self-contained.
3. Negation-as-absence (`no fact asserted for attribute X`) — deferred; default rules cover the demo cases.
4. **Should `validate_pack` type-check expressions, and with what?** It does not today: guards are parsed for syntax and typed only when a fact binds. So `amount > 200` against a money attribute loads cleanly, passes every check between authoring and production, and raises `cannot compare money with decimal` on the first real fact. The DMN compiler closes the path that produced this in practice — given the pinned ontology's value kinds it refuses the cell ([dmn.md](dmn.md), "Refusal classes") — but a hand-written pack still reaches adjudication before anything objects.

   The blocking question is *what the checker would check against*. Value kinds live in the ontology, and the kernel deliberately takes facts and a pack and no registry: making the ontology a load-time input would put a second artifact inside the trust boundary of every adjudication and every replay, for a class of error that is loud, immediate, and never silently wrong. Two narrower shapes avoid that and are worth weighing first: infer kinds from the pack's own `then.value` declarations and check only what the pack itself determines (no new input, partial coverage), or keep the check outside the kernel in `prove`, which already resolves the ontology and already reasons about the whole input space (no new kernel surface, opt-in and optional). The third option — accept it, on the grounds that a type error at first adjudication is a fast, unambiguous failure — is the status quo and needs saying out loud rather than defaulting into.

   The stability policy prices this question without answering it. [compatibility.md](compatibility.md) C1 makes the IR a floor rather than a ceiling: later versions may accept more, never less. **A validator that gets stricter is therefore a breaking change**, even though it adds no syntax and fixes a real problem — so answering this *yes* after v1.0 rejects packs that used to load. That may leave the two narrower shapes above, both of which check outside `validate_pack`'s loading path, as the only affordable answers.
