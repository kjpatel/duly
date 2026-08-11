# Changelog

What each release turned out to mean. The [roadmap](README.md#roadmap) says what is planned and what is done; this file says what was learned doing it — the boundaries that moved, the claims that were corrected, and the things that could not be done honestly.

Entries are written after the fact, from merged work.

**Through M4, these versions were git tags marking milestones, not package releases** — `pyproject.toml` deliberately stayed at `0.0.1` because nothing was published, and a tag said "this milestone is done and here is what it meant" without claiming the contract was stable. **From v1.0.0 a tag is both**: the distribution version and the tag agree, and the milestone/stability distinction is carried by [spec/compatibility.md](spec/compatibility.md) instead of by the absence of a package.

## Unreleased

**A question a reader asked the demo, and could not answer from it.** Someone downloaded a receipt minted in a live session, pasted it back into the receipt viewer, got **Partly verified** with two *not checked* cards, and reasonably concluded verification was broken. Every word on the screen was accurate; nothing on it said the thing that would have resolved the confusion. What that exposed was not a defect in the receipt contract but an unexamined seam in how the project talks about it — and, underneath, one real bug.

### Added

- **Bundle exports** (`Receipt + facts`, in the decision workspace and the receipt viewer). A JSON array carrying the receipt and the exact fact set it was adjudicated over — *wrapped*, never merged, because a fact array added inside a receipt changes the bytes its own `receiptSha256` covers, so the merged document would fail the first check it met. Bundles are the whole fact set rather than `inputFacts`, which is the subtlety: abstentions are computed over the entire live fact set, so a below-floor fact shapes a receipt without ever binding, and replaying from the pinned facts alone drops the abstention and byte equality with it.
- **[The FAQ answers the question directly](docs/faq.md)** — *a receipt does not carry its facts; what does it prove if they are gone?* Integrity and a binding commitment to the evidence, which are separable from availability. The commitment is the part that is easy to miss: losing the facts costs the ability to substantiate a decision and never buys the ability to substitute a more convenient account of what the evidence was, because matching a pinned hash with different bodies is a second-preimage attack. Evidence loss is made visible and irreversible rather than quietly repairable.

### Fixed

- **The workspace's receipt download was corrupting hashed bytes, and the demo data hid it.** `abstentions[].confidence.score` and `.threshold.minConfidence` are JSON *numbers* in the receipt schema; the button assembled its file with `JSON.stringify` in the browser, and JavaScript has one number type — so a receipt whose abstention scored exactly `1.0` downloaded as `1`, a different canonical body, and failed its own hash check in the viewer one page over. The [JSON-fidelity gotcha](duly_demo/CLAUDE.md) had been written a release earlier about the *upload* direction and read as a rule about `/inspect`; it was always directionless. Every export is a server round trip now, pinned by feeding the download back into `/inspect`. Nothing caught it because no committed scenario has an integral floor or score — the bug needed a `0.0` or a `1.0`, and honest demo data never produced one.
- **A demo scenario's in-memory facts are not always the documents their ids name**, which the deletion gate found by failing the new bundle test. `_load_fixture_scenario` rewrites `grounding.charSpan` on the committed `spec/examples` facts to index the abridged rendition the demo serves — right for a highlight, and a mutation of a content-addressed body, so those facts stop hashing to their own ids. It went unnoticed because the demo had only ever *displayed* them; an export is the first path that hands facts to someone as hashed artifacts. The bundle re-hashes every pinned fact and refuses rather than emit a file that fails its own facts check, since **"the evidence has been altered" is indistinguishable from a forgery on the receiving end** — the guard is on the artifact rather than the code path, so a future edit-on-the-way-through is caught the same way.
- Receipt-viewer and audit-report copy now say *why* a check could not run and what supplying the facts would change, rather than only that it did not: "not checked" is a missing input, not a refuted check, and the two are different verdicts on purpose.
- **The abstentions prose now matches the abstentions behavior** — the same fact the bundle export above ran into from the other side, arrived at independently. The kernel has always filtered the case's live facts before any rule runs, and every entry seals into every receipt for the case; but the fact spec said abstentions were "attributes the decision *needed* but declined to use", and the demo captioned its panel the same way, so a `low_confidence` entry appearing on a question whose rules never consult the attribute read as a UI bug rather than as the design. The behavior is pinned by the 351 golden receipts and did not move; the sentences did — [spec/grounded-facts.md](spec/grounded-facts.md), [spec/rule-ir.md](spec/rule-ir.md) (the filter's scope is the case, not the question), the receipt schema's own `description`, [docs/concepts.md](docs/concepts.md), and the architecture doc, which gained the sharper claim: abstention is a property of the case's evidence, not of the question asked. The demo now also labels a not-consulted entry explicitly — a server-computed presentation hint beside the receipt, never in its bytes.

- **The demo's own default effective date floated on the wall clock**, which is a peculiar defect for a project whose claim is that a decision replays under the rules of a named date. The loader intended to open each scenario at the latest `effectiveFrom` among its facts and fall back to `date.today()`; no committed starter fact carries that field, so the fallback was the only branch that had ever run. Two consequences, and the second is the one that stung: the demo was not reproducible day to day, and the floating date was *hiding teaching* — `tila-rescission` answers `fundingPermitted = true` at any date past the rescission window, so the scenario built to show a borrower's rescission right was showing the dull steady state instead. Every starter now declares the moment its case turns on, with a sibling field saying why that date, since JSON allows no comments. **A fallback that is the only branch anyone exercises is not a fallback, it is the design** — and nothing said so out loud.

- **An audit report could caption a decision with an exclusion that decision never read.** Abstentions are case-wide by design — the kernel filters the live-fact universe once, before any rule runs — so a receipt carries every exclusion its case had. `low_confidence_caveat` collected all of them, and it renders the `{caveat}` placeholder *and* decides the `abstained` phrasing guard, for the demo and the examiner-facing report alike. A decision whose rules never touched the attribute could therefore read "Presumption only — … excluded": a false claim about why that answer is what it is, in the document a regulator reads. Now scoped by **[`duly_kernel.relevance`](kernel/duly_kernel/relevance.py)**, one shared answer to "can this decision reach that attribute", following `derived` bindings transitively.

  Two things about how it hid. **The corpus structurally cannot produce the failure**: it asks one question per case, so every abstention it records is relevant — all 43 receipts carrying a `low_confidence` entry check out, and scoping changes no committed byte. It takes asking *several* questions of *one* case, which is what the demo does and what a user did. And the kernel's own phrasing tests passed because their fixture pack abstained over an attribute its only rule never bound — a fixture describing a situation the system cannot be in, which is its own small lesson about synthetic test data.

### Changed

- **The decision workspace's audit pane is three tabs rather than five stacked sections** — Derivation, Rules fired, Abstentions, each labelled with its count, because *Abstentions · none* is a useful thing for a decision to say and an empty section is not. It uses the `.tabs` component the receipt viewer, evidence browser and rule studio already shared and this pane was the last to do without, which is the "one shape per job" convention doing its job: the fix for a crowded column was to reach for the system, not to add a fifth top-level page. A page would also have cost the demo its best moment — correcting a fact and watching the verdict flip *on the spot* — by putting a navigation between the two halves of it.
- [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) sharpens the claim this work put pressure on. The doc already argued that a record only its author can verify is documentation, while one its recipient can verify is a receipt — "the difference is not in the artifact, it is in whether the checking is available to the person with a reason to doubt." What the download exposed is that this availability has a *packaging* precondition: **integrity travels inside the artifact; availability is a retention decision somebody has to make.** The separation is not a gap in the scheme — it is what lets a receipt prove what was decided to someone not entitled to read the evidence it was decided from.

## v1.1.1 — both edges walkable, and the envelope measured

**M5 closes with this release.** Its exit criterion was met the only way it could be honestly: an agent with no repository context followed the guide with an invented domain and reached a verified, replaying corpus in one sitting. The plan that ran the milestone (26 PRs at estimate, 40 shipped, every overrun a measurement replacing a guess) is deleted with the milestone; what it proved out lives in CLAUDE.md's rules, the stability policy, and this file.

### Added

- **Both contribution paths are walkable** — the roadmap's "only one of them has a path" is closed. [examples/rulepacks/README.md](examples/rulepacks/README.md) gained "Contributing it back" (what a pack PR triggers, what each check cannot see, what nobody wires for you); [extraction/README.md](extraction/README.md) is the adapter edge's new component contract, whose central observation makes recording harnesses unnecessary: conversion and proposal are separable stages with a content-addressed artifact between them, so *the rendition is the recording* and `StubAdapter` is the replay adapter that already exists.
- **[The capacity envelope](docs/capacity-envelope.md)** — ~3,100 adjudications/s/core with the pack in memory (p50 0.32 ms); parse is the 30× lever; scaling additive in rules and facts; five named shapes where the reference interpreter is the wrong tool. One curve published rather than tuned: `validate_pack` is quadratic in rules-per-attribute, cause located. `bench/capacity_bench.py` is the only stopwatch in the repository, by design.

### Fixed

- The corpus generator now writes the committed corpus's content-root-relative pack refs while loading via the working directory — a regeneration is byte-inert again (proven over a corpus copy, 351/351 including `review-0001`), where it would have rewritten 350 `pack:` lines.
- Starter generators merge into `scenario.json` instead of overwriting it: hand-maintained keys (`domain`, `demoExtractor`, `reviewArc`) survive a re-run, enforced by a new generator-drift suite. The same fix caught the reverse drift — one generator's literal was resurrecting fact files deleted from the manifest and the disk.
- Three docs pointed the LinkML lane at its pre-move path — a command that collected zero tests and exited 0; and the optional-deps comments still claimed the packs were outside a paths filter the move had put them inside.

## v1.1.0 — the adopter's wave

What shipping the adopter's guide cost and taught. The guide was written by executing every command against an installed wheel, then executed *again* by an agent with no context and an invented domain — and the three defects that run surfaced were all in seams the guide's claims never covered.

### Added

- **[The adopter's guide](docs/adopters-guide.md)** — one end-to-end bring-your-own walkthrough: documents → adapter → facts → conformance → pack → store → review → corpus → calibration, every command executed outside the repository against the released wheel, with a "what is not automatic" register and a closing statement of what an adopter is depending on.
- **First-contact imports** — `duly_extraction` and `duly_store` re-export their public surfaces (`from duly_store import FactStore` works now); the missing-solver messages in `duly-whatif` and `prove` speak to installed users instead of naming this repository's paths.
- `duly_kernel.phrasing` — the pack-phrasing engine as public kernel API (see below).

### Fixed — the three defects the cold run found

- **The audit report now reads the pack's `phrasing:` block.** It had guessed verdicts from attribute names — agreeing with duly's own packs by coincidence, so neither renderer was ever compared against the other. Phrasing lives in `duly_kernel.phrasing` beside its validator; the report and the demo are two callers of one implementation, keeping only their per-medium fallbacks.
- **`duly-whatif` reads `case.yaml` dates with the kernel's parser.** The review freezer writes the receipt's `date-time` form, the generator writes bare dates, both legal — and what-if was the only reader parsing the field itself, so it agreed on 350 committed cases and tracebacked on the 351st. Bad input is now a diagnostic naming field and file.
- **The receipt viewer resolves packs by declared name, not directory name.** Nothing requires a pack's directory to match `pack.name` except this checkout's habit — an adopter with any other layout got `replay: unavailable`. The eighth costume of the repo-relative-path defect, subtler for the path being correct and only the assumption behind it wrong.

### Changed

- **The stability posture, corrected** ([spec/compatibility.md](spec/compatibility.md) is now "the stability policy"): the contracts are *held stable*, not "frozen" — an architecture that **can** be locked, a priced and versioned break procedure (C9) with a named failing check behind every contract, and an explicit pre-adoption clause. An unfalsifiable promise is weaker than a procedure with a check behind it.
- Roadmap milestones are M-numbers (`M6`–`M8+`): version numbers belong to releases now that tags are releases, and this minor release moving mid-milestone is the proof.

## v1.0.0 — M5: adoption and v1.0

The milestone where duly became installable, deletable, and accountable for its own contracts: `pip install` gives the seam, `git rm -r examples/` leaves a working toolkit (enforced in CI), and the fact/receipt/IR contracts are v1.0 with what they hold stable — and what it would take to break one — written down. 351 golden receipts replay byte-for-byte from before the milestone — nothing here changed a decision.

### The demo grew three surfaces

**Rule studio** (`/rules`) — packs as editable decision-table grids with the validator, declared cases, ad-hoc cases, corpus impact and the solver over one session draft; drafts never write into the packs. **Evidence browser** (`/evidence`) — every fact with its grounding, provenance and supersession chain under a knowledge-time dial; liveness recomputed from the event log and differentially checked against the store. **Receipt viewer** (`/receipt`) — any receipt re-verified on open: own hash, fact hashes, full re-adjudication; a re-sealed forgery passes the first two checks, which is why there are three.

### The contracts reached v1.0

- **[spec/compatibility.md](spec/compatibility.md)** — what v1.0 holds stable per contract (C1–C9), including the receipt having no extension point, review resolutions superseding (C6, now enforced), and how a break happens when one is right (C9).
- **Semantics-scoped replay** — every replay path checks `engine.version` against what the kernel implements and refuses rather than replaying foreign semantics; `engine.version` is a decision-semantics pin, not a package version, and stays `0.0.1` at 1.0.0 by design.
- **`decision_digest()`** — a hash over a receipt's determinant fields, excluding what identifies the run; cross-backend agreement is digest equality, with self-contained vectors in [spec/decision-digest-vectors.json](spec/decision-digest-vectors.json).
- **One canonical form** — RFC 8785 key order in a shared `duly_core`, seven call sites migrated, provably inert.

And the correction the milestone's own documentation needed, found by writing the adopter's guide: **the work built the machinery for locking a contract and then described it with a word the machinery does not support.** "Frozen" reads as *this will not change*, which is a claim about the future that nobody — not this project, not its readers, not a test — can audit. What actually shipped is better and more checkable: canonical bytes, a decision-semantics pin whose replay guard refuses receipts it has no standing to answer for, committed canonical-form and digest vectors, a corpus that replays on every push, and four version scopes with a procedure saying which one moves. That is an architecture that *can* be locked, holding its contracts stable by policy — and a break stays available as a deliberate, versioned, documented major-version event, which is what C9 was for all along even while it was filed last and read as an appendix. The generalization is one this project already applies to rule packs and had exempted itself from: **an unfalsifiable promise is weaker than a procedure with a failing check behind it**, and every contract here has the second. duly also has no external adopters yet, so saying "frozen" claimed a rigidity that no dependency had yet earned — the honest version costs nothing and survives being wrong.

### The seams stopped assuming this repository

- Schemas ship inside `duly_core`; the review queue works from an installed wheel; every CLI lost its repo-relative path defaults — **seven instances of one defect**, the last surviving two sweeps because it was the second parser in an already-fixed file. Sweep by parser, not by file.
- An empty corpus reports honestly ("0 of 0" is a sentence, not a pass); a missing one refuses.
- `wheel_smoke.py` runs one real entry point per package from an installed wheel, and refuses to run from the source tree.

### A corpus the toolkit owns

- **[`fixtures/`](fixtures/README.md)** — one invented domain: a pack with declared cases, five corpus cases, committed receipts, an ontology, a span-grounded scenario with extraction targets, DMN inputs, a deterministic builder. Every toolkit suite runs on it; the founding rule is that **a test that would still pass with its subject deleted is not a test**.
- The conversions kept finding the rule's quiet forms: loops over empty globs, parametrize collecting zero cases, a contract demo reading `golden/`, a suite no scout had swept. The deletion measurement caught what reading missed, every time.
- Fixture facts are adapter-emitted from committed targets (the hand-assembled originals were schema-invalid and nothing was positioned to notice); `sensitivity` became a declared target field the adapter carries — nothing infers PII.
- The demo's review arc became content (a `reviewArc` manifest block), provable end-to-end on a fixture-only deployment.

### The separation, enforced

- **The move**: teaching content under `examples/` — 2,253 files by pure rename, `review-0001` byte-compared across it. The content-root contract stayed flat; the repo's default root became `examples/`; 351 committed case refs resolve unrewritten. Example tests live in `examples/tests/` and die with the directory.
- **The deletion gate**: CI deletes `examples/` on every push, runs all eleven toolkit suites (791 pass), asserts the verifier's honest refusal, and boots all four demo pages against nothing. The built-in `spec/examples` scenario now ships with the demo, so the deleted state demonstrates the contract rather than nothing.
- CLAUDE.md's gotchas split to where the work happens (root file −32%), with a graduation rule: when a check starts catching a gotcha, the prose shrinks to name the check.

### Distribution

- **`duly_demo`** — the demo is an installable package; `static/` ships as package data; the wheel excludes the in-package tests it would otherwise have carried.
- **A plain install is seven packages** — duly, pyyaml, and jsonschema's closure — down from 18, pinned by an assertion in the wheel check. Extras: `demo` (fastapi/uvicorn — also the review API's surface), `report` (reportlab). The `scheduling` extra moved into its example as PEP 723 metadata. jsonschema is core because C6 enforcement is not behaviour an extra may withhold.
- **`1.0.0`**, distribution scope only — `test_engine_identity` proves the bump moves no receipt byte. Five console scripts (`duly-verify`, `duly-impact`, `duly-conformance`, `duly-dmn`, `duly-whatif`), each introducing itself by its own name, smoked from an installed wheel by running them.

### Corrections this milestone made to its own record

The narrowness argument gained its supply-chain half: every package that can execute in the process that seals a receipt is inside the boundary the receipt's guarantees are drawn against. The blast radius of a rule edit is not a syntactic property of the edit — a one-line change to a derived value moves every decision downstream while their rules stay byte-identical, which is what the studio's equivalence panel is *for*. And subtracting from a plain install is a breaking change; the release-process table now says so.

## v0.4.0 — M4: standards, authoring, and static assurance

Ten capabilities across twenty-five pull requests (#6–#30), and **the golden corpus was never regenerated once**. All 351 receipts still replay byte-for-byte from before any of it. Every track's acceptance test was that `git diff -- golden/` came back empty.

### Interchange and contract

**PROV-O JSON-LD export.** Facts, receipts, and run envelopes expand to W3C PROV triples under external context files, stored bytes unchanged. The mapping is deliberately partial — bitemporal effective time, confidence, and abstentions have no faithful PROV equivalent and stay in duly's namespace. An earlier "lossless mapping" claim was corrected in the process.

**Ontology conformance gate.** A fact's `schemaRef` resolves against a registry of versioned, immutable LinkML artifacts; a misspelled attribute that previously surfaced only as a rule silently failing to bind now fails ingestion loudly. The hot-path validator interprets a documented LinkML subset rather than importing linkml-runtime, which would drag RDF tooling into the runtime; a marker-gated suite proves the files are genuine LinkML under real tooling.

**Pack-embedded calendars.** `add_business_days` walks a calendar carried inside the rule pack — excluded weekdays, cited holiday dates, and a coverage window that raises rather than guessing past its edge. "Last Monday in May" became legal content, versioned and receipt-pinned with the rules that use it, instead of engine code. The TILA pack now computes the rescission deadline it could previously only certify.

### Authoring

**DMN decision-table compiler.** DMN 1.3+ tables compile into the rule IR; the kernel cannot tell the result from a hand-written pack. Deliberately narrow — S-FEEL cells only, three of seven hit policies, a mandatory citation and effective date on every row. It refuses rather than approximates: an uncited row is a compile error, not an invented `TODO(verify)`.

*The acceptance criterion was unachievable as written.* It demanded a DMN-authored pack produce "the same decision **and receipt**" as its IR equivalent. A receipt pins its pack's name and version, so two packs are two identities and the hashes cannot match. What is proven instead — same decision, same rules fired in the same order, same defeat chains, same input facts — is asserted alongside the difference, which a test pins as precisely as the agreement.

*And the proof is fixture-bounded.* Perturbing a compiled rule from `> disclosed` to `>= disclosed` leaves the whole equivalence suite green, because the two differ only when the amounts are exactly equal and no committed fixture reaches that boundary. A perturbation the fixtures can see fails 10 of 12 tests. This is what motivated pack equivalence in the verifier below.

**Pack-owned decision phrasing.** A decision's verdict wording moved from `demo/app.py` into the pack, alongside the `question` a pack already declared. Every determination the demo can render is byte-identical before and after — the wording moved without a word of it changing.

**Rule-ID convention, with the existing ids grandfathered.** Nothing was renamed: `NY-NR-45` sits in 76 golden receipts, and a receipt is not editable. The argument is that **a rule id is a handle, not a claim** — everything an id is tempted to encode (statute, date, threshold, jurisdiction) already has a correctable home on the rule, and the id does not. All 46 existing ids are exempt by an explicit committed list; 17 would fail the convention today.

### Static assurance

**Z3 static pack verifier.** Per same-priority rule pair: `PROVED-DISJOINT`, `NOT-PROVED` with a concrete witness, or `OUT-OF-FRAGMENT` naming the construct it declined to encode. Also reports uncovered input regions per decision attribute. Across six packs: 25 proved disjoint, one genuine overlap (correct — a registered eNote *is* a promissory note, which is why `PKG-NOTE-31 overrides PKG-NOTE-30`), nine uncovered regions, all intended and now witnessed. It discharges two TILA disjointness claims that previously lived only in code comments, one over a deadline the pack computes with its own calendar.

`validate_pack` is deliberately **not** relaxed, so the kernel's proof set stays small enough to audit by reading. A consequence worth stating: because the validator already refuses any pack with an unproven same-priority overlap, `prove` cannot meet one in a committed pack — its non-zero exit is a differential check between two proof systems, not a routine gate.

**What-if queries** (a v1.2 item, pulled forward). Free one input of a decided case and solve the pack backwards. The contract is that **the solver proposes and the kernel disposes**: every answer is re-adjudicated through the real kernel, extremals are boundary-verified, and a solver/kernel disagreement raises with both artifacts rather than returning an answer. A committed broken encoding proves that guard trips — and proves why answer-checking alone is insufficient, since the kernel *confirms* the wrong date the broken encoding produces. Only the boundary check catches it.

It reuses the verifier's SMT encoding with zero edits; a test asserts class identity so divergence must be deliberate.

### Reference wiring

**OR-Tools closing scheduler**, the first resident of `examples/`. CP-SAT plans sign → fund → record to the earliest feasible dates. Every hard constraint is a table of days an adjudication actually permitted; the only constraints the scheduler writes itself are availability. Each chosen date cites the receipt ids that constrained it.

The demonstration is the funding date: compliance opens **Saturday** 2026-02-21, because Saturdays are business days under the precise § 1026.2(a)(6) calendar — the rule schedulers get wrong — and the wire desk is closed Saturdays, so the plan says Monday. Two constraints, two owners, and the output names which one bound the date. The separation is checked by mutation: move the TILA pack from three business days to five and the plan moves with `schedule.py` untouched.

### Infrastructure

**The marker-gated suites now run.** `linkml`, `z3`, and `docling` tests had never executed in CI — the main job runs `pytest` with no extras and no marker selection, so all three were silently skipped. They now run in their own workflow, path-filtered so a rule-pack PR pays nothing for them, plus every merge to main and a weekly cron. The `linkml` one mattered most: its whole job is checking the ontologies against real tooling, and the hot-path validator would have gone on passing while the files drifted out of spec.

### What this milestone changed about the mental model

Three claims in [the architecture guide](docs/neuro-symbolic-architecture.md) were sharpened by the work rather than merely updated:

- **Pack identity is inside the hashed body**, so two packs are two identities even when they encode the same rules. Equivalence between rulebases is therefore a claim about *decisions*, and has to be tested at that level.
- **Between "reproducible" and "true" sits "internally consistent"** — a property duly could not previously claim, because the validator could only say "I cannot prove these disjoint," which is a statement about the validator rather than the rules.
- **"Keep actions outside the kernel" is only half a boundary.** An integration can respect it perfectly at the API level and still hold a second copy of the rule ten lines away, invisible at the seam because the seam still looks correct. It is detectable only by mutation.

And one distinction the contribution work forced: **a rule pack has two halves.** The deciding half reaches the receipt and is frozen. The speaking half — the question, the phrasing — is authored by the same expert in the same file and must never enter a hashed body, because a wording improvement that invalidated 351 receipts would make the wording unimprovable. Governance and identity are not the same boundary.

## v0.3.0 — M3: extraction and review

Extraction adapter protocol with a Docling implementation, content-addressed run envelopes, pack-level abstention policy with confidence floors, the review queue, and calibration mathematics (deliberately unfitted — labels arrive from review). Human corrections re-enter as first-class facts and auto-become golden regression cases. Six rule packs across insurance and mortgage closing.

## v0.2.0 — M2: replay and regression

Append-only bitemporal fact store, the replay verifier, the golden corpus, and rule-change impact analysis wired into CI.

## v0.1.0 — M0/M1: the contract and the first vertical slice

The grounded-fact and decision-receipt specs, JSON Schemas, the rule IR, the reference kernel, the audit-report renderer, and the interactive demo.
