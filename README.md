```text
██████╗ ██╗   ██╗██╗  ██╗   ██╗
██╔══██╗██║   ██║██║  ╚██╗ ██╔╝
██║  ██║██║   ██║██║   ╚████╔╝
██║  ██║██║   ██║██║    ╚██╔╝
██████╔╝╚██████╔╝███████╗██║
╚═════╝  ╚═════╝ ╚══════╝╚═╝
```

**Auditable document decisioning for regulated workflows.**

*duly* — as in duly authorized, duly recorded, duly noted: in accordance with proper procedure. 

duly is an open-source toolkit for building neuro-symbolic document-decisioning systems: a neural layer reads unstructured documents and *proposes* structured facts; a deterministic symbolic layer applies a versioned, effective-dated rulebase to *decide* what those facts mean. Perception proposes, logic disposes. Every conclusion arrives with the rule that fired, the fact it fired on, and the clause the fact came from — an answer plus a receipt.

## The problem

In regulated domains — insurance manuscripts, mortgage closing packages, healthcare claims, KYC files, customs declarations — reading the documents was never the hard part. The hard part is that every conclusion must be:

- **defensible** to a regulator or auditor, citing the exact rule and the exact source text;
- **reproducible** months or years later, byte-for-byte;
- **evaluated under the rules as they stood** on the transaction date, not today's rules.

A model that is right 95% of the time and cannot show its work is unusable here, because the output isn't the answer — it's the answer plus an auditable chain. And the expensive failure mode isn't being wrong; it's being *confidently* wrong. The architecture duly supports converts confident wrongness into explicit abstention routed to a human.

The individual pieces of this architecture already exist as open source: Datalog engines, document AI, rules-as-code DSLs, graph stores, provenance vocabularies. What doesn't exist is the **seam** — a standard for how a probabilistic extractor hands facts to a deterministic reasoner with source spans, calibrated confidence, abstention semantics, and bitemporal versioning intact, plus a kernel that can replay any decision as of any date. Today, every team building one of these systems writes that layer themselves.

duly is that seam.

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="duly architecture: documents flow through neural extraction adapters into the grounded fact contract, then a bitemporal fact store, adjudication kernel, and decision receipt; a review queue handles abstentions, rule packs feed the kernel, and an assurance harness replays receipts" width="680">
</p>

Everything above the contract is probabilistic and replaceable; everything below it is deterministic and replayable. Extractors and models can be swapped at the contract line without touching the reasoning layer — the approach OpenTelemetry took for telemetry: standardize the interchange format, ship adapters, and let the ecosystem form around the format rather than around any single engine.

| Piece | What it is | Status |
|---|---|---|
| [Grounded fact contract](spec/grounded-facts.md) | The interchange format: facts with provenance, confidence, and bitemporal fields; decision receipts with derivation trees | **drafting** |
| Rule IR + compilers | Defeasible rules (priority + unless + citation + effective window) compiled to stratified Datalog | next up |
| Adjudication kernel | Deterministic as-of evaluation over a bitemporal fact store, emitting receipts | not started |
| Extraction adapters | Document AI providers (Docling, Azure DI, Google Document AI, Textract, VLM + constrained decoding) emitting contract-conformant facts | not started |
| Review queue | Abstention routing; human corrections re-enter as first-class facts | not started |
| Assurance harness | Replay verifier, golden-set CI, rule-change impact analysis | seed exists ([validate.py](spec/validate.py)) |
| Starters | Complete vertical slices; first: cancellation/nonrenewal notice compliance for personal lines | example data exists |

## Design choices and why

### Why neuro-symbolic at all

Pure-LLM approaches improve with every model release, and for most document work they are the right choice. duly targets the workflows where the requirement isn't capability but accountability:

- **The audit trail is a byproduct of evaluation.** A rules engine reports which rule fired on which fact from which clause. Prompted explanations cannot provide this, because a model's stated reasoning is not its actual reasoning.
- **Rule changes are code changes, not ML projects.** When a regulation changes, you edit a rule, version it, effective-date it. Nothing retrains; nothing silently regresses elsewhere.
- **Long-tail coverage without long-tail data.** You encode a county's recording rule once instead of collecting three hundred labeled examples of it — decisive when the tail is thousands of jurisdictions with a handful of files each.
- **Failure is legible.** The system can say "insufficient grounded facts" and route to a human, converting the expensive failure mode (confident wrongness) into a manageable one (abstention).

This approach carries known risks: it assumes regulators will continue to require determinism and provenance rather than accepting model output directly, and it inherits the classic expert-systems problem that knowledge engineering never ends. Both risks shape the roadmap — the ontology is bring-your-own, and the starting point is one narrow vertical slice rather than a comprehensive knowledge graph.

### Why the focus on the seam

Engines are replaceable; interchange formats compound. Datalog engines, document parsers, and graph stores all exist and keep improving. The glue between them is where implementations diverge and break: how confidence survives the handoff, how a span stays resolvable after the extractor upgrades, how a decision made in March stays replayable in November. Standardizing that layer is where a neutral open-source project adds the most value, and it is not a layer any single vendor is positioned to define.

### Why facts are atomic, typed, and content-addressed

A fact is one entity–attribute–value assertion with mandatory grounding (a document span or a human attestation), a calibrated confidence, and two time axes. Atomic facts ground directly into Datalog relations and carry per-assertion confidence — an extractor is often sure about a notice's mailing date and unsure about its stated ground for termination, and one score per record can't express that. Money is decimal strings, never floats: binary floating point is not acceptable where amounts must reconcile to the cent under audit. Facts are content-addressed (RFC 8785 canonical JSON + SHA-256), so receipts pin their inputs by hash and replay integrity is checkable byte-for-byte. Full rationale, decision by decision, in [the spec](spec/grounded-facts.md).

### Why bitemporal from birth

"Evaluate a March file under March rules, as we understood the facts in March" is the defining query of regulated replay, and it needs two independent time axes: *effective time* (when a fact or rule applies in the world) and *knowledge time* (when the system learned it). Retrofitting bitemporality onto a unitemporal store is a rewrite; carrying two timestamps from day one is nearly free. Facts are immutable — corrections supersede, and the supersession chain *is* the correction history.

### Why a defeasible IR compiled to stratified Datalog

Real rulebases are defaults and exceptions all the way down ("standard tolerance applies *unless* the fee is in the 10% bucket *unless* a changed circumstance reset the baseline"). Full answer-set programming handles this natively, but at a cost that is hard to justify in v1: the learning curve for contributors is steep, ASP explanation tooling remains immature — a serious problem when the receipt is the primary output — and multiple answer sets complicate the determinism guarantee. Plain Datalog has the opposite problem: hand-encoded exception plumbing makes rule packs hard to read and review.

duly follows the approach [Catala](https://catala-lang.org/) established for computational law: rules carry `priority` and `unless` metadata *declaratively in the IR*, and the compiler mechanically lowers them to stratified Datalog. Authors get explicit exception semantics; the engine stays deterministic; receipts show which rule **defeated** which, making the non-monotonic reasoning itself auditable. A clingo backend can be added later for rule fragments that genuinely need it, without changing any rule pack.

### Why bring-your-own ontology

duly ships no domain schema. MISMO, ACORD, FHIR, and FIBO already exist, and building a new domain ontology is a large undertaking that has stalled many efforts in this space. Facts reference the user's ontology by CURIE + version; duly validates conformance (SHACL/LinkML gate, planned) but defines no domain terms. This boundary also contains the knowledge-engineering burden: duly's core never grows domain knowledge, so it never accumulates domain debt.

### Why code-first

Specifications that develop ahead of running code rarely get adopted. The contract is being developed against a real vertical slice (termination-notice compliance), and it will be stabilized only once that slice runs end to end. Until v1.0, breaking changes are expected.

### What duly deliberately is not

- **Not a knowledge graph platform.** Graph projections (SPARQL over Oxigraph/RDFox) come when cross-document reasoning genuinely demands them, not before.
- **Not an orchestration framework.** LangGraph, Temporal, and friends compose around duly; integration examples only.
- **Not a UI product.** The review queue ships as an API with defined queue semantics; review interfaces vary too much across organizations to standardize, and are left to integrators.
- **Not an extraction model.** Adapters wrap the extractors you already use; duly's job starts at the contract line.

## The target demonstration

The milestone that validates the architecture end to end: run a decision, change one rule's effective date, and replay. The outcome changes, and the receipt shows exactly why — which rule fired, which rule it defeated, and which clause of which document each input fact came from.

## Roadmap

Sequencing principle: build nothing until its consumer exists. Each milestone ends in something demonstrable.

### M0 — the contract (in progress)
- [x] Grounded fact spec: ten design decisions with rationale ([spec/grounded-facts.md](spec/grounded-facts.md))
- [x] JSON Schemas for `GroundedFact` and `DecisionReceipt`
- [x] Worked example with real content hashes: New York nonrenewal notice-period check (N.Y. Ins. Law § 3425)
- [x] Validator: schema + hash + referential-integrity checks
- [ ] Resolve open questions: span encoding, conflict handling, PII sensitivity tags, batch envelopes

### M1 — end-to-end vertical slice
- [ ] Rule IR: defeasible rules with priority, unless, legal citation, and effective window
- [ ] Reference interpreter (pure Python, optimized for derivation-trace quality, not speed)
- [ ] Notice-compliance starter end to end, first state New York: sample dec page + termination notice → facts → adjudication → receipt
- [ ] Receipt renderer: derivation tree → human-readable audit report
- [ ] First end-to-end run of the target demonstration

### M2 — replay and regression
- [ ] Bitemporal fact store on Postgres (append-only events, as-of queries)
- [ ] Replay verifier: re-run any receipt, assert byte-identical output
- [ ] Golden-set runner; human corrections auto-become regression cases
- [ ] Rule-change impact analysis in CI: a rule PR gets a comment — "this change flips N of M historical decisions, here are five before/after receipts"
- [ ] Two or three additional state rule packs (different notice periods, grounds, and delivery requirements) to exercise jurisdictional variation and effective-dating

### M3 — extraction and review
- [ ] Extraction adapter interface + Docling adapter + one commercial adapter (Azure DI or Google Document AI)
- [ ] Calibration module (temperature/Platt/conformal) with abstention policy hooks
- [ ] Review queue API: abstention routing, human facts re-entering the store

### M4 — backends and standards alignment
- [ ] Soufflé backend for large fact volumes; Z3/OR-Tools for arithmetic and timing constraints
- [ ] DMN decision-table authoring surface compiling to the same IR (compliance edits without a deploy)
- [ ] SHACL/LinkML ontology conformance gate
- [ ] PROV-O JSON-LD context for facts and receipts

### v1.0 — specification stability
- [ ] Spec freeze with versioning policy
- [ ] Second starter vertical: claims coverage determination against a synthetic manuscript — grant → exclusion → exception chains as a full defeasible-reasoning showcase
- [ ] Rule-pack authoring guide and contribution pipeline

## Contribution model

The project is structured so that the two largest contribution surfaces sit at the edges of the contract, where domain knowledge matters more than familiarity with the core:

- **Rule packs** — domain experts (analysts, lawyers, compliance engineers) contribute versioned, cited, effective-dated rules for their jurisdiction or program. [OpenFisca](https://openfisca.org/)'s country packages demonstrate that this contribution model works.
- **Extraction adapters** — vendors and users of a given document AI service can maintain its adapter independently, the way observability vendors maintain OpenTelemetry exporters.

A small core maintains the specification and kernel; the edges grow with the ecosystem.

## Relationship to prior art

duly stands on, and deliberately does not rebuild: [OpenFisca](https://openfisca.org/) (rules-as-code with effective-dated parameters), [Catala](https://catala-lang.org/) (default logic for statutes — the IR's direct inspiration), [Docling](https://github.com/docling-project/docling) (document parsing), [Outlines](https://github.com/dottxt-ai/outlines) (schema-constrained decoding), [Soufflé](https://souffle-lang.github.io/) / [clingo](https://potassco.org/clingo/) / [Z3](https://github.com/Z3Prover/z3) (evaluation backends), [XTDB](https://xtdb.com/) (bitemporality as default), [PROV-O](https://www.w3.org/TR/prov-o/) and [SHACL](https://www.w3.org/TR/shacl/) (provenance and validation vocabularies), and [DMN](https://www.omg.org/dmn/) (business-editable decision tables). What none of them cover is the seam between perception and adjudication — that is duly's entire scope.

## Status

Pre-alpha, M0. The [grounded fact contract](spec/grounded-facts.md) is drafted and its examples validate:

```bash
uv sync
uv run spec/validate.py
```

Feedback on the spec's [open questions](spec/grounded-facts.md#open-questions) is the most useful contribution right now.

## License

[Apache-2.0](LICENSE)
