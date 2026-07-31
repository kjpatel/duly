# Authoring a rule pack

A rule pack is versioned, cited, effective-dated domain knowledge — the contribution surface where legal and operational expertise matters more than familiarity with the kernel. This guide is the path from "I know a rule" to "the rule is adjudicated, demonstrated, and protected by regression tests."

Read [spec/rule-ir.md](../spec/rule-ir.md) for what the IR *means*. This document is about the mechanics around it.

## A pack is three things

```
rulepacks/<pack-name>/
  pack.yaml        # metadata, decisions, rules, optional abstentionPolicy
  expected.yaml    # declared adjudication outcomes — the pack's own test suite
  fixtures/<case>/facts/*.json   # optional: fact sets for expected.yaml cases
```

Copy [termination-notice-us-states](termination-notice-us-states/) for a jurisdiction-scoped pack, or [trid-fee-tolerance-us-federal](trid-fee-tolerance-us-federal/) for a two-document computation. Neither is a toy; both are what shipped.

## Most wiring is automatic. Three things are not.

This is the part worth internalizing, because it is where contributions silently come up short.

**Automatic** — add the file and it works, no registration anywhere:

| You add | It is picked up by |
|---|---|
| `rulepacks/<name>/expected.yaml` | `kernel/tests/test_rulepacks.py`, which globs `rulepacks/*/expected.yaml` |
| `starters/<name>/scenario.json` | the demo, which iterates `starters/*/` at startup |
| `starters/<name>/facts/*.json` | `starters/tools/check_facts.py` (schema, hashes, spans) |
| a `phrasing:` block on a decision | the demo, which words every verdict from the pack ([spec/rule-ir.md](../spec/rule-ir.md), "Decision phrasing") |
| a new test directory | CI, which runs all suites listed in `.github/workflows/ci.yml` |

**Not automatic** — nothing fails loudly if you skip these, which is exactly why they get skipped:

1. **Golden-corpus coverage.** [Impact analysis](../assurance/duly_assurance/impact.py) — the "this change flips N of M historical decisions" CI comment — runs *over the golden corpus*, not over `expected.yaml`. A pack with no generator template in [assurance/duly_assurance/generate.py](../assurance/duly_assurance/generate.py) gets a cheerful "0 of N decisions flip" for every edit, forever. `expected.yaml` catches breakage; only the corpus catches *drift*. Adding a template is a registry entry plus a fact builder — `STATE_TEMPLATES` is deliberately data, not code.
2. **Extractor pinning for scripted confidences.** If a scenario depends on a specific confidence value — e.g. a below-floor fact that must abstain — set `"demoExtractor": "stub"` in its `scenario.json`. Docling measures its own confidence and will silently overwrite a scripted 0.58 with a passing 0.9, skipping the arc the scenario exists to demonstrate. This one has no failing test to warn you; it was found by looking at the running demo.
3. **Ontology coverage.** Every attribute, entity type, and code value your pack or targets introduce must be declared in the ontology version the facts' `schemaRef` pins ([ontologies/](../ontologies/)). This one *does* fail loudly — `conformance/tests/test_repo_conformance.py` sweeps every committed fact — but it fails in `conformance/`, which pack authors do not expect to touch. New terms for an existing domain go in a **new version file** of that domain's ontology (committed versions are immutable; see [spec/ontology-conformance.md](../spec/ontology-conformance.md)), and the facts pin the new version.

## The path, in order

1. **Write `pack.yaml`.** Decisions first (each with `attribute`, `entityType`, the human `question` the demo shows, and the `phrasing` for its answer — step 6), then `idPrefix` and the rules: `id`, `priority`, `citation`, `effectiveFrom`, `given`/`when`/`then`, and `overrides` where a rule defeats a default.

   *Or author this step as a decision table.* If your organization already reviews rules as DMN — business analysts with a modeller, an existing table your compliance team maintains — you can write the rules as a DMN 1.3+ decision table and compile it:

   ```bash
   uv run python -m duly_dmn compile my-rules.dmn -o rulepacks/my-pack/pack.yaml
   ```

   The output is an ordinary pack; the kernel cannot tell. **This replaces step 1 and nothing else** — steps 2–7 below are the same either way. Worth knowing before you choose: every row needs `duly:ruleId`, `duly:citation`, and `duly:effectiveFrom` annotation columns, because the compiler will not invent an id, a citation, or a date on your behalf; and only `UNIQUE`, `FIRST`, and `PRIORITY` compile, since the others return lists and a duly decision is one value for one attribute. If you are writing rules from scratch and have no DMN tooling, YAML is the shorter path. See [spec/dmn.md](../spec/dmn.md). The ids you author in `duly:ruleId` are permanent in exactly the same way, so hold them to the same convention — though note the compiler emits no `pack.idPrefix`, so a compiled pack is not currently checked against it.
2. **Write `expected.yaml`** covering every rule and every defeat chain, plus both sides of each effective-date boundary. `factsFrom` points at a starter's facts or at `fixtures/`. This is what CI runs, so under-covering here is invisible until something breaks in production.
3. **Build a starter** — synthetic documents so the pack is demonstrable. Write `starters/<name>/make_documents.py` importing the shared helpers from [starters/tools/make_documents.py](../starters/tools/make_documents.py) (import them; do not edit the shared file), commit the PDFs and renditions, and pin each document's `sha256` in `scenario.json`.
4. **Declare fact targets and extract.** One `starters/tools/targets/<name>-<doc>.json` per document, then `starters/tools/extract.py` to emit span-verified facts, then `check_facts.py` to prove every quote matches `rendition[start:end]`.
5. **Set `domain` in `scenario.json`** (`"mortgage"`, `"insurance"`, …) so the demo groups the scenario. Unknown slugs get a title-cased label and a missing field lands in "Other" — graceful, but unlabeled.
6. **Declare the phrasing in your pack** — a `phrasing:` block on each decision, giving `{verdict, detail, tone}` per case, where `tone` is `pos`/`neg`/`warn`/`""` ([spec/rule-ir.md](../spec/rule-ir.md), "Decision phrasing"). This is domain wording, so it belongs with the rules and not in a UI; no demo code is involved either way. A boolean decision may skip it and fall back to Yes/No. Anything else without it renders as `attribute = value`, which is honest but useless to a reviewer.
7. **Add a generator template** so the corpus and impact analysis cover the pack. Draw parameters that straddle every boundary the rules encode, the way the notice templates' margin ranges cross each state's threshold in both directions.

## Constraints that will bite you

All verified against the kernel, not folklore:

- **A rule id is a handle, not a claim — and it is permanent.** Ids are inside `rulesFired` on every receipt that cited them, and receipts are immutable, so an id that encodes a fact is wrong forever once that fact changes. `NY-NR-45` is in 76 golden receipts and will keep saying 45 whatever New York does next. Mint ids as `<PREFIX>-<TOPIC>[-<QUALIFIER>][-NN]`, uppercase, where `PREFIX` is your pack's declared `pack.idPrefix` and `NN` is a two-digit sequence number that means nothing else. The validator refuses a digit anywhere but that tail (so no years, statute sections or bill numbers), refuses a tail that equals a number in the rule's own body, and refuses an id outside the pack's family. Existing ids that predate the convention are exempt by an explicit list in [kernel/duly_kernel/rule_ids.py](../kernel/duly_kernel/rule_ids.py) — 17 of the 46 would fail today, which is what one late convention costs. Full argument in [spec/rule-ir.md](../spec/rule-ir.md), "Rule ids".
- **One entity per `entityType` per case, one live fact per attribute.** Per-document decisions therefore need either one case per document or the document type modelled as an attribute of a single entity. Two live facts for one attribute is a *conflict*, not an overwrite ([spec/rule-ir.md](../spec/rule-ir.md)).
- **Same-priority rules concluding the same attribute must be provably disjoint**, or the pack validator rejects it. The proofs it accepts: non-overlapping effective windows, contradictory equality guards, or an explicit `overrides`. The guard check (`_equality_guards` in [kernel/duly_kernel/ir.py](../kernel/duly_kernel/ir.py)) matches only `var == "quoted string"` — **boolean guards do not count**, so two rules distinguished solely by `x == true` / `x == false` need an explicit `overrides` even though they look disjoint to a human.

  Before you reach for that `overrides`, run the static verifier — it answers the question the validator cannot:

  ```bash
  uv run --with z3-solver python -m duly_assurance prove rulepacks/your-pack/pack.yaml
  ```

  If the pair comes back `PROVED-DISJOINT`, your rules genuinely never overlap and the `overrides` is a workaround for the validator's narrow proof set — say so in a comment on the rule, so the next author knows which kind it is. If it comes back `NOT-PROVED`, you get the exact input assignment under which both rules fire, and the `overrides` is a real legal exception. The same run reports which input regions your rules leave with no conclusion at all. See [spec/pack-verification.md](../spec/pack-verification.md).
- **The IR has no calendar arithmetic.** Expressions cover boolean logic, `min`/`max`, `abs`, `days_between`, comparisons, and typed literals — there is no date-plus-N, no day-of-week, no holiday calendar. If your rule needs business-day math, model the honestly expressible slice and document the boundary, as [tila-rescission](tila-rescission-us-federal/pack.yaml) does in its `MODELING BOUNDARY` header. A documented limitation is a contribution; a silent approximation is a defect.
- **Changing a pack changes receipts.** Bump the pack version, and expect the impact-analysis CI comment to tell you how many historical decisions moved. Adding an `abstentionPolicy` where there was none excludes below-floor facts and will shift outcomes.

Packs are also consumed from outside this repo's own tooling. [examples/closing-scheduler](../examples/closing-scheduler/README.md) plans a mortgage closing against `tila-rescission-us-federal`, `notarization-ron-us-states` and `county-recording-us`, and pins the resulting plan in a test. If your change moves a date those packs decide, that test is a legitimate casualty — update it in the same commit, as you would a golden receipt.

## Honesty conventions

The repo's culture here is not negotiable, because the entire value proposition is that a decision is defensible.

- **Every rule carries a real citation**, or a `TODO(verify)` marker saying precisely what was not confirmed. Never present an unverified requirement as verified.
- **Scope comments** state what a rule does and does not cover — jurisdictions, transaction types, edge cases deliberately excluded.
- **Never invent statutory history.** If you need an effective-date change to demonstrate replay, use the real dates ([notarization-ron-us-states](notarization-ron-us-states/pack.yaml) is built entirely on real state authorization dates). Where a synthetic version is unavoidable, mark it `DEMO-SYNTHETIC` and say so in the top-level README's honest-labels paragraph.
- **Label scripted values.** A confidence chosen to make a demo reproducible is scripted, and its comment says so.
- **Fail safe, and say which way is safe.** Unknown jurisdictions and document types should resolve to the conservative outcome, with the asymmetry argued in the pack: [esign-closing-package](esign-closing-package/pack.yaml) explains why unknown document types route to wet ink (paper costs convenience; a wrong eSign risks enforceability), while [notarization-ron-us-states](notarization-ron-us-states/pack.yaml) explains why an unauthorized state is a *decision*, not an abstention (RON exists only by affirmative authorization).

## Verifying your pack

```bash
uv run pytest kernel/tests -q                       # your expected.yaml runs here
uv run python3 starters/tools/check_facts.py         # schema, hashes, quote spans
uv run python -m duly_assurance verify               # every golden case still replays
uv run python -m duly_assurance impact               # what your change moved
uv run spec/validate.py                              # spec examples and schemas
uv run uvicorn demo.app:app --port 8788              # see it adjudicate
```

Then the full suite, because a pack touches more than it looks like it touches:

```bash
uv run pytest kernel/tests demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests -q
```

A useful final check that no test performs: perturb one of your rules, run `impact`, and confirm it reports the flips you expect. If it reports zero, your pack has no corpus coverage — see item 1 above.
