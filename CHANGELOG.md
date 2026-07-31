# Changelog

What each release turned out to mean. The [roadmap](README.md#roadmap) says what is planned and what is done; this file says what was learned doing it — the boundaries that moved, the claims that were corrected, and the things that could not be done honestly.

Entries are written after the fact, from merged work.

**These versions are git tags marking milestones, not package releases.** `pyproject.toml` deliberately stays at `0.0.1`: nothing is published, and [installable distribution](README.md#roadmap) is an M5 item. A tag says "this milestone is done and here is what it meant" — it does not say the contract is stable. The fact, receipt, and IR contracts are v0 and may break until v1.0.

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
