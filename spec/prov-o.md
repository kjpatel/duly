# PROV-O alignment — v0 draft

The [grounded fact contract](grounded-facts.md) promised its field structure was chosen so a PROV-O mapping would be lossless. This document is that mapping made concrete: versioned JSON-LD 1.1 contexts in [`contexts/`](contexts/) under which the stored JSON documents — GroundedFacts, DecisionReceipts, ExtractionRunEnvelopes — are valid JSON-LD that expands to meaningful [PROV-O](https://www.w3.org/TR/prov-o/) triples, so RDF/SPARQL consumers can ingest duly provenance without a bespoke importer.

Contexts: [`contexts/grounded-fact.context.jsonld`](contexts/grounded-fact.context.jsonld), [`contexts/decision-receipt.context.jsonld`](contexts/decision-receipt.context.jsonld), [`contexts/extraction-run.context.jsonld`](contexts/extraction-run.context.jsonld). Exporter: [`kernel/duly_kernel/provo.py`](../kernel/duly_kernel/provo.py). Expansion tests against committed examples and golden receipts: [`kernel/tests/test_provo.py`](../kernel/tests/test_provo.py). Structural checks: `uv run spec/validate.py`.

As with the fact contract, everything below is a design decision with its rationale and the alternative that was rejected.

---

## P1. The context is external; stored documents do not change by a byte

Facts, receipts, and envelopes are content-addressed (D8): the id *is* the hash of the canonical bytes. Adding an `@context` key into a stored document would change every hash and break replay — so no stored document ever carries one. The context is a standalone, versioned artifact applied in one of two ways:

- **Out-of-band** — JSON-LD 1.1 lets a consumer supply a context externally (the `expandContext` option of expansion). Applied to the raw stored document, this yields the full entity-level graph: derivations, quotations, attributions, revisions.
- **Export wrapper** — `as_jsonld(doc, kind)` returns a *new* dict wrapping the stored fields with an `@context` URL reference, `@id`, `@type`, and the derived PROV nodes listed in P6 that a context cannot mint (contexts map keys to IRIs; they cannot invent nodes). The input is never mutated; every stored field except `id` — carried as `@id`, to which the context aliases it — survives byte-for-byte.

**Rejected:** embedding `@context` in stored documents (breaks content addressing); a bespoke RDF exporter with no context artifact (consumers holding only stored JSON could produce no triples; the context makes the stored documents themselves the interchange format, which is the whole point of the contract).

## P2. The fact is a `prov:Entity`; its nested provenance lifts to fact-level PROV properties

The stored fact nests provenance under `grounding` and `assertion`, but the PROV statements they encode are about *the fact*. The context therefore declares both keys as JSON-LD 1.1 nest terms (`"@id": "@nest"`) with property-scoped contexts: their members expand as properties of the fact node itself, each branch with its own key mappings (which is also what keeps the two `kind` discriminators, the two `at` timestamps, and the two `actor` shapes from colliding).

Mapping table — GroundedFact:

| duly field | maps to | notes |
|---|---|---|
| `id` | `@id` | the URN is the node IRI |
| `supersedes` | `prov:wasRevisionOf` | P4 |
| `recordedAt` | `prov:generatedAtTime` | P5 |
| `grounding.documentId` | `prov:wasDerivedFrom` (node ref) | fact derived from the source document |
| `grounding.rendition` | `prov:wasQuotedFrom` (node, `@id` = rendition id) | P3 |
| `assertion.actor` | `prov:wasAttributedTo` (node, `@id` = actor id) | human asserter; `role` stays `duly:role` on the agent node |
| `grounding.actor` (attestation) | `prov:wasAttributedTo` (node ref) | the attesting human is a source agent of the fact |
| `assertion.extractor.runId` | `prov:wasGeneratedBy` (node ref) | the extraction run is the generating `prov:Activity`; joins the envelope's run (P7) |
| everything else | `duly:` vocabulary (`https://duly.dev/spec/v0/vocab#`) | P8; `value`, `charSpan`, `bbox` are `@json` literals — byte-preserved, no RDF-ization of the typed value union |

**Why nest terms:** the alternative — mapping `grounding`/`assertion` to blank nodes — would hang `wasQuotedFrom`/`wasAttributedTo` off anonymous intermediates, and "this *fact* was quoted from that rendition" is exactly the statement a provenance consumer wants to query. **Rejected:** flattened bespoke keys (would require the exporter to restructure documents, betraying the stored-form-is-the-interchange-form principle).

## P3. Span grounding is quotation: `prov:wasQuotedFrom` the rendition

PROV-O defines `wasQuotedFrom` as citing "a potentially larger Entity … from which a new Entity was created by repeating some or all" — precisely what a D3 document grounding is: the fact repeats a span (`charSpan`, `quote`) of the rendition text. The subject is the quoting entity (the fact), the object the quoted one (the rendition), and the rendition node carries the extractor name/version that produced it (D4). The fact additionally `prov:wasDerivedFrom` the source document.

One honest gap: `rendition prov:wasDerivedFrom document` is *not* emitted. `documentId` and `rendition` are sibling keys, and a context cannot re-parent one under the other; both links exist fact-level instead (and envelope-level as `duly:sourceDocument`). A consumer wanting the rendition→document edge materializes it with a one-line SPARQL `CONSTRUCT` over facts or envelopes. **Rejected:** having the exporter synthesize the edge — it would then exist only on the exporter path, silently diverging from out-of-band expansion for a triple consumers can derive themselves.

## P4. Supersession is revision: `supersedes` → `prov:wasRevisionOf`

Directionality checked against PROV-O: "the *derived* Entity contains substantial content from the *original*" — subject is the newer entity. duly's `supersedes` sits on the correcting (newer) fact and points at the corrected (older) one (D7), the same orientation, so the mapping is key-for-key with no inversion. The correction chain is walkable in SPARQL exactly as it is in the store.

## P5. Knowledge time is generation time; effective time maps to nothing

`recordedAt` — when the append-only store created the record (D6) — is the one duly timestamp whose semantics genuinely match `prov:generatedAtTime` ("the time at which an entity was completely created"): the stored fact-record *is* the entity, and it exists from the moment the store writes it. `assertion.at` stays `duly:assertedAt` (an assertion can be made before it is recorded, and PROV has no second creation axis to give it).

`effectiveFrom`/`effectiveTo` — when the assertion is true *in the world* — have **no PROV equivalent and are deliberately not forced into one**. PROV models the history of the record (generation, invalidation, derivation), not the validity interval of the claim the record makes; the nearest terms, `prov:generatedAtTime`/`prov:invalidatedAtTime`, are about the entity's own lifecycle, and using them would flatten duly's two time axes into one — the exact confusion bitemporality exists to prevent (D6). They remain `duly:effectiveFrom`/`duly:effectiveTo`, typed `xsd:dateTime`. Likewise the receipt's `asOf` pair stays `duly:effectiveTime`/`duly:knowledgeTime`: it is an evaluation *parameter*, not a provenance event.

## P6. The receipt is a `prov:Entity` generated by an adjudication `prov:Activity` whose `prov:Plan` is the rule pack

Mapping table — DecisionReceipt:

| duly field | maps to | notes |
|---|---|---|
| `id` | `@id` | |
| `inputFacts[].id` | `prov:wasDerivedFrom` (node refs) | entity-level: the receipt derives from every pinned input fact; `contentHash` rides on each fact node |
| `caseId` | `duly:caseId` (node ref) | joins receipts to facts on the shared case IRI |
| `derivation` | `duly:derivation` as `@json` literal | see below |
| `abstentions[].facts` | `duly:consideredFact` (node refs) | links the receipt to the below-floor/conflicting fact URNs |
| everything else | `duly:` vocabulary | P8 |

The stored receipt contains no activity id — the adjudication is implicit — so the *exporter* materializes it deterministically (the out-of-band path still gets the full entity-level graph above):

- activity `urn:duly:adjudication:sha256:<receiptSha256>`, typed `prov:Activity`; the receipt `prov:wasGeneratedBy` it;
- the activity `prov:used` every input fact — same URNs the facts themselves carry, so fact-level and receipt-level graphs join;
- a `prov:qualifiedAssociation` binding the engine agent (`urn:duly:agent:<kernel>:<version>`, a `prov:SoftwareAgent`) to the rule pack as its plan: `prov:hadPlan` `urn:duly:rulepack:<name>:<version>`, typed `prov:Plan` — PROV-O's Plan ("a set of actions or steps intended by one or more agents to achieve some goals") is the textbook description of a versioned rule pack. `prov:wasAssociatedWith` carries the unqualified form.

Machine-asserted facts get the same treatment on export: the extractor has no IRI in the stored form (only name/version literals), so the exporter mints `urn:duly:agent:<name>:<version>` as a `prov:SoftwareAgent` and attributes the fact to it. Human asserters need nothing minted — their actor id is already an IRI the context maps.

**Why the derivation tree stays a JSON literal:** the tree is a proof structure — conclusions, rules, nested premises — and flattening it to generic PROV nodes would produce a thicket of blank nodes that answers no query the receipt does not already answer better: the fact linkage is first-class via `inputFacts` → `prov:wasDerivedFrom`/`prov:used`, and the reasoning rendering is [report.py](../kernel/duly_kernel/report.py)'s job. A proof-vocabulary mapping (e.g. per-step activities) can be added later without touching this one. **Rejected:** RDF-izing every derivation node now — a total mapping that would be structurally faithful and semantically mute.

## P7. The envelope is a `prov:Collection` of the run's facts

Mapping table — ExtractionRunEnvelope:

| duly field | maps to | notes |
|---|---|---|
| `id` | `@id` | |
| `factIds` | `prov:hadMember` (node refs) | the envelope is the run's manifest — a Collection whose members are the proposed facts |
| `runId` | `prov:wasGeneratedBy` (node ref) | the same activity IRI member facts carry, so envelope ↔ fact graphs join on the run |
| `createdAt` | `prov:generatedAtTime` | the manifest exists when the run completes |
| `documentId` | `duly:sourceDocument` (node ref) | the *manifest* is not derived from the document's content, so no `prov:wasDerivedFrom` here (contrast the fact, which is) |
| everything else | `duly:` vocabulary | P8 |

The exporter types the run node as the generating `prov:Activity`, `prov:wasAssociatedWith` the adapter's software agent. One loss, stated rather than papered over: `factIds` is *ordered and complete* in the stored form; `prov:hadMember` is set-valued, so the RDF view keeps membership but not order or completeness. Both survive in the stored document, which the envelope's content hash makes tamper-evident — completeness is an integrity claim, and integrity checking is the replay verifier's job, not SPARQL's.

## P8. Deliberately not mapped

A partial-but-correct mapping beats a total-but-lying one. Everything below stays in the `duly:` namespace (`https://duly.dev/spec/v0/vocab#`), with the reason:

- **`effectiveFrom` / `effectiveTo` / `asOf`** — bitemporal effective time; no PROV axis for world-validity (P5).
- **`confidence` (score/method/calibrationRef)** — PROV records what happened, not degrees of belief; no PROV term exists, and wedging scores into qualified-influence annotations would imply a standardized semantics PROV does not define.
- **`status`** — a store-level projection (D7). `prov:invalidatedAtTime` was considered and rejected: a superseded fact is not invalidated — it remains a true record of what was asserted, which is why knowledge-time replay works. Revision (P4) carries the correction story.
- **`contentHash` / `receiptSha256` / `documentSha256` / rendition `sha256`** — content addresses. PROV has no digest vocabulary; borrowing one (e.g. SPDX checksums) is a consumer decision, not this contract's.
- **`charSpan` / `bbox` / `page` / `quote`** — locator detail below PROV's granularity; the quotation *relation* is PROV (P3), the coordinates are duly's.
- **`attribute`, `entity.type`, and other CURIEs** — resolved against `schemaRef.ontology` (D10), so they are ontology-relative names, not global IRIs; expanding them as IRIs would mint identifiers that collide across ontologies. They stay literals; the SHACL/LinkML milestone owns real term resolution.
- **`abstentions`** — an abstention is a *refusal* to use an entity. PROV can say `used`; it cannot say "deliberately did not use," and mapping abstention to absence-of-`used` would erase the most audit-relevant part of the receipt. The `duly:abstention` node keeps reason, threshold provenance, and the considered facts (as node references, so the excluded fact is still linkable).
- **`rulesFired` / `defeated`** — defeasible-logic structure (which rule overrode which) has no PROV counterpart; `prov:used` on the activity covers facts, not the non-monotonic story.
- **`derivation` internals** — P6.
- **`kind` discriminators, `channel`, `sensitivity`, `schemaRef`, `engine`, `adapter`, thresholds** — duly contract mechanics with no provenance semantics.

One known coarseness, accepted with eyes open: `actor.role` lands as `duly:role` on the agent node, though a role is per-assertion, not a property of the person. The faithful PROV rendering is a `prov:qualifiedAttribution` with `prov:hadRole`, which the stored shape cannot express without restructuring; consumers reading role should treat it as scoped to the fact whose expansion produced it. If this bites, the exporter can grow a qualified form without touching stored documents or the context's existing terms.

## Versioning

The contexts are JSON-LD 1.1 (`"@version": 1.1` — required: nest terms, scoped contexts, and `@json` literals are all 1.1 features) and live under the same `v0` path as the schemas they mirror: `https://duly.dev/spec/v0/contexts/<name>.context.jsonld`. A breaking change to a schema is a breaking change to its context; they version together. Term additions (new optional schema fields) are non-breaking. The vendored `prov:`/`xsd:` prefix bindings mean no consumer or test ever needs to dereference w3.org.
