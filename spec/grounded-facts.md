# The grounded fact contract — v0 draft

This document is the seam between the neural and symbolic halves of a duly system. It defines three artifacts:

- **GroundedFact** — a single typed assertion proposed by an extractor (or a human), carrying its source span, its confidence, and its temporal validity. Facts flow *into* the fact store.
- **DecisionReceipt** — the output of an adjudication: a conclusion plus the complete derivation that produced it, pinned to exact fact and rule versions. Receipts flow *out of* the kernel.
- **ExtractionRunEnvelope** — the manifest of one extraction run: the adapter, the source document hash, the rendition hash, and the ordered fact ids the run proposed, content-addressed as a unit so a whole run can be verified or revoked at once (resolved question 4).

Schemas: [`schemas/grounded-fact.schema.json`](schemas/grounded-fact.schema.json), [`schemas/decision-receipt.schema.json`](schemas/decision-receipt.schema.json), [`schemas/extraction-run.schema.json`](schemas/extraction-run.schema.json).
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

The canonical form is one implementation, [`duly_core`](../core/duly_core/__init__.py), and one set of committed answers: [`spec/canonical-vectors.json`](canonical-vectors.json) gives eleven `(document, canonical bytes, digest)` triples that **any** implementation in any language must reproduce, including the two cases every implementation gets wrong — RFC 8785 orders object keys by *UTF-16 code unit*, not code point (Python's `sort_keys=True` is the latter and differs above the BMP), and non-ASCII is emitted raw rather than `\u`-escaped. `spec/make_canonical_vectors.py` regenerates them; `core/tests/test_canonical_vectors.py` re-derives the RFC's properties independently, because vectors generated from an implementation can only prove it has not *changed*.

**Why:** receipts pin their inputs by hash, so replay integrity is checkable byte-for-byte, identical facts deduplicate for free, and no id-issuing authority is needed across systems.

## D9. Human and machine assertions share one shape

`assertion.kind` is `machine` (with extractor name/version/model/run) or `human` (with actor id and role). Nothing else differs. That humans outrank machines on conflict is kernel policy — versioned and replayable — not schema.

**Why:** the review-queue loop only closes cheaply if a human correction is just another fact. A separate "correction" type would fork every downstream consumer.

## D10. Ontology by reference

Every fact carries `schemaRef: {ontology, version}` and its `attribute` / entity `type` are CURIEs resolved against that ontology (MISMO, ACORD, FHIR, or project-local). duly validates conformance — the reference resolves against a versioned LinkML artifact and the fact's entity type, attribute, value kind, and code values are checked against it ([ontology-conformance.md](ontology-conformance.md), gate in `conformance/duly_conformance`) — but defines no domain terms.

---

## Decision receipts

The receipt is the product. Its schema mirrors the commitments above:

- **`asOf`** — the effective/knowledge pair the decision was evaluated at (D6).
- **`rulePack`** — name, version, and git commit of the exact rulebase (rules are code).
- **`rulesFired`** — each rule with its version, its legal `citation` (text + URL), its priority, and — because the rule IR is defeasible — the list of rules it **`defeated`**. When an exception overrides a default, the receipt says so explicitly; that is the non-monotonic story made auditable.
- **`derivation`** — a tree: each node is a conclusion, the rule that produced it, and its premises (input fact ids or sub-derivations). Rendering this tree as prose is the audit report.
- **`inputFacts`** — every consumed fact pinned by id + contentHash (D8), so replay can verify inputs byte-for-byte.
- **`abstentions`** — attributes the decision needed but declined to use (missing, below confidence policy, or conflicting), with routing. Abstention appears on the receipt, not on the fact (D5).
- **`engine`** — engine identity: kernel name, its **decision-semantics version**, and backend, because "deterministic" is a claim about a specific engine. The version is the semantics' own — pinned as `SEMANTICS_VERSION`, deliberately not the `duly_kernel` package version or the distribution version, which move with releases while sealed receipts cannot ([docs/release-process.md](../docs/release-process.md)).

Receipts are content-addressed the same way facts are (`receiptSha256`, JCS canonical form excluding `id` and `receiptSha256`).

## Relationship to standards

- **PROV-O** — a JSON-LD context mapping facts and receipts onto `prov:Entity` / `prov:Activity` / `prov:wasQuotedFrom` and friends is specified in [prov-o.md](prov-o.md) and shipped in [contexts/](contexts/). The mapping is deliberately partial, not lossless: bitemporal effective time, confidence, and abstentions have no faithful PROV equivalent and stay in the `duly:` namespace (prov-o.md, P8).
- **SHACL / LinkML** — the ontology conformance gate at the ingestion seam, specified in [ontology-conformance.md](ontology-conformance.md) and shipped in `conformance/duly_conformance` with sample artifacts in `ontologies/`. LinkML is the source language — one definition yields SHACL (via LinkML's generator, exercised in marker-gated tests) while the enforcing validator interprets a documented pure-Python subset.
- **DMN** — a compliance-editable authoring surface that compiles to the same rule IR; receipts are identical regardless of authoring surface.

## Resolved questions

1. **Span encoding** — `charSpan` offsets are Unicode code points, end-exclusive, defined against the rendition text (see the schema). Friendlier to Python/JS consumers; a byte-offset representation can be added as an alternate locator if a backend needs it.
2. **Conflict resolution** — conflicts (two live facts asserting the same entity/attribute) are detected by the kernel at evaluation time; the store accepts both writes (immutability, D7, means nothing is lost by admitting a conflict). Resolution policy: if **exactly one** of the conflicting facts is human-asserted, it outranks the machine assertions and binds — this is what makes the review-queue loop (D9) work without mutating history. Any other mix — machine vs. machine, or multiple humans — is unresolvable by rank and becomes an abstention with reason `conflict` on the receipt. Supersession (D7) remains the *durable* correction mechanism; outranking is the evaluation-time behavior when a correction and its target are both live.
3. **PII sensitivity** — facts carry an optional `sensitivity` field (`public` | `internal` | `pii`). Renderers must redact the `quote` of a `pii` fact in human-facing output while preserving the document reference, span, and content hash — the evidence chain survives redaction. The default (absent field) is `internal`.

4. **Batch envelope** (deferred from M0, resolved in M3) — an extraction run emits one **envelope** per rendition: a manifest `{runId, adapter{name, version, modelId?}, documentId, documentSha256, rendition{id, sha256}, createdAt, factIds[]}` where `factIds` is the ordered, complete list of facts the run proposed and `rendition.sha256` is the SHA-256 of the rendition text's UTF-8 bytes — the content address D4 promised the rendition would have. The envelope is content-addressed exactly like facts (D8: SHA-256 over the JCS canonical form excluding `id` and `contentHash`; id = `urn:duly:run:sha256:<hash>`), so consumers can verify a whole run before ingesting — manifest hash, every fact's hash, every span against the rendition — and revoke a whole run at once by retracting every live fact carrying its `runId` (retraction is an event, never a deletion, per D7). "Signed" at this stage means that integrity hash: tampering with the manifest, any fact, or the rendition is detectable, but there is no authenticity claim about *who* produced the run — asymmetric signatures are the open question below. **Why one envelope per rendition rather than per case or per batch:** the rendition is the unit of span validity (D4) and the document hash is the unit of source integrity (D3); a run over several documents emits several envelopes. **Rejected:** per-fact signatures (N artifacts per document and no way to assert "this run is complete — nothing was dropped"), and embedding run membership in the fact beyond `runId` (facts are already content-addressed; run membership is the envelope's job, and moving it into the fact would change every fact hash whenever the run's membership was corrected). Schema: [`schemas/extraction-run.schema.json`](schemas/extraction-run.schema.json); example: [`examples/envelopes/envelope-decpage-run.json`](examples/envelopes/envelope-decpage-run.json) (kept in a subdirectory so fact-fixture tooling globbing `examples/*.json` is unaffected); producer and consumer: [`extraction/duly_extraction/`](../extraction/duly_extraction/).

## Open questions

1. **Envelope signatures** — asymmetric signatures over the envelope's canonical bytes (an optional `signatures` array carrying algorithm, key id, and value) would add authenticity — *who* ran the extraction — on top of the integrity hash resolved question 4 provides. Deferred until a deployment needs cross-organization trust: key distribution and rotation are a heavier commitment than any current consumer justifies, and the canonical-bytes convention means adding signatures later breaks nothing.

2. **Must a review-queue correction supersede the below-floor fact it rules on?** Today `duly_review` accepts either form: a correction that `supersedes` the abstained machine fact (which then stops being live, so future receipts carry no entry for it), or a coexisting human fact that merely outranks it (resolved question 2). The coexisting form leaves the below-floor fact live, so every future receipt carries a persistent `low_confidence` entry even though the attribute binds via the human fact — which bends this spec's definition of `abstentions` ("attributes the decision needed but declined to use": the attribute *was* used), and is why the golden-case converter tests bindability rather than entry absence.
   *The case for requiring supersession (on `low_confidence` items only):* resolving a queue item is, by construction, a ruling on that specific fact — supersession is the truthful record of that act, it makes the bent receipt state unrepresentable rather than worked around, and it ties calibration labels to the machine fact structurally (the `supersedes` link) instead of via store-history lookup at resolve time. Nothing is lost: the superseded fact, its score, and the chain survive in history and in knowledge-time replay. Enforcement would sit at the *queue* boundary — the store must keep accepting independent human facts (a value known from a phone call is not a ruling on an extraction), and the queue would stamp `supersedes` from the entry's fact id itself rather than trust callers.
   *The costs:* store custody becomes a precondition (you cannot supersede a fact the store never held — true in the envelope-ingest pipeline, not yet true of the demo's from-disk facts), and future receipts lose the standing "a below-floor extraction exists here" marker (historical receipts and knowledge-time replay retain it).
   *Also open within this question:* whether the requirement is a hard invariant of what "resolve" means or a pack-versioned policy knob (a knob would reintroduce the bent state under configuration), and whether `conflict` items — whose entries carry multiple facts — get an analogous rule. Not yet decided; the current dual behavior stands until it is.
