# The grounded fact contract — v0 draft

This document is the seam between the neural and symbolic halves of a duly system. It defines two artifacts:

- **GroundedFact** — a single typed assertion proposed by an extractor (or a human), carrying its source span, its confidence, and its temporal validity. Facts flow *into* the fact store.
- **DecisionReceipt** — the output of an adjudication: a conclusion plus the complete derivation that produced it, pinned to exact fact and rule versions. Receipts flow *out of* the kernel.

Schemas: [`schemas/grounded-fact.schema.json`](schemas/grounded-fact.schema.json), [`schemas/decision-receipt.schema.json`](schemas/decision-receipt.schema.json).
Worked examples: [`examples/`](examples/). Run `uv run spec/validate.py` from the repo root to check examples against schemas (after `uv sync`).

Everything below is a design decision with its rationale and the alternative that was rejected. This spec is being developed code-first; expect breaking changes until a vertical slice runs end to end.

---

## D1. Facts are atomic entity–attribute–value assertions

A fact asserts one attribute of one entity: *(entity `notice:HO-77401-NY:2026-07-25`, attribute `nc:noticeMailedDate`, value 2026-07-25)*. Complex records decompose into multiple facts sharing an entity id.

**Why:** atomic facts ground directly into Datalog relations, diff cleanly, supersede independently, and carry per-assertion confidence — a document AI extractor is often sure about the fee amount and unsure about the fee category, and one confidence score per nested record cannot express that.

**Rejected:** nested record facts (one fact = one extracted form section). Records force whole-record supersession and whole-record confidence, and they push schema shape into the contract, which belongs to the user's ontology.

## D2. Values are typed; numbers are decimal strings; money carries currency

The value union: `string`, `decimal`, `money`, `date`, `datetime`, `boolean`, `code` (a coded value with its code system), and `entityRef` (a link to another entity). Decimals and money amounts are strings matching `^-?\d+(\.\d+)?$` — never JSON floats.

**Why:** the flagship use cases are notice-period date arithmetic and premium or fee amounts. Binary floating point is not acceptable where amounts must reconcile exactly under audit. `code` exists because regulated ontologies are full of enumerations (fee categories, document types) whose meaning depends on the issuing code system and its version.

## D3. Every fact says where it came from: a span or an attestation

Grounding is a discriminated union:

- **document** — document id + SHA-256 of the document bytes, the rendition it was read from (see D4), and a locator: character span, bounding box, or both. An optional `quote` carries the source text so receipts can render without document access.
- **attestation** — a human actor, a channel ("phone call with closing agent"), and a timestamp, for facts that exist in no document.

**Why:** the receipt must cite clause-level provenance, so provenance is mandatory at the fact level — it cannot be reconstructed later. Attestation is included because real files always contain a fact someone was told; forcing those into fake document spans would corrupt the provenance story precisely where it matters.

**Rejected:** optional provenance. A fact with no grounding is exactly the confident-wrongness failure mode this architecture exists to eliminate.

## D4. Spans reference a hashed document rendition

Character offsets are meaningless against "the PDF" — every extractor produces different text from the same bytes. A span therefore points at a **rendition**: an immutable, stored artifact (extractor name + version + the extracted text/layout itself, content-addressed) derived from the hashed source document. Offsets are defined against the rendition, and the rendition is retained as long as the facts derived from it.

**Why:** this is the difference between provenance that replays and provenance that rots. Re-running a newer extractor produces a new rendition and new facts; old receipts still resolve against the old rendition.

## D5. Confidence is a calibrated score plus its method; abstention is policy, not data

A machine-asserted fact carries `confidence: {score, method}` where method ∈ `raw | temperature | platt | conformal`. The fact does **not** carry an "abstained" flag: abstention thresholds are adjudication policy, versioned with the rule pack, applied by the kernel at decision time.

**Why:** the same fact may clear the threshold for one decision and not another, and thresholds change as calibration improves. Baking the policy outcome into the fact would make historical replay lie. Conformal calibration is first-class in the enum because distribution-free abstention guarantees ("when we don't abstain, error ≤ X%") are the claim regulated buyers actually want.

## D6. Bitemporal from birth

Two independent time axes:

- **Effective time** (`effectiveFrom` / `effectiveTo`, on the fact): when the assertion is true in the world — a premium quote has a good-through date; a policy endorsement applies from its effective date.
- **Knowledge time** (`recordedAt`, on the record): when the system learned it. Assigned by the store, append-only, never edited.

Every adjudication runs against an explicit `asOf` pair, and the receipt records both.

**Why:** "evaluate a March file under March rules, as we understood the facts in March" is the defining query of regulated replay, and it needs both axes. Retrofitting bitemporality onto a unitemporal store is a rewrite; carrying two timestamps from day one is nearly free.

## D7. Facts are immutable; corrections supersede

No fact is ever edited. A correction is a new fact with `supersedes: <old fact id>`; the old fact's status becomes `superseded` (or `retracted` when withdrawn without replacement) as a store-level projection, not a mutation of the original record.

**Why:** immutability is what makes knowledge-time replay trivial and audit trails trustworthy. The supersession chain *is* the correction history.

## D8. Facts are content-addressed

`contentHash` = SHA-256 over the RFC 8785 (JCS) canonical JSON of the fact, excluding `id` and `contentHash` themselves. The fact id is `urn:duly:fact:sha256:<hex>`.

**Why:** receipts pin their inputs by hash, so replay integrity is checkable byte-for-byte, identical facts deduplicate for free, and no id-issuing authority is needed across systems.

## D9. Human and machine assertions share one shape

`assertion.kind` is `machine` (with extractor name/version/model/run) or `human` (with actor id and role). Nothing else differs. That humans outrank machines on conflict is kernel policy — versioned and replayable — not schema.

**Why:** the review-queue loop only closes cheaply if a human correction is just another fact. A separate "correction" type would fork every downstream consumer.

## D10. Ontology by reference

Every fact carries `schemaRef: {ontology, version}` and its `attribute` / entity `type` are CURIEs resolved against that ontology (MISMO, ACORD, FHIR, or project-local). duly validates conformance (SHACL/LinkML gate, planned) but defines no domain terms.

---

## Decision receipts

The receipt is the product. Its schema mirrors the commitments above:

- **`asOf`** — the effective/knowledge pair the decision was evaluated at (D6).
- **`rulePack`** — name, version, and git commit of the exact rulebase (rules are code).
- **`rulesFired`** — each rule with its version, its legal `citation` (text + URL), its priority, and — because the rule IR is defeasible — the list of rules it **`defeated`**. When an exception overrides a default, the receipt says so explicitly; that is the non-monotonic story made auditable.
- **`derivation`** — a tree: each node is a conclusion, the rule that produced it, and its premises (input fact ids or sub-derivations). Rendering this tree as prose is the audit report.
- **`inputFacts`** — every consumed fact pinned by id + contentHash (D8), so replay can verify inputs byte-for-byte.
- **`abstentions`** — attributes the decision needed but declined to use (missing, below confidence policy, or conflicting), with routing. Abstention appears on the receipt, not on the fact (D5).
- **`engine`** — kernel version and backend, because "deterministic" is a claim about a specific engine.

Receipts are content-addressed the same way facts are (`receiptSha256`, JCS canonical form excluding `id` and `receiptSha256`).

## Relationship to standards

- **PROV-O** — a JSON-LD context mapping facts and receipts onto `prov:Entity` / `prov:Activity` / `prov:wasDerivedFrom` is planned; the field structure was chosen so this mapping is lossless.
- **SHACL / LinkML** — the ontology conformance gate facts pass through before entering the store; LinkML is the intended source language so one definition yields JSON Schema, SHACL, and dataclasses.
- **DMN** — a compliance-editable authoring surface that compiles to the same rule IR; receipts are identical regardless of authoring surface.

## Open questions

1. **Span portability** — should `charSpan` offsets be defined in Unicode code points (chosen for now) or UTF-8 bytes? Code points are friendlier to Python/JS consumers; bytes are friendlier to Rust and hashing.
2. **Conflict representation** — when two live facts assert different values for the same entity/attribute at the same effective time, is the conflict detected purely by the kernel, or should the store reject on write? Current lean: kernel-detected, surfaced as an abstention with reason `conflict`.
3. **Fact-level access control** — closing packages contain PII; `quote` duplication (D3) makes redaction harder. Possibly a `sensitivity` tag per fact.
4. **Batch envelope** — extractors emit many facts per document; a signed envelope (extraction run manifest) would let a whole run be verified or revoked at once.
