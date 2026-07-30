# duly guiding PRD

**Status:** Draft  
**Owner:** Project maintainer  
**Audience:** Prospective platform-engineering collaborators, domain and rules
contributors, extraction-adapter contributors, and early adopters  
**Planning horizon:** Through v1.0 and the first post-v1 adoption cycle  
**Last updated:** 2026-07-30

## Purpose

duly is an open-source toolkit for building auditable document-decisioning
systems in regulated workflows.

This document exists to recruit and align collaborators around a shared product
thesis:

> AI systems can propose facts from documents, but consequential decisions
> should be made by deterministic, versioned rules and delivered with
> replayable evidence.

duly is not a vertical application for insurance or mortgage closing. Those
domains are proving grounds. The product is a general-purpose trust layer that
lets an organization combine its own document extraction, ontology, rules,
review workflow, and storage with an auditable decision contract.

## Opportunity

Organizations in regulated domains increasingly use document AI and LLMs to
read unstructured documents. The difficult part is not reading a document; it
is making and defending a decision derived from it.

A consequential document decision must be:

- **Defensible:** linked to the exact source evidence and governing rule.
- **Reproducible:** replayable later under the same inputs and logic.
- **Effective-dated:** evaluated under the rules in force at the relevant time.
- **Governable:** able to abstain, route uncertainty to a human, and preserve
  correction history.

Existing tools address parts of this problem: document extraction, business
rules, temporal data, provenance, workflow, and human review. The seam between
them remains bespoke. Teams repeatedly build their own handoff from uncertain
extraction to deterministic adjudication, often losing confidence, source
spans, version history, or the ability to explain a past decision.

## Working hypothesis

If duly standardizes the handoff between probabilistic document extraction and
deterministic adjudication—with grounded facts, versioned rules, bitemporal
replay, explicit abstention, human correction, and content-addressed
receipts—then platform teams can safely use improving AI extraction systems in
regulated workflows without tying their decision logic or audit trail to one
model, provider, or rules engine.

## Users and collaborators

### Primary user

**Platform engineers** at technology organizations building or integrating
document-decisioning systems with regulatory, operational, or audit
requirements.

They need a dependable foundation they can embed in a larger system while
retaining control over their documents, ontology, extraction provider, rules,
workflow, and actions.

### Collaboration priorities

1. **Platform engineers** who validate the integration contract and adoption
   path.
2. **Rules and compliance experts** who contribute cited, effective-dated rule
   packs.
3. **Document-AI and extraction practitioners** who build contract-conformant
   adapters.
4. **Researchers** who advance authoring, verification, calibration, or
   alternate execution when a demonstrated workload needs it.

### First-week contributor outcome

A new contributor should be able to add either:

- A rule pack, with examples, expected outcomes, and golden-corpus coverage; or
- An extraction adapter that emits verified, contract-conformant facts and run
  envelopes.

Neither path should require changing the adjudication kernel.

## Product principles

1. **Perception proposes; logic disposes.** Extraction is probabilistic and
   replaceable. Adjudication is deterministic, versioned, and replayable. duly
   does not perform joint neural-symbolic inference.
2. **The output is an answer plus a receipt.** A decision is incomplete unless
   it identifies the evidence considered, facts excluded, applicable rules and
   dates, derivation, and any human correction.
3. **Standardize the seam, not the entire stack.** duly does not prescribe a
   model, workflow engine, review UI, ontology, or domain vocabulary. It defines
   the contract that lets those components work together without losing
   provenance or determinism.
4. **Abstention is a feature.** Below-confidence, missing, or conflicting
   evidence must become an explicit, routable state—not an unsupported
   confident answer.
5. **Historical decisions must remain explainable.** Facts, rules, confidence
   policy, ontology references, and evaluation time are versioned or pinned so
   a decision can be replayed as it was made.
6. **Honest boundaries build trust.** Every rule is cited or explicitly marked
   unverified; synthetic data is labeled; calibration is never claimed without
   real labeled data; and unsupported modeling is documented rather than
   silently approximated.

## Product definition

duly provides:

- A [grounded-fact contract](../spec/grounded-facts.md) for typed, atomic
  assertions with document spans or human attestations, confidence, content
  hashes, and bitemporal fields.
- A decision-receipt contract that captures conclusions, rule versions,
  citations, derivation, consumed facts, abstentions, and engine identity.
- A [deterministic rule kernel](../spec/rule-ir.md) for effective-dated,
  defeasible rules: defaults, exceptions, priorities, overrides, typed
  expressions, and pack-owned business calendars.
- An append-only bitemporal fact store with supersession and as-of projections.
- An extraction boundary: adapters and content-addressed run envelopes that
  verify source documents, renditions, fact hashes, and spans before ingestion.
- A [review loop](../review/README.md) that routes abstentions, lets human
  corrections enter as first-class facts, and turns resolved cases into
  replayable regression cases.
- An assurance harness: [golden replay](../golden/README.md), rule-change
  impact analysis, schema and hash validation, and ontology conformance checks.
- An [ontology conformance gate](../spec/ontology-conformance.md) that validates
  facts against versioned, immutable LinkML artifacts supplied by the adopter.
- Interoperability with provenance tooling through
  [PROV-O JSON-LD export](../spec/prov-o.md), without changing content-addressed
  stored artifacts.

## Proof surface

duly demonstrates generality through a bounded set of rule packs that exercise
distinct reasoning shapes, not by claiming to serve every regulated vertical.

The current proof surface is six packs across insurance and mortgage closing:

| Pack | Reasoning demonstrated |
|---|---|
| Insurance termination notice | Jurisdiction-specific rules, notice-period date arithmetic, defaults and exceptions, review correction |
| TRID fee tolerance | Typed money, cross-document comparison, regulatory categorization |
| RON eligibility | Effective-dated authorization and historical replay |
| eSign/eNote routing | Multi-document operational routing and conservative defaults |
| TILA rescission | Business-calendar computation, funding hold, statutory timing |
| County recording readiness | Document completeness, jurisdictional requirements, low-confidence abstention |

### Flagship demonstrations

The README and demo should lead with:

1. **Insurance termination notice:** a compact, understandable
   evidence-to-receipt flow.
2. **TILA rescission:** effective dates and legally defined business-calendar
   arithmetic.
3. **eSign/eNote routing:** a practical multi-document operational decision.

No new vertical is added merely for breadth. A new pack must demonstrate a
reasoning or contribution pattern that the existing proof surface does not.

## Scope

### In scope

- Auditable document-to-decision contracts and deterministic adjudication
- Rule packs, citations, effective dates, exceptions, and impact analysis
- Replaceable extraction adapters and source-grounded facts
- Human review, correction, calibration-label export, and regression capture
- Bring-your-own ontologies and versioned conformance validation
- Independent adoption through packaging, examples, and contributor
  documentation

### Non-goals

- Building an OCR, document-AI, or foundation-model provider
- Providing legal advice or representing sample rule packs as complete legal
  coverage
- Becoming a generic workflow or BPM platform
- Becoming a general-purpose knowledge-graph platform
- Standardizing review-user interfaces across organizations
- Taking autonomous consequential actions such as funding, closing, or denial
- Premature performance optimization that weakens receipt fidelity or
  semantics

## Behavior contract

duly must make the following outcomes legible:

| Situation | Required behavior |
|---|---|
| A fact is confidently extracted and grounded | Admit it as a typed fact; preserve source document, rendition, span, extractor identity, and confidence |
| A fact is below a pack's confidence floor | Exclude it from binding; record an abstention with score, threshold, pack version, and routing |
| Two live facts conflict | Resolve only under explicit policy; otherwise abstain and preserve both facts |
| A human corrects a fact | Create a new human-asserted fact; preserve correction provenance and supersession history |
| A rule changes | Version and effective-date the change; report impact against the golden corpus before accepting a new baseline |
| A decision is replayed | Reproduce it from the pinned facts, rule pack, as-of pair, and engine contract |
| A model or extractor changes | Emit new renditions and facts; preserve old receipts and evidence unchanged |
| A calendar lacks coverage | Fail loudly rather than compute a plausible but unsupported deadline |

## Success measures

### Collaborator success

- An independent platform engineer can go from document, adapter, ontology, and
  rule pack to a replayable decision and review loop within **one working day**.
- An external contributor can add a rule pack or adapter with examples and
  assurance coverage without changing kernel code.
- Contributions occur first at the intended edges: packs, adapters, examples,
  and conformance artifacts.

### Trust success

- Every committed golden case replays byte-for-byte.
- Every committed fact passes schema, hash, span, and ontology checks.
- Every automated decision has a receipt identifying its evidence, rule
  version, and as-of context.
- Rule changes expose their historical impact before acceptance.
- No calibration or accuracy claim is made without the labeled data and
  assumptions needed to support it.

### Adoption success

- An external team integrates duly into a real document-decision workflow.
- That team can use a receipt to explain a historical decision and its
  correction history.
- Replacing or upgrading an extractor does not require rule rewrites or
  invalidate old decisions.
- A real workload establishes the capacity, latency, review-rate, and quality
  measures needed to guide later scale work.

### Workflow-specific quality measures

duly does not set one global accuracy threshold. Each adopter must define, per
workflow:

- Field-level extraction accuracy on a labeled corpus
- Abstention and human-review rate
- False-acceptance rate measured through audit sampling
- Decision latency and throughput
- Drift by document template, extractor version, and model version
- Rule-change impact: decisions flipped, reasoning changed, and cases newly
  abstaining

## Risks and responses

| Risk | Response |
|---|---|
| The project becomes a collection of unrelated demos | Keep the proof surface bounded; require each new pack to prove a distinct reasoning or contribution pattern |
| Contributors cannot safely author rules | Add DMN-to-IR authoring, static verification, clearer conventions, and complete contributor paths |
| Extraction quality is confused with decision correctness | Measure extraction, calibration, abstention, and rule outcomes separately |
| The project overclaims legal or production readiness | Preserve cited scope boundaries, synthetic labels, explicit open questions, and pre-alpha status |
| An adopter needs scale before semantics are stable | Publish reference capacity limits and benchmarks; add alternate backends only for demonstrated workloads |
| The scope expands into a workflow product | Maintain the boundary: duly adjudicates and provides evidence; integrators orchestrate actions and own their UI |
| Human-review labels are biased or insufficient | State censored-sample limitations; require representative audit sampling before fitting or claiming calibration |

## Product plan

The canonical implementation and release sequence lives in the
[README roadmap](../README.md#roadmap). This PRD defines the users, product
promise, scope, and measures that guide that roadmap; it does not duplicate
milestones or release status.

The sequencing principle is stable: build capabilities for demonstrated
consumers, make the toolkit independently adoptable before optimizing for
hypothetical scale, and preserve the deterministic kernel as the final
decision and receipt authority.

## Open questions

- Which external workflow will first validate independent adoption?
- What capacity envelope should the reference interpreter publish at v1.0?
- Must review-queue resolution always supersede the abstained fact?
- What multi-entity binding model is needed when real packs outgrow the current
  one-entity-per-type simplification?
- Which contributor pathway fails first in practice: rule authoring, ontology
  mapping, extraction integration, or golden-corpus generation?
- What evidence would demonstrate that duly is more governable than a
  model-centric workflow for a specific adopter?

## Decision cadence

This PRD is a living document.

Update it when:

- A collaborator or adopter invalidates a key assumption
- A real workflow reveals a missing contract or unsafe abstraction
- A new rule pack demonstrates a genuinely new reasoning shape
- A measured workload justifies changing roadmap order
- A shipped capability changes duly's scope, trust boundary, or adoption
  promise

The governing principle remains: build capabilities for demonstrated
consumers, not hypothetical completeness.
