# Authoring a rule pack

A rule pack is versioned, cited, effective-dated domain knowledge — the contribution surface where legal and operational expertise matters more than familiarity with the kernel. This guide is the path from "I know a rule" to "the rule is adjudicated, demonstrated, and protected by regression tests."

Read [spec/rule-ir.md](../../spec/rule-ir.md) for what the IR *means*. This document is about the mechanics around it.

## A pack is three things

```
rulepacks/<pack-name>/
  pack.yaml        # metadata, decisions, rules, optional abstentionPolicy
  expected.yaml    # declared adjudication outcomes — the pack's own test suite
  fixtures/<case>/facts/*.json   # optional: fact sets for expected.yaml cases
```

Copy [termination-notice-us-states](termination-notice-us-states/) for a jurisdiction-scoped pack, or [trid-fee-tolerance-us-federal](trid-fee-tolerance-us-federal/) for a two-document computation. Neither is a toy; both are what shipped.

**Paths in this guide are content-root relative, and commands are written to run from the repository root.** A content root is the flat directory holding `rulepacks/`, `starters/`, `golden/`, `ontologies/` and `dmn/` — `examples/` in this repository, yours wherever you keep it (`DULY_DEMO_CONTENT`). So `rulepacks/<name>/expected.yaml` is `examples/rulepacks/<name>/expected.yaml` here, and every command below spells the `examples/` prefix out. The distinction is not pedantry: a golden case's `pack:` and an expected case's `factsFrom:` are resolved against the content root, so a path that quietly acquires this repository's prefix stops resolving in the deployment that copies it.

## Read the packs before you write one

`uv run uvicorn duly_demo.app:app --port 8788`, then <http://localhost:8788/rules>. The **rule studio** renders every committed pack as decision-table grids — rows are rules, columns are the inputs they bind — which is the fastest way to see how a real pack is shaped before you copy one. It also drafts and tests: edit a cell, a rule form or the YAML, and the panel beside it runs the kernel's validator, this pack's `expected.yaml`, an ad-hoc case you build by changing input values, golden-corpus impact analysis, and the solver. Drafts are session-only — the studio hands you `pack.yaml` bytes and a diff and never writes into this directory, so everything below still applies. It is a good place to *understand* and *try*; it is not a shortcut past steps 2–7. Walkthrough: [demo tour §10](../../docs/demo_tour.md#10-the-rule-studio).

## Most wiring is automatic. Three things are not.

This is the part worth internalizing, because it is where contributions silently come up short.

**Automatic** — add the file and it works, no registration anywhere:

| You add | It is picked up by |
|---|---|
| `rulepacks/<name>/expected.yaml` | `examples/tests/test_rulepacks.py`, which globs `rulepacks/*/expected.yaml` |
| `starters/<name>/scenario.json` | the demo, which iterates `starters/*/` at startup |
| `starters/<name>/facts/*.json` | `starters/tools/check_facts.py` (schema, hashes, spans) |
| a `phrasing:` block on a decision | `duly_kernel.phrasing`, and through it every surface that words a verdict — the demo's answer line *and* the Markdown/PDF audit report's headline ([spec/rule-ir.md](../../spec/rule-ir.md), "Decision phrasing") |
| a new test directory | CI, which runs all suites listed in `.github/workflows/ci.yml` |

**Not automatic** — nothing fails loudly if you skip these, which is exactly why they get skipped. All three are on the rule studio's Verify rail, where they say what they cannot see rather than reporting a comfortable zero:

1. **Golden-corpus coverage.** [Impact analysis](../../assurance/duly_assurance/impact.py) — the "this change flips N of M historical decisions" CI comment — runs *over the golden corpus*, not over `expected.yaml`. A pack with no generator template in [assurance/duly_assurance/generate.py](../../assurance/duly_assurance/generate.py) gets a cheerful "0 of N decisions flip" for every edit, forever. `expected.yaml` catches breakage; only the corpus catches *drift*. Adding a template is a registry entry plus a fact builder — `STATE_TEMPLATES` is deliberately data, not code — and the regeneration that follows has arithmetic worth knowing before you run it ([golden/README.md](../golden/README.md), "Adding a template").
2. **Extractor pinning for scripted confidences.** If a scenario depends on a specific confidence value — e.g. a below-floor fact that must abstain — set `"demoExtractor": "stub"` in its `scenario.json`. Docling measures its own confidence and will silently overwrite a scripted 0.58 with a passing 0.9, skipping the arc the scenario exists to demonstrate. This one has no failing test to warn you; it was found by looking at the running demo.
3. **Ontology coverage.** Every attribute, entity type, and code value your pack or targets introduce must be declared in the ontology version the facts' `schemaRef` pins ([ontologies/](../ontologies/)). This one *does* fail loudly — [`examples/tests/test_example_conformance.py`](../tests/test_example_conformance.py) sweeps every committed fact — but it fails in a suite pack authors do not expect to touch. New terms for an existing domain go in a **new version file** of that domain's ontology (committed versions are immutable; see [spec/ontology-conformance.md](../../spec/ontology-conformance.md)), and the facts pin the new version.

## The path, in order

1. **Write `pack.yaml`.** Decisions first (each with `attribute`, `entityType`, the human `question` the demo shows, and the `phrasing` for its answer — step 6), then `idPrefix` and the rules: `id`, `priority`, `citation`, `effectiveFrom`, `given`/`when`/`then`, and `overrides` where a rule defeats a default.

   *Or author this step as a decision table.* If your organization already reviews rules as DMN — business analysts with a modeller, an existing table your compliance team maintains — you can write the rules as a DMN 1.3+ decision table and compile it:

   ```bash
   uv run python -m duly_dmn compile my-rules.dmn -o examples/rulepacks/my-pack/pack.yaml
   ```

   The output is an ordinary pack; the kernel cannot tell. **This replaces step 1 and nothing else** — steps 2–7 below are the same either way. Worth knowing before you choose: every row needs `duly:ruleId`, `duly:citation`, and `duly:effectiveFrom` annotation columns, because the compiler will not invent an id, a citation, or a date on your behalf; and only `UNIQUE`, `FIRST`, and `PRIORITY` compile, since the others return lists and a duly decision is one value for one attribute. If you are writing rules from scratch and have no DMN tooling, YAML is the shorter path. See [spec/dmn.md](../../spec/dmn.md). The ids you author in `duly:ruleId` are permanent in exactly the same way, so hold them to the same convention — though note the compiler emits no `pack.idPrefix`, so a compiled pack is not currently checked against it.
2. **Write `expected.yaml`** covering every rule and every defeat chain, plus both sides of each effective-date boundary. `factsFrom` points at a starter's facts or at `fixtures/`. This is what CI runs, so under-covering here is invisible until something breaks in production.
3. **Build a starter** — synthetic documents so the pack is demonstrable. Write `starters/<name>/make_documents.py` importing the shared helpers from [starters/tools/make_documents.py](../starters/tools/make_documents.py) (import them; do not edit the shared file), commit the PDFs and renditions, and pin each document's `sha256` in `scenario.json`.
4. **Declare fact targets and extract.** One `starters/tools/targets/<name>-<doc>.json` per document, then `starters/tools/extract.py` to emit span-verified facts, then `check_facts.py` to prove every quote matches `rendition[start:end]`.
5. **Set `domain` in `scenario.json`** (`"mortgage"`, `"insurance"`, …) so the demo groups the scenario. Unknown slugs get a title-cased label and a missing field lands in "Other" — graceful, but unlabeled.
6. **Declare the phrasing in your pack** — a `phrasing:` block on each decision, giving `{verdict, detail, tone}` per case, where `tone` is `pos`/`neg`/`warn`/`""` ([spec/rule-ir.md](../../spec/rule-ir.md), "Decision phrasing"). This is domain wording, so it belongs with the rules and not in a UI; no demo code is involved either way. It is also what the **audit report** leads with — the document an examiner reads is phrased by your pack, not by the renderer — so write the verdict you would want quoted back at you. A boolean decision may skip the block and fall back to Yes/No in the demo (`attributeName: no` in the report). Anything else without it renders as `attribute = value`, which is honest but useless to a reviewer.
7. **Add a generator template** so the corpus and impact analysis cover the pack. Draw parameters that straddle every boundary the rules encode, the way the notice templates' margin ranges cross each state's threshold in both directions.

## Constraints that will bite you

All verified against the kernel, not folklore:

- **A rule id is a handle, not a claim — and it is permanent.** Ids are inside `rulesFired` on every receipt that cited them, and receipts are immutable, so an id that encodes a fact is wrong forever once that fact changes. `NY-NR-45` is in 76 golden receipts and will keep saying 45 whatever New York does next. Mint ids as `<PREFIX>-<TOPIC>[-<QUALIFIER>][-NN]`, uppercase, where `PREFIX` is your pack's declared `pack.idPrefix` and `NN` is a two-digit sequence number that means nothing else. The validator refuses a digit anywhere but that tail (so no years, statute sections or bill numbers), refuses a tail that equals a number in the rule's own body, and refuses an id outside the pack's family. Existing ids that predate the convention are exempt by an explicit list in [kernel/duly_kernel/rule_ids.py](../../kernel/duly_kernel/rule_ids.py) — 17 of the 46 would fail today, which is what one late convention costs. Full argument in [spec/rule-ir.md](../../spec/rule-ir.md), "Rule ids".
- **One entity per `entityType` per case, one live fact per attribute.** Per-document decisions therefore need either one case per document or the document type modelled as an attribute of a single entity. Two live facts for one attribute is a *conflict*, not an overwrite ([spec/rule-ir.md](../../spec/rule-ir.md)).
- **Same-priority rules concluding the same attribute must be provably disjoint**, or the pack validator rejects it. The proofs it accepts: non-overlapping effective windows, contradictory equality guards, or an explicit `overrides`. The guard check (`_equality_guards` in [kernel/duly_kernel/ir.py](../../kernel/duly_kernel/ir.py)) matches only `var == "quoted string"` — **boolean guards do not count**, so two rules distinguished solely by `x == true` / `x == false` need an explicit `overrides` even though they look disjoint to a human.

  Before you reach for that `overrides`, run the static verifier — it answers the question the validator cannot:

  ```bash
  uv run --with z3-solver python -m duly_assurance prove \
      --ontologies examples/ontologies examples/rulepacks/your-pack/pack.yaml
  ```

  `--ontologies` has no default — your ontologies are yours, and duly does not
  know where you keep them (`DULY_ONTOLOGIES` works too). It is optional, and
  passing it is worth doing anyway: without a registry the verifier infers value
  kinds from use and reports `OUT-OF-FRAGMENT` for what it cannot infer, which
  is a weaker answer honestly labelled. Across the six committed packs the
  registry is the difference between 23 pairs proved disjoint and 25.

  If the pair comes back `PROVED-DISJOINT`, your rules genuinely never overlap and the `overrides` is a workaround for the validator's narrow proof set — say so in a comment on the rule, so the next author knows which kind it is. If it comes back `NOT-PROVED`, you get the exact input assignment under which both rules fire, and the `overrides` is a real legal exception. The same run reports which input regions your rules leave with no conclusion at all. See [spec/pack-verification.md](../../spec/pack-verification.md).
- **The IR has no calendar arithmetic.** Expressions cover boolean logic, `min`/`max`, `abs`, `days_between`, comparisons, and typed literals — there is no date-plus-N, no day-of-week, no holiday calendar. If your rule needs business-day math, model the honestly expressible slice and document the boundary, as [tila-rescission](tila-rescission-us-federal/pack.yaml) does in its `MODELING BOUNDARY` header. A documented limitation is a contribution; a silent approximation is a defect.
- **Changing a pack changes receipts.** Bump the pack version, and expect the impact-analysis CI comment to tell you how many historical decisions moved. Adding an `abstentionPolicy` where there was none excludes below-floor facts and will shift outcomes.

Packs are also consumed from outside this repo's own tooling. [examples/closing-scheduler](../closing-scheduler/README.md) plans a mortgage closing against `tila-rescission-us-federal`, `notarization-ron-us-states` and `county-recording-us`, and pins the resulting plan in a test. If your change moves a date those packs decide, that test is a legitimate casualty — update it in the same commit, as you would a golden receipt.

## Honesty conventions

The repo's culture here is not negotiable, because the entire value proposition is that a decision is defensible.

- **Every rule carries a real citation**, or a `TODO(verify)` marker saying precisely what was not confirmed. Never present an unverified requirement as verified.
- **Scope comments** state what a rule does and does not cover — jurisdictions, transaction types, edge cases deliberately excluded.
- **Never invent statutory history.** If you need an effective-date change to demonstrate replay, use the real dates ([notarization-ron-us-states](notarization-ron-us-states/pack.yaml) is built entirely on real state authorization dates). Where a synthetic version is unavoidable, mark it `DEMO-SYNTHETIC` and say so in the top-level README's honest-labels paragraph.
- **Label scripted values.** A confidence chosen to make a demo reproducible is scripted, and its comment says so.
- **Fail safe, and say which way is safe.** Unknown jurisdictions and document types should resolve to the conservative outcome, with the asymmetry argued in the pack: [esign-closing-package](esign-closing-package/pack.yaml) explains why unknown document types route to wet ink (paper costs convenience; a wrong eSign risks enforceability), while [notarization-ron-us-states](notarization-ron-us-states/pack.yaml) explains why an unauthorized state is a *decision*, not an abstention (RON exists only by affirmative authorization).

## Verifying your pack

```bash
uv run pytest examples/tests -q                             # your expected.yaml runs here
uv run python3 examples/starters/tools/check_facts.py       # schema, hashes, quote spans
uv run python -m duly_conformance --ontologies examples/ontologies \
    check examples/starters examples/golden/cases examples/rulepacks spec/examples
uv run python -m duly_assurance verify                      # every golden case still replays
uv run python -m duly_assurance impact                      # what your change moved
uv run spec/validate.py                                     # spec examples and schemas
uv run uvicorn duly_demo.app:app --port 8788                # see it adjudicate
```

`examples/tests` is where a pack's declared outcomes run — [`test_rulepacks.py`](../tests/test_rulepacks.py) globs `rulepacks/*/expected.yaml`. It used to be `kernel/tests`, and relocating it was not bookkeeping: a suite that asserts *these packs behave as declared* is a claim about the example content and has to be deleted with it, or `git rm -r examples/` leaves a green suite testing nothing (CLAUDE.md, "a test that would still pass with its subject deleted").

Then the full toolkit suite, because a pack touches more than it looks like it touches:

```bash
uv run pytest core/tests kernel/tests duly_demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
```

A useful final check that no test performs: perturb one of your rules, run `impact`, and confirm it reports the flips you expect. If it reports zero, your pack has no corpus coverage — see item 1 above.

## Contributing it back

Everything above is authoring, and it reads the same whether the pack lives here or in your own content root. This section is the other half: what happens when you open a PR against duly, where your pack becomes example content and the checks below become the first reviewer.

### What your PR triggers

| Check | Runs on | What it proves — and what it cannot see |
|---|---|---|
| **CI / tests** | every PR | `examples/tests` runs your `expected.yaml` ([test_rulepacks.py](../tests/test_rulepacks.py)), sweeps every committed fact against the ontology registry ([test_example_conformance.py](../tests/test_example_conformance.py)) and holds your rule ids to the convention ([test_example_rule_ids.py](../tests/test_example_rule_ids.py)); then `spec/validate.py` and `verify` over all 351 receipts. It cannot see a rule your `expected.yaml` never exercises — coverage here is authored, not measured. |
| **CI / rule-impact** | PRs touching `examples/rulepacks/**` | Re-adjudicates the whole golden corpus under your working-tree packs and posts a sticky comment (marker `<!-- duly-impact -->`, updated in place on each push): how many historical decisions flip, with before/after receipts. **It reports; it never fails the build.** A pack with no generator template reports `0 of 351` forever, and that zero is the comfortable one. |
| **CI / deletion-gate** | every PR | `git rm -r examples` and the toolkit suites still pass. A pack PR passes this for free — unless you put a claim about your pack in a *toolkit* suite, which is precisely what it exists to catch. |
| **Optional dependency suites** | PRs touching `examples/**` — which includes `examples/rulepacks/**` | `prove` over every committed pack, as a differential check between Z3 and the validator's own disjointness proofs; real LinkML tooling over `examples/ontologies/`; and the [closing scheduler](../closing-scheduler/README.md)'s committed plan, which a pack that moves a date genuinely can break. |

The last row is worth reading twice, because it changed underneath the comments that describe it. While the packs lived at the repository root they were outside that workflow's paths filter by construction, and a pack change that moved the scheduler's plan surfaced on the merge to `main` rather than on the PR. Under `examples/` they are inside `examples/**`, so the scheduler test now fails on *your* PR — which is where this README already said the fix belongs ("a legitimate casualty — update it in the same commit"). The claim became enforceable by a directory move nobody made for that reason.

And one that no workflow runs: `prove` is not a gate on your pack. `validate_pack` already refuses a pack with an unproven same-priority overlap and no `overrides`, so a pack that *loads* cannot fail the differential check — which is exactly why running it yourself, before the PR, is the only way to learn which kind of `overrides` you wrote.

### Before you open it, in this order

Each step exists because nothing later catches it. Numbers 2, 3 and 5 are the three the top of this README warns about; the order is the part that is easy to get wrong, because the ontology has to exist before the facts that pin it and the facts have to exist before the corpus that draws on them.

1. **The pack loads and validates** — ids under `idPrefix`, a citation or a `TODO(verify)` on every rule, a `phrasing:` block on every non-boolean decision, `overrides` where a rule defeats a default. `validate_pack` refuses malformed phrasing, an off-convention id, and an unproven same-priority overlap where the pack loads.
2. **Ontology coverage, in a new version file.** Every attribute, entity type and code value your pack or targets introduce is declared in the ontology version your facts' `schemaRef` pins. Committed versions are immutable: new terms mean a new `<name>/<version>.yaml` and facts that pin it ([ontologies/README.md](../ontologies/README.md)).
3. **A starter**, so the pack is demonstrable: documents, `targets/`, span-verified facts, `scenario.json` with `domain` set and — if any confidence is scripted — `"demoExtractor": "stub"` ([starters/README.md](../starters/README.md)).
4. **`expected.yaml` covering every rule, every defeat chain, and both sides of every effective-date boundary.** Under-covering here is invisible: CI runs what you declared and reports the count that remains.
5. **A generator template, and the corpus regeneration that follows it** — the only thing that gives your pack a non-zero impact answer, ever. Adding one changes the corpus, so it is a deliberate baseline change with its own arithmetic: [golden/README.md](../golden/README.md), "Adding a template".
6. **The verification block above, run in full**, plus `prove` if your pack has same-priority rules concluding one attribute.
7. **The honesty pass, last.** Re-read your own citations. This is the one a reviewer will send back.

### What reviewers read for

Test-green is the floor, not the bar. What gets read closely, in the order it gets read:

- **Citations.** Every rule cites its authority or carries a `TODO(verify)` naming exactly what was not confirmed. "Cites something that sounds right" is the failure mode; a `TODO(verify)` is not a demerit, it is the honest form.
- **`DEMO-SYNTHETIC` on anything invented.** Statutory history above all: if you need an effective-date change to demonstrate replay, use real dates, and where a synthetic one is unavoidable mark it and say so in the top-level README's honest-labels paragraph.
- **A `MODELING BOUNDARY` header where the IR ran out.** Business-day math, holiday calendars, anything the expression grammar cannot state. A documented limitation is a contribution; a silent approximation is a defect, and the approximation is usually invisible in the diff.
- **Which kind of `overrides` you wrote**, in a comment on the rule — an authored legal exception, or a workaround for a proof the validator cannot perform. Only `prove` tells them apart, and the comment is the only place the answer survives.
- **Scope comments** that say what the rule does *not* cover, and a stated direction of safety for unknown inputs, argued in the pack rather than assumed.
- **Rule ids you can live with forever.** They sit in `rulesFired` on every receipt that cites them and will not be renamed after merge.

### What nobody will wire for you

The list is short and it is the whole register:

- **A generator template.** Not written for you, not backfilled later. Without it the impact comment on every future edit to your pack reads `0 of N` and means nothing.
- **`expected.yaml` cases.** A reviewer will tell you the coverage is thin; a reviewer will not author the cases.
- **The starter, its documents, its targets, or its facts.** A pack with no starter is not demonstrable, and "add a starter later" has the same shape as "add tests later".
- **An ontology version file for your new terms** — and no one will edit a committed version to make your facts conform. That direction is closed by design.
- **The `demoExtractor` pin.** No test warns; the scenario simply demonstrates something other than what you wrote it to demonstrate.
- **Corpus regeneration to make your flips disappear.** A flip is either intentional and explained in the PR, or a bug in the pack. Regenerating to match is a reviewed act of accepting a new baseline, never a way to quiet a diff.
- **A `phrasing:` block.** Without one a non-boolean decision renders as `attribute = value` in the demo and in the audit report an examiner reads — honest, and useless.
- **The date update in the closing scheduler's committed plan**, if your rules move it. Yours to make, in the same commit.

Every item is something that fails quietly or not at all, which is why the list is stated as a refusal rather than as advice.

## Gotchas that have actually bitten

Moved here from the root CLAUDE.md: every one is about authoring pack content, and this README is the mandated reading for that. The validator enforces some of these now — the prose stays because it says *why*.

- **An `overrides` can mean two different things, and only a solver tells them apart.** `PKG-NOTE-31 overrides PKG-NOTE-30` is an authored legal exception over rules that genuinely overlap (a registered eNote *is* a promissory note); TILA's manufactured priority gap is a workaround for a proof the validator cannot perform. Both look identical in the pack. Run `prove` before adding either — if the pair comes back PROVED-DISJOINT you were working around the validator, and the comment saying so belongs on the rule.

- **Only `attribute` bindings can prove disjointness — `derived` ones cannot.** Narrower than the boolean-guard gotcha below and less visible: `_equality_guards` inspects only `when` items whose variable resolves to an *attribute* binding, so `category == "ZeroTolerance"` on a `derived` binding proves nothing however string-equal it looks. Two same-priority rules separated only by a derived-value guard need an explicit `overrides`.

- **Boolean guards don't prove disjointness.** The pack validator's same-priority check accepts only *quoted-string* equality guards (`state == "US-NY"`) as a disjointness proof. Two rules split by `x == true` / `x == false` need an explicit `overrides`, even though they look disjoint.

- **`expected.yaml` is not the corpus.** Pack outcome declarations run in CI, but impact analysis runs *over `golden/`*. A pack without a generator template in `assurance/duly_assurance/generate.py` gets "0 decisions flip" for every edit. Both are required.

- **Non-boolean decisions need *pack* phrasing, and the audit report reads it too.** A decision that isn't boolean renders as a bare `attribute = value` unless its `decisions[]` entry carries a `phrasing:` block ([spec/rule-ir.md](../../spec/rule-ir.md), "Decision phrasing"). The fix is in the pack, never in `duly_demo/app.py` — and never in `kernel/duly_kernel/report.py` either, which used to carry a heuristic ("if the attribute name contains *compliant*…") that quietly outranked whatever the pack said. One renderer, `duly_kernel.phrasing.determination`, now answers for both surfaces; `validate_pack` rejects a malformed block, an unknown placeholder, or a tone outside `pos/neg/warn/""` where the pack loads. Booleans still get a fallback (Yes/No in the demo, `attributeName: no` in the report). Phrasing is presentation and must stay out of every hashed body — putting it in a receipt would change every hash.

- **Rule ids are permanent, and now conventional.** Ids sit in `rulesFired` on every receipt that cited them, so an id encoding a day count, a year, or a statute section is wrong forever once the law moves — `NY-NR-45` is in 76 golden receipts. New ids are `<PREFIX>-<TOPIC>[-QUALIFIER][-NN]` with `PREFIX = pack.idPrefix`; `validate_pack` refuses digits outside the two-digit tail, a tail echoing the rule's own numbers, and an id outside the pack's family. The 46 pre-convention ids are exempt by an explicit list in [kernel/duly_kernel/rule_ids.py](../../kernel/duly_kernel/rule_ids.py) — 17 of them would fail today. Checks run only for packs declaring `idPrefix`; a kernel test requires every committed pack to declare one.

- **Calendars are pack data and coverage is a wall.** `add_business_days` walks only the pack's `calendars:` block; a walk touching any day outside the calendar's `coverage` window raises rather than guessing. The TILA calendar reconciles by test with the corpus generator's 6103(a) derivation — edit either and the suite tells you.

- **Kernel abstention policy is pack-versioned.** Adding `abstentionPolicy` to a pack changes receipts (bump the pack version, expect corpus churn for that pack). Packs without one must stay byte-identical — there is a pinned-hash test proving the pre-policy kernel's output.
