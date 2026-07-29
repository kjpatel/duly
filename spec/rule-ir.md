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
```

Resolution semantics (v0 simplifications, deliberate):

- At most **one entity per entityType** and **one live fact per attribute** per case. Two live facts asserting the same attribute is a *conflict*: the run records an abstention with reason `conflict` and rules needing that binding are inapplicable.
- A rule is **applicable** iff every `given` binding resolves and every `when` expression is true and the rule is effective at `asOf.effective`. An unresolvable binding makes the rule silently inapplicable (it is not an error — most rules in a pack won't apply to most cases).
- `derived` bindings create rule dependencies. Evaluation runs to a fixpoint in dependency order; cycles are a pack-validation error.

## Expression language

Small, typed, deterministic. Used in `when` items and `then.value.expr`.

- Literals: integers and decimals (`45`, `0.1`), strings in double quotes (`"US-NY"`), `true`, `false`, dates via `date("2026-09-01")`.
- Operators: `+ - * /`, comparisons `== != < <= > >=`, boolean `and or not`, parentheses.
- Functions: `days_between(a, b)` → decimal days from date a to date b; `abs(x)`, `min(a,b)`, `max(a,b)`.
- Typing follows fact value kinds: `date`, `decimal`, `money`, `boolean`, `string`, `code`. Money arithmetic requires matching currencies (`money - money → money`; `money * decimal → money`). Comparing a `code` var to a string compares the code's `value` field. No implicit conversions; type errors fail the run loudly.

`then.value` is either a literal fact value (`{kind: boolean, value: false}`) or a computed one (`{kind: money, currency: USD, expr: "actual - disclosed"}`).

## Defeasibility semantics

Two mechanisms, both recorded on the receipt:

1. **`overrides`** (explicit exceptions): if rule R is applicable and fires, every rule listed in `R.overrides` has its conclusions suppressed for this run, and R's receipt entry records `defeated: [those ids]`. This is the default-and-exception pattern: `NC-DEF-00` presumes compliance; `NC-NR-01` overrides it when the notice-period arithmetic fails.
2. **Priority** (conflict tiebreak): if two applicable rules conclude the *same attribute for the same entity* and neither overrides the other, the higher `priority` wins and the receipt records the loser as defeated. Equal priority on a same-attribute conflict is a pack-validation error — packs must be unambiguous.

## Receipt mapping

The interpreter emits a `DecisionReceipt` per `spec/schemas/decision-receipt.schema.json`:

- `rulesFired`: every rule whose conclusion survived, with its `citation`, `priority`, effective window, and `defeated` list.
- `derivation`: built from binding provenance — fact bindings become `{factId}` premises; `derived` bindings become nested derivation nodes.
- `inputFacts`: every fact consumed anywhere in the derivation, pinned by id + contentHash.
- `abstentions`: conflicts and (later) low-confidence exclusions.
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
