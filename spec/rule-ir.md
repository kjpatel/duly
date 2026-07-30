# Rule IR — v0 draft

The rule intermediate representation (IR) is the neutral middle format for rules: authoring surfaces (YAML today, DMN later) compile into it; evaluation backends (the reference interpreter today, Soufflé/clingo later) execute it. Rule packs are written against the IR, never against an engine.

This v0 uses YAML directly as the IR serialization. One file per pack.

## Pack file layout

```yaml
pack:
  name: termination-notice-us-states
  version: "2026.2.0"
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

rules:
  - id: NC-DEF-00
    ...
```

## Rule fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable identifier, unique within the pack (e.g. `NY-NR-45`). |
| `version` | yes | Semver of this rule. |
| `priority` | yes | Integer; used for conflict resolution (higher wins). Defaults/presumptions sit low (0), specific rules higher. |
| `citation` | yes | `{text, url?}` — legal source. Defaults may cite `"Default presumption"`. |
| `description` | no | One plain-English sentence stating what the rule holds. Used verbatim by report renderers; write it for a compliance reader. |
| `effectiveFrom` / `effectiveTo` | from: yes | ISO dates. The rule participates only when `asOf.effective` falls in `[effectiveFrom, effectiveTo)`. Omitted `effectiveTo` = open-ended. |
| `given` | yes | Variable bindings (see below). |
| `when` | no | List of boolean expressions, ANDed. Omitted/empty = always true (this is how default rules work). |
| `then` | yes | The conclusion: `{entity: <var>, attribute: <CURIE>, value: <literal or expr>}`. |
| `overrides` | no | List of rule ids this rule defeats when it fires. |

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

`then.value` is either a literal fact value (`{kind: boolean, value: false}`) or a computed one (`{kind: money, currency: USD, expr: "actual - disclosed"}`).

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

## Receipt mapping

The interpreter emits a `DecisionReceipt` per `spec/schemas/decision-receipt.schema.json`:

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

1. Multi-entity binding (two fees on one loan) — v0 restricts to one entity per type; the TRID pack works around it with one fee entity per case. Real fix is quantified bindings in v1.
2. Should `overrides` be allowed across packs? v0: no — packs are self-contained.
3. Negation-as-absence (`no fact asserted for attribute X`) — deferred; default rules cover the demo cases.
