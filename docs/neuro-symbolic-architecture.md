# Neuro-symbolic architecture in duly

This guide is for platform engineers who understand conventional application,
data, and AI systems but are new to neuro-symbolic architecture. It explains
the general pattern, the specific version implemented by duly, the guarantees
that version does and does not provide, and the directions in which it could
grow.

The [grounded-fact specification](../spec/grounded-facts.md) and
[rule IR specification](../spec/rule-ir.md) remain authoritative for contract
and evaluation semantics. The [README roadmap](../README.md#roadmap) remains
authoritative for delivery sequence. This document supplies the system mental
model.

## The short version

Neuro-symbolic AI is a family of architectures that combine learned,
probabilistic components with explicit, symbolic representations and
reasoning. The boundary can be drawn in many places.

duly chooses a deliberately narrow division of labor:

> **Perception proposes; logic disposes.**

- A replaceable extraction layer reads unstructured documents and proposes
  atomic, typed facts.
- Every machine-proposed fact retains its evidence and source identity and
  should carry its uncertainty; an active pack policy fails closed when
  confidence is absent.
- A deterministic kernel—not a language model—applies versioned,
  effective-dated rules to the selected facts.
- The primary output is a content-addressed decision receipt containing the
  decision and derivation, pinning the evidence chain, and recording the
  applied rule trace and any abstentions.
- Unreliable or conflicting evidence can be excluded and explicitly queued
  for human review by the integrating service. Human corrections re-enter
  through the same fact contract and preserve history.

This is not joint neural-logical inference, learned theorem proving, or an LLM
reasoning inside a knowledge graph. It is a governed handoff from fallible
perception to explicit adjudication.

The architecture does not make uncertainty disappear. It concentrates
uncertainty at named boundaries where it can be inspected, measured,
rejected, or reviewed.

## Architecture at a glance

<p align="center">
  <img src="architecture-glance.svg" alt="duly architecture at a glance: a source document flows through a neural extraction adapter into proposed grounded facts with a run envelope, then admission checks fed by a versioned ontology, the append-only bitemporal fact store, an as-of projection, the deterministic rule kernel fed by versioned rule packs, and a content-addressed decision receipt; abstentions route to a review queue whose human corrections re-enter the store as facts, and receipts feed golden replay and impact analysis" width="680">
</p>

There are really two systems here:

1. The **runtime evidence flow** moves from document bytes to a rendition, to
   proposed facts, to an as-of projection, to a receipt.
2. The **change-control flow** versions ontologies and rule packs, validates
   them, replays historical cases, and makes the impact of a change visible
   before deployment.

The second flow is as important as the first in a regulated system. A correct
decision today is insufficient if the organization cannot explain what changed
or reproduce yesterday's decision later.

Moving governed meaning into typed, versioned artifacts restores deterministic
contract tests, impact analysis, and replay for that part of the system.
Behavior at the probabilistic perception edge still requires statistical
evaluation; explicit artifacts do not make model behavior deterministic.

## The two traditions, in practical terms

The statistical and symbolic traditions solve different parts of the problem.

| Capability | Probabilistic or neural systems | Symbolic systems |
|---|---|---|
| Read variable language and layouts | Strong | Require structured input |
| Handle ambiguity and unfamiliar phrasing | Strong, but fallible | Brittle outside encoded concepts |
| Represent an explicit rule | Implicitly at best | Directly |
| Reproduce an identical derivation | Not generally | Can, with deterministic semantics and retained inputs |
| Explain which rule used which fact | Generated explanation may be unfaithful | Can emit a native evaluation artifact |
| Adapt without manual knowledge engineering | Often learns from data | Typically requires governed schema and rule maintenance |

Pure symbolic systems historically struggled because the world had to be
formalized before they could act. Modern extraction models make that
formalization cheaper: they can propose structure from language. Pure
statistical systems have the opposite weakness: they can read language but do
not naturally provide a stable, inspectable decision procedure.

duly composes the two without asking either to do the other's job. A model may
propose that a notice was mailed on a certain date. It does not decide whether
the notice complied with a statute. A rule pack may decide compliance from
accepted dates and jurisdiction facts. It does not parse the source PDF.

## Prior grounding rather than post-hoc explanation

A conventional retrieval-augmented system can show which passages were near a
model when it produced an answer. That is provenance of text, not necessarily
provenance of the decision. A generated rationale may be readable without
being the computation that produced the result.

duly moves evidence and constraints in front of the decision:

1. a machine assertion must first become a typed, grounded proposal;
2. a correctly composed admission path makes malformed, untraceable, or
   nonconforming proposals fail loudly;
3. explicit rules derive the decision from the admitted fact set; and
4. the receipt records the actual rule-to-fact derivation.

This is the useful meaning of **prior grounding** in duly. The model's output
does not acquire decision authority merely because it sounds plausible or
cites a document. It must cross a governed interface first.

This shifts part of the safety strategy from monitoring free-form output to
constraining the decision path. It does not replace monitoring, evaluation, or
human review, and it does not make extraction errors impossible.

## The artifacts that carry meaning

Semantic-web literature often distinguishes a **T-Box**—the vocabulary and
constraints describing what can exist—from an **A-Box**—assertions about
particular things. That is a useful analogy, but duly separates the concerns
more explicitly:

| Artifact | Role in duly | What it is not |
|---|---|---|
| Ontology artifact | Versioned vocabulary and type constraints supplied by the adopter | The decision logic |
| `GroundedFact` | One assertion about one case, with evidence and uncertainty | A conclusion merely because it is well-formed |
| Rendition | One extractor's reading of one document's bytes, content-addressed and immutable — and the coordinate system every character span is measured in | The document, or a faithful transcription of it. Two extractors produce two renditions from identical bytes, which is why a span that resolves against one may resolve nowhere in the other |
| Rule pack | Versioned decision policy, including defaults, exceptions, confidence floors, citations, calendars, and the phrasing of each decision it can answer. Authored as YAML, or compiled from a [DMN decision table](../spec/dmn.md) — either way the kernel sees one artifact | A domain ontology or workflow definition — and its phrasing is not part of the decision's identity |
| `DecisionReceipt` | A derived decision that pins its evidence references and records its rule trace — independently checkable by its holder, to the depth the inputs they also hold allow | The facts, source rendition, or rule-pack bytes themselves — which is why it can verify its own hash alone, and needs those artifacts supplied to verify anything more |
| Extraction run envelope | Integrity manifest for one run over one rendition | Authentication of the producer |

A rule pack has two halves, and the distinction is easy to miss because one
file holds both. The **deciding half** — rules, priorities, effective windows,
calendars, confidence floors — reaches the receipt through the decision it
produces and the trace it leaves, and is therefore frozen: change it and you
change what replays, which is why every such change is a version bump and an
impact run. The **speaking half** — the question a pack advertises and the
phrasing of its answers — is authored by the same expert, reviewed in the same
pull request, and versioned in the same file, yet must never enter a hashed
body, because a wording improvement that invalidated 351 receipts would make
the wording unimprovable. Governance and identity are not the same boundary.
The practical test: a decision's meaning is `decision.value`, which is hashed;
how that value reads to a human is pack data that any renderer may consume and
no receipt records.

There is a third part of the file, and building an editor for packs is what
made it visible. Between the deciding half and the speaking half sits the
**arguing** part: the prose in the YAML. `DEMO-SYNTHETIC` on an invented
effective window, `TODO(verify)` naming what was not confirmed, the
`MODELING BOUNDARY` header explaining what the IR could not express, the
comment recording why an `overrides` is an authored legal exception rather
than a workaround for a proof the validator cannot perform. None of it is
hashed, none of it is phrasing, and every automated gate in this repository is
blind to it: strip every comment from a pack and validation passes, the 351
golden receipts replay byte-for-byte, and impact analysis reports zero. The
honest-labeling invariant lives entirely in a layer nothing checks.

The practical consequence, which the [rule studio](../demo/rules_api.py) had
to answer directly: any tool that re-emits a pack from the IR — a compiler, a
formatter, a structured editor — destroys the arguing part while leaving both
governed halves provably intact. duly's response is neither to forbid the
re-emission nor to pretend it is lossless, but to make the loss the thing you
look at: the studio shows a normalised diff for *what you changed* and the raw
file diff for *what you would be committing*, and keeps a text-editing path
that preserves comments. That is the same move as impact analysis. A change
that cannot be prevented mechanically is instead made impossible to make
accidentally.

In T-Box/A-Box terms, the ontology is T-Box-like and grounded facts are
A-Box-like. Rule packs are a separate policy artifact. duly does not currently
use an RDF/OWL knowledge base or an OWL reasoner, so the analogy should not be
read as an implementation claim.

## The runtime lifecycle

### 1. A document becomes an immutable rendition

The source document is pinned by a SHA-256 digest of its bytes. An extraction
adapter produces a **rendition**: immutable extracted text with its own hash and
the identity and version of the tool that produced it.

Facts point to character offsets in that rendition, not vaguely to "the PDF."
Different PDF parsers produce different text and therefore different offsets.
Retaining the exact rendition is what lets an old fact's quote remain
resolvable after an extractor upgrade.

The shipped adapters are intentionally modest:

- the scripted stub makes demonstrations deterministic;
- the Docling adapter converts the document into a rendition and locates an
  author-declared quote. The target already supplies the entity, attribute,
  value, and quote; the adapter's raw confidence is a quote-match heuristic,
  not semantic field accuracy or a calibrated probability.

They are not autonomous ontology-discovery systems. A production LLM or
document model can replace the proposal mechanism while preserving the same
rendition, fact, span, and envelope contracts. duly is the extraction boundary,
not the extraction model.

### 2. Extraction produces proposed grounded facts

A [`GroundedFact`](../spec/grounded-facts.md) is one
entity–attribute–value assertion. For example:

```text
notice:HO-77401-NY:2026-07-25
  nc:noticeMailedDate
  2026-07-25
```

The complete fact also carries:

- a typed value—dates, decimals, money, codes, booleans, and entity
  references have distinct representations;
- document grounding with the source hash, rendition, exact span, and quote,
  or a human attestation when no document contains the fact;
- machine or human assertion provenance;
- for a machine assertion, normally confidence and its method—the schema
  currently permits omission, while an active pack policy excludes a
  confidence-less machine fact;
- a required, caller-supplied `recordedAt` knowledge timestamp and optional
  `effectiveFrom`/`effectiveTo` validity window;
- an exact ontology name and version;
- a content hash from which the fact ID is derived.

Atomicity matters. An extractor can be confident about an amount and uncertain
about its regulatory category. Separate facts let the system admit, reject,
supersede, and calibrate those assertions independently.

### 3. The admission boundary checks the proposal

One extraction run emits an
[`ExtractionRunEnvelope`](../spec/grounded-facts.md#resolved-questions) for one
rendition. `verify_envelope` checks, before ingestion:

- the envelope's hash and ID;
- the rendition hash;
- ordered and complete membership of the supplied fact list;
- every fact's hash and ID;
- that each fact's document hash, rendition ID, and assertion run ID match the
  corresponding envelope fields;
- that every quote exactly equals the rendition slice named by its span;
- optionally, conformance to the fact's pinned ontology when the deployment
  supplies an `OntologyRegistry`.

"Complete" here means that the verifier received exactly the outputs declared
by this run. It does not mean that the extractor found every decision-relevant
fact in the document.

`verify_envelope` does not compare a fact's `documentId` with the envelope's,
compare extractor metadata with `envelope.adapter`, or recompute the source
document hash from source bytes it was not given. Full JSON Schema validation
supplies additional shape and URN checks. A production admission path should
compose both layers and establish the source hash when it first receives the
bytes.

If a run must later be withdrawn, `revoke_run` appends retraction events for
its live facts. It does not delete or rewrite their history.

The [ontology conformance gate](../spec/ontology-conformance.md) checks that the
ontology version exists, the entity type and attribute are declared together,
the value kind is correct, and codes belong to the expected code system and,
for closed enums, the permitted set.

These checks answer different questions:

- **Schema and ontology checks:** is this assertion expressed in an allowed
  form and vocabulary?
- **Envelope and span checks:** are these the exact artifacts the adapter
  emitted, and does the quoted evidence resolve?
- **Extraction evaluation and review:** did the adapter interpret the evidence
  correctly?

Only the last question is about semantic truth. A wrong date can be
well-typed, correctly hashed, and perfectly grounded to the phrase it
misinterpreted.

One integration detail matters: duly is a toolkit, not a monolithic service.
`adjudicate()` trusts the fact list it receives. Full JSON Schema validation,
envelope verification, and ontology conformance must be composed into the
deployment's admission path; the kernel does not repeat them. Ontology checking
is optional in `verify_envelope` because the registry belongs to the adopter,
so a production integration must supply it deliberately.

### 4. The store preserves what was known, not just what is current

The reference [`FactStore`](../store/) is an append-only SQLite event store.
It records assertions, supersessions, and retractions; it never updates the
original fact in place. SQLite is a decision about now, not about the ceiling:
the schema is deliberately Postgres-portable, so a server deployment changes
the engine without changing the semantics — and that cost is deferred until a
deployment exists to demand it, not paid in advance.

This supports two independent time questions:

- **Effective time:** when was the assertion true in the world?
- **Knowledge time:** when had the system learned it?

`recordedAt` is required but caller-supplied. The store never reads the wall
clock and does not authenticate that timestamp. Effective windows are optional;
the v0 convention is that event assertions generally omit them, while facts
with genuinely bounded validity include them.

A correction is a new human-asserted fact that can supersede the earlier
machine fact. An earlier knowledge-time projection still contains the old
state; a later projection contains the correction. This is how the system can
answer, "What would we have decided then, using what we knew then?"

The caller must obtain the fact set through `FactStore.as_of` before calling
the kernel. The kernel records `asOf.knowledge` on the receipt but does not
itself reconstruct historical knowledge; it evaluates the supplied
projection. That boundary is important in any alternative storage
implementation.

The same `asOf.effective` point currently selects rule versions and filters
bounded fact validity. Separating those into independently selectable time
dials is a future semantic extension, not current behavior.

### 5. The kernel applies explicit decision semantics

The current kernel is a pure-Python reference interpreter for duly's
[rule IR](../spec/rule-ir.md). It is not yet a Datalog, Soufflé, ASP, or solver
backend.

Everything domain-specific it consumes — rules, priorities, effective windows,
calendars, confidence floors, even the phrasing of a verdict — arrives as
versioned pack data. That placement is a deliberate design pressure, not an
accident of layering: when a new need appears (business-day arithmetic,
abstention thresholds, non-boolean verdict wording), the question asked is
"what does the pack need to carry?" rather than "what does the kernel need to
do?", so a domain author can create, validate, test, and impact-assess a rule
change without touching kernel code, and the kernel changes rarely while the
packs change often.

A rule declares:

- the entity and attributes it needs;
- an effective window;
- a typed condition;
- the conclusion it produces;
- its priority and any rules it explicitly overrides;
- a legal or policy citation.

Evaluation is deterministic:

1. Bounded facts and rules are filtered at the supplied effective time.
2. Pack-owned confidence floors exclude low-confidence machine facts.
3. Conflicts are resolved only by explicit policy: one human assertion can
   outrank machine assertions; otherwise the attribute is unbindable.
4. Rules with unresolved inputs are inapplicable.
5. Derived dependencies are evaluated in strata, so producers settle before
   consumers and dependency cycles are rejected.
6. Explicit overrides suppress named defaults or general rules.
7. Priority resolves remaining same-attribute conflicts; unresolved
   ambiguity is an error.
8. Pack-owned business calendars fail loudly outside their declared coverage
   rather than guessing.

This is **defeasible reasoning**: a low-priority presumption can apply by
default and a more specific rule can defeat it when its conditions hold. The
receipt records that defeat rather than hiding it.

duly derives conclusions during each adjudication and emits a receipt; receipt
persistence is the integrating service's responsibility. It does not write
derived conclusions back as materialized facts. A future materialized
inference or graph layer would need premise-and-rule lineage so changes can
invalidate every dependent conclusion.

### 6. The receipt is the decision product

The kernel emits a content-addressed `DecisionReceipt` containing:

- the decision value and entity;
- the effective and knowledge as-of pair;
- rule-pack name and version;
- the surviving rules, citations, priorities, effective windows, and defeated
  rule IDs;
- a nested derivation from conclusion to consumed facts;
- every consumed fact pinned by ID and content hash;
- low-confidence and conflict abstentions, including any optional routing
  label;
- the kernel version and backend.

The Markdown/PDF audit report and
[PROV-O JSON-LD export](../spec/prov-o.md) are deterministic projections of
these artifacts. They do not ask a model to invent an explanation. PROV-O
provides useful lineage interoperability, but the mapping is deliberately
partial: effective time, confidence, abstention, and defeasible-rule structure
do not have faithful generic PROV equivalents.

A retrieved passage or citation provides provenance of an input. The receipt's
derivation provides provenance of the decision procedure: which accepted facts
bound which rules and how their conclusions composed.

The receipt is content-addressed, but the current runtime receipt identifies a
rule pack by name and version rather than hashing the pack bytes. Replay
therefore also depends on the repository's immutability discipline: a released
pack version must never be changed in place. A fact's `schemaRef` likewise
pins an ontology name and version, not an ontology-file digest, so the same
immutability requirement applies to ontology artifacts.

Because pack identity sits *inside* the hashed body, two packs are two
identities even when they encode the same rules. The DMN work made this
concrete: a decision table compiled from
[`dmn/examples/trid-fee-tolerance.dmn`](../dmn/examples/trid-fee-tolerance.dmn)
reaches the same decision as the hand-written TRID pack, fires the same rules
in the same order with the same defeat chains, and consumes the same facts —
and cannot produce the same `receiptSha256`, because the two packs do not
share a name. This is the same shape as `engine.backend` being inside the
hash, and it is a feature rather than a limitation: a receipt is supposed to
say which artifact decided, not merely what was decided. Any claim of
equivalence between two rulebases is therefore a claim about *decisions*, and
has to be stated and tested at that level.

The same discipline governs `engine.version` from the other direction: what a
sealed field says must be something that cannot drift. It is the version of
the kernel's **decision semantics** — a pinned constant, deliberately
decoupled from the `duly_kernel` package version and from the distribution
version. The three scopes nest one way only: a semantics change implies a
kernel code change implies a release, never the reverse, because a release can
ship a demo fix with the kernel byte-identical. Coupling the sealed field to
the release cadence would invalidate every committed receipt on the first
published version without a rule, a fact, or a decision having changed. Like a
rule id, the sealed value is a handle rather than a claim: everything a
version number is tempted to say has a correctable home in package metadata,
and the field inside the hash does not.
[docs/release-process.md](release-process.md) is the operating procedure this
implies.

### 7. Review closes the evidence loop

A receipt can contain a decision and abstentions at the same time. For example,
a low-confidence fact may be excluded while a conservative presumption still
produces a decision. "The system abstained on evidence" does not always mean
"the system produced no decision."

An integrator passes receipt abstentions to `ReviewQueue.enqueue_receipt`,
where they become deduplicated, append-only review items. A pack may attach an
optional `routedTo` label; the kernel does not dispatch work to a queue. A
reviewer can:

- resolve the item with a human-asserted grounded fact, usually superseding
  the machine assertion; or
- dismiss it because exclusion was the correct outcome.

The correction enters through the ordinary fact-store API, so subsequent
adjudication needs no special "human override" execution path. A resolved case
can become a committed golden regression case and can yield a labeled pair for
calibration.

Those labels are selected from reviewed, usually abstained facts. They are a
censored sample, not an unbiased estimate of extraction accuracy. duly ships
calibration mathematics, not a pre-calibrated production model.

There is also a current boundary mismatch to resolve before making a conformal
guarantee in production: `ConformalCalibrator.accepts` uses a strict
`score > threshold` test, while the kernel admits a fact at
`score >= minConfidence`. Copying a fitted conformal threshold directly into a
pack floor therefore does not preserve equality behavior literally.

## A concrete duly example

The insurance starter asks whether a New York nonrenewal notice supplied
enough notice.

1. The extractor proposes the governing state, notice type, mailing date, and
   policy expiration date, each grounded to a rendition span.
2. The termination-notice rule pack derives the required notice period for the
   jurisdiction and notice type.
3. A noncompliance rule compares the two dates and can defeat the pack's
   low-priority presumption of compliance.
4. In the review scenario, the mailing-date proposal has confidence `0.62`,
   below the pack's `0.90` attribute floor. The kernel excludes it and records
   a `low_confidence` abstention. The demo explicitly enqueues it for review.
   The presumption remains as the decision, explicitly identified as such.
5. A reviewer supplies a human assertion for the mailing date and supersedes
   the machine fact.
6. The next as-of projection contains the correction. The specific rule now
   fires, defeats the presumption, and changes the verdict.
7. The resolved case is exported as a replayable golden case.

The UI is useful, but it is not the architecture. The architecture is that the
same correction is a new immutable fact, the changed conclusion has a new
receipt, and both historical states remain reconstructible. See
[Follow one fact](follow-one-fact.md) for the committed data and hashes at each
step.

## Missingness, open-world reasoning, and defaults

One of the most important choices in any symbolic system is what absence means.

Under an **open-world** interpretation, a missing fact means "unknown." Under a
**closed-world** interpretation, it may mean "false" or "not present." Neither
is universally correct. A complete, bounded document may justify an
absence-based conclusion; an incomplete case file does not.

duly does not inherit RDF/OWL open-world semantics because it is not an OWL
reasoner. Its v0 behavior is operational:

- a rule fires only when all of its declared bindings resolve;
- a missing binding makes that rule inapplicable;
- a different default or presumption may still produce a decision;
- if no rule produces the requested decision, the kernel raises an
  `AdjudicationError`.

Low-confidence and conflicting facts produce explicit receipt abstentions.
Ordinary missing bindings do **not** currently produce `reason: missing`
entries, even though the receipt schema permits that shape. Ontology
conformance also does not enforce sibling-field completeness.

Therefore, pack authors must not silently treat "not extracted" as "verified
absent." When absence is decision-relevant, the workflow should establish
document completeness or encode an explicit fact that the rule can consume.
More expressive completeness checkpoints are a credible extension, but they
are not current behavior.

## What the current guarantees mean

| Property | What duly provides | What it does not imply |
|---|---|---|
| Determinism | The same supplied fact set, exact rule content, as-of pair, and engine produce the same receipt bytes | That the facts or rules are true |
| Grounding | A verified quote resolves to an exact span in an exact rendition | That the extractor interpreted the quote correctly |
| Content addressing | Mutation of facts, envelopes, renditions, or receipts is detectable *relative to their seal* | Producer identity, authorization, or an adversarially immutable database — nor that the sealed content is faithful, since an altered receipt can be re-sealed and only re-adjudication catches that |
| Independent receipt verification | Whoever holds a receipt can check it without trusting its producer: its hash from its own bytes, its facts against their content hashes, and — given those facts and the pack version it names — a full re-adjudication compared byte-for-byte | That the rulebase was right about the law, or who produced the receipt. Two of the three checks require inputs the receipt does not carry, and report *not checked* rather than passing when they are absent |
| Ontology conformance | With the registry enabled, vocabulary, attachment, value kinds, and codes conform to a pinned version | Record completeness, cross-fact consistency, or domain truth |
| Confidence policy | Low-confidence machine facts can be excluded under versioned pack policy | A calibrated error rate unless representative labels and the calibrator's assumptions hold |
| Defeasible rules | Defaults, exceptions, priorities, and derivations are explicit and replayable — and, where the [verifier's fragment](../spec/pack-verification.md) reaches, mechanically checkable: same-priority rules can be *proved* mutually exclusive, and the input regions where no rule concludes a decision can be enumerated with witnesses | That the encoded policy is current or legally correct. "Complete" acquires a narrow, checkable meaning here and keeps a wide unchecked one: the verifier proves a pack reaches *some* conclusion over its inputs, never that the conclusion is the right one, that the rules encode the whole of the law, or that the facts the rules need were extracted |
| Bitemporal replay | The store can reconstruct facts known at a prior knowledge point and valid at an effective point, and — from the same log — say what became of a fact that no longer binds | Correct replay if a caller bypasses the as-of projection |
| Golden replay | Committed cases produce byte-identical historical receipts | General correctness outside the corpus or legal validation of synthetic examples |
| Impact analysis | A rule change's flips and reasoning changes are visible on the corpus | Automatic approval or rejection of the change |
| PROV-O export | Standard lineage tools can query useful artifact relationships | A lossless mapping of duly's time, uncertainty, or rule semantics |

The compact version is:

> Determinism makes a decision reproducible and inspectable. It does not make
> the decision true.

Correctness still depends on extraction quality, evidence coverage, ontology
fitness, rule quality, temporal selection, implementation correctness, and
human governance.

That sentence has an unexamined middle, and the static verifier occupies it.
Between *reproducible* and *true* sits **internally consistent**, and until a
solver could speak about a rulebase, duly had no way to make that claim: the
pack validator could only report "I cannot prove these disjoint," which an
author correctly reads as a statement about the validator rather than about the
rules. The verifier separates the two. A green `prove` run licenses exactly
three beliefs — no two same-priority rules can both fire, the named decision
attributes have no unintended input gaps, and (against a second pack) the two
decide and defeat alike everywhere. It licenses nothing about whether the
encoded rule is the rule the statute states, whether the statute has since
changed, or whether the case file contained the evidence the rules needed.

The generalization is worth stating on its own, because it explains several
otherwise-unrelated design choices at once:

> **A proof about the rulebase is a different kind of claim from a proof about
> a run.** Determinism, content addressing, and golden replay are all claims
> about *one execution* and its reproducibility. Disjointness and coverage are
> claims about *the space of all executions*, established before any execution
> happens, by a tool that is not permitted to participate in one.

That separation is not an accident of packaging. It is the same reason the DMN
compiler is an authoring surface rather than a second engine, the reason
`engine.backend` sits inside the receipt hash, and the reason `prove` does not
relax the pack validator: anything that could change a decision must live
inside the versioned, replayable artifact, and anything that merely *reasons
about* decisions must be provably outside it.

A second claim in this document turned out to have a soft edge, and building a
reader for the store is what found it. Immutability is usually defended as
**preservation**: a correction supersedes rather than edits, so nothing once
believed is lost. Preservation is the weaker half of what an append-only log
buys. The log admits two different queries — *which facts bind at this
horizon*, which is what adjudication needs and what `as_of` answers, and *what
became of this fact*, which adjudication never asks and an auditor asks first.
A mutating store can answer neither honestly. A store with a deletion-free log
but only a survivor projection answers the first and merely *promises* the
second, and duly was in that position from M2 until the evidence browser ran
the second query. So the line worth drawing is not between mutable and
immutable storage:

> "Nothing is lost" becomes checkable at the point where something reads the
> history back. Until then it is a property of the schema, which a system can
> satisfy perfectly while remaining unable to tell you what it used to believe.

Which is why the browser recomputes liveness from the event log instead of
calling `as_of`, and why a test walks every case at every point on its timeline
asserting the two projections agree. One implementation answering both
questions would prove nothing; two implementations that must agree are a
differential check, in the same spirit as `prove` standing behind the pack
validator.

That dichotomy is not exhaustive, and the gap in it is instructive. A what-if
answer is a claim about *one execution that did not happen* — as pointwise as a
receipt, but with no run behind it to reproduce. It cannot be established by
reasoning about the rulebase, because it is about a single point; and it cannot
be established by replay, because there is nothing to replay. The only way to
make it true is to make it a run: hand the proposed facts to the real kernel
and keep the verdict.

So [`whatif`](../spec/whatif.md) reaches back across the boundary that `prove`
never crosses — it *calls the kernel*, repeatedly, on cases that do not exist —
and stays outside all the same. The rule was never "a tool that reasons about
decisions may not touch the kernel." It is that such a tool may not produce
artifacts which enter the audit chain. `prove` honours it by never making a
decision; `whatif` honours it by making many and keeping none. Both sit outside
the versioned artifact; only one of them sits outside the executor, and the
difference tells you which invariant was actually load-bearing.

There is one more position in that lattice, and it belongs to whoever is
holding the receipt rather than to anyone running this repository. Content
addressing appears in the guarantees table above as *mutation is detectable*.
That is true, and weaker than it sounds. A hash is computed over a document,
so it detects mutation relative to a seal — and whoever alters the document
can simply re-apply the seal. Flip a verdict, recompute `receiptSha256`, and
the artifact is consistent again: the facts it pins are genuine and hash
correctly, the derivation is well-formed, the report renders in fluent
sentences over real statutory citations. Every integrity check that operates
on the receipt *as a document* passes. The forgery is undetectable by
inspection precisely because nothing about it is malformed.

What it cannot survive is being run. So the sharpened claim is:

> Content addressing establishes that a receipt is **unaltered since it was
> sealed**. Only re-adjudication establishes that it is a **faithful record of
> what the rules concluded**. Tamper-evidence and fidelity are different
> properties, and the first does not approach the second.

This is why a receipt cannot be verified by one check reporting one verdict.
Hash, fact integrity, and replay establish three different things and fail
independently; collapsing them into a single valid/invalid pill would hide the
one case where they disagree, which is the case that matters. It is also why
the middle check must be able to report *not checked*: a receipt pins its
facts by hash rather than by value, so a receipt arriving on its own genuinely
cannot reproduce its own evidence, and a verifier that quietly passed it would
be converting an absence into an assurance.

The last distinction is about standing rather than about computation. Golden
replay and single-receipt verification run the same kernel over the same
inputs and compare the same bytes; what differs is who is entitled to conclude
something. Replay over the corpus is a claim duly makes about artifacts duly
produced, checked by CI duly configured — real evidence of determinism, and
structurally the same shape as any project's test suite. The identical
computation, performed by the party *holding* a receipt, against facts and a
pack version the receipt itself names, is a claim that needs no trust in the
producer at all. A decision record that only its author can verify is
documentation. One that its recipient can verify is a receipt, and the
difference is not in the artifact — it is in whether the checking is available
to the person with a reason to doubt. The [receipt viewer](../demo/receipts_api.py)
exists to make that availability concrete rather than theoretical
([tour §12](demo_tour.md#12-the-receipt-viewer)).

## The gates

The most dangerous transition in a neuro-symbolic system is where a
probabilistic proposal acquires deterministic authority. A useful design rule
is to name and test every such boundary.

| Boundary | duly mechanism today | Residual risk |
|---|---|---|
| Document → proposed fact | Immutable rendition, source hash, typed fact, exact grounding span, extractor identity, and deployment-required confidence | A plausible but wrong interpretation can still be well-grounded |
| Proposed run → admitted facts | Deployment-composed JSON Schema validation, envelope verification, and optional ontology registry; envelope checks finish before `ingest_envelope` writes | An integration can omit schema or ontology enforcement; hashes provide integrity, not authenticity |
| Stored history → decision input | Explicit `FactStore.as_of` projection, effective windows, supersession/retraction history | The caller can supply the wrong projection or bypass the store |
| Facts → rule bindings | Pack confidence floors, conflict policy, typed expressions, explicit dependencies | Missingness and completeness remain pack/workflow concerns |
| Rule/ontology change → release | Pack validation, expected outcomes, conformance checks, golden replay, impact analysis | A stable baseline can still encode the wrong policy |

Three additional gates become relevant only if the product grows into those
surfaces:

- **Natural language → formal query:** validate syntax, schema references, and
  bounded scope before deterministic execution. These checks cannot prove user
  intent—a query can be valid, executable, and still ask the wrong formal
  question—so semantic translation needs its own evaluation and review.
- **Receipt → generated prose:** permit a model to phrase only claims already
  present in the receipt and evidence chain.
- **Decision → external action:** validate the action against explicit policy,
  authorization, freshness, and idempotency requirements before execution.

duly currently adjudicates and emits evidence-linked receipts. It does not
autonomously deny a claim, release funds, close a loan, or execute another
consequential action. An orchestrator remains responsible for side effects.

## Where knowledge graphs fit

A knowledge graph represents entities and typed relationships as a connected
graph. It becomes especially useful for questions such as:

- Which endorsements modify the coverage implicated by this loss?
- Which decisions relied, directly or indirectly, on a retracted fact?
- How are parties, documents, transactions, clauses, and decisions connected
  across a long-running case?

Vector retrieval and graph retrieval answer different questions. Vector search
finds text that is semantically similar to a query; graph traversal follows
relationships the system has explicitly modeled and can make a multi-hop path
inspectable. A graph is "complete" only relative to its schema and its current,
correctly populated contents—it cannot recover an omitted or stale fact. The
two approaches can be composed when a workload needs broad candidate recall
followed by explicit relationship checks.

duly is neuro-symbolic without being a general-purpose knowledge-graph
platform. Today it has:

- atomic facts with entity IDs, CURIE attributes, and an `entityRef` value
  kind;
- versioned LinkML ontology artifacts and a constrained conformance gate;
- a relational append-only event store;
- a deterministic rule interpreter for bounded per-case adjudication;
- PROV-O export for external RDF/SPARQL lineage queries.

It does **not** have a graph-native source of truth, graph traversal in the
kernel, OWL inference, general SHACL enforcement at runtime, or GraphRAG.
LinkML can generate SHACL for standards-tooling tests, but the hot-path
validator interprets a documented LinkML subset.

That is a sensible boundary for the current workload. The v0 kernel assumes
one entity per entity type and one live fact per attribute in a case. Its
demonstrations ask bounded document-decision questions; adding graph
infrastructure would create another consistency, temporal, and operational
surface without yet simplifying those decisions.

A graph becomes justified when a real workload needs multiple same-type
entities, explicit relationship constraints, multi-hop or cross-document
reasoning, longitudinal queries, or large-scale lineage traversal. The safest
evolution is likely:

1. keep content-addressed facts, receipts, and evidence as canonical artifacts;
2. project those artifacts into a graph for the demonstrated query or
   reasoning workload;
3. preserve bitemporal, confidence, abstention, and defeasible-rule semantics
   that generic graph vocabularies cannot represent faithfully;
4. regenerate or validate the projection rather than maintaining two
   unaudited sources of truth.

RDF/OWL/SHACL and labeled property graphs offer different semantics and
ergonomics; neither is universally correct. RDF and standards-based validation
are attractive when formal interoperability and inference are requirements.
Property graphs are often convenient for application traversal. A hybrid
vector-plus-graph retrieval layer can help when recall and relationship
verification are both needed. None should become a foundational dependency
until a workload supplies acceptance criteria.

## Current implementation versus adjacent patterns

| Pattern | Status in duly |
|---|---|
| Model or document AI as fact proposer | Supported by the adapter contract; autonomous model-driven proposal is supplied by the adopter, not shipped as a duly model |
| Symbolic layer as decision authority | Implemented |
| Deterministic report rendering | Implemented |
| Backward query over the rulebase ("what would have had to be true?") | Implemented as a validation-time tool reusing the verifier's encoding unmodified, with every answer re-adjudicated through the kernel before it is returned ([spec/whatif.md](../spec/whatif.md)). No artifact is produced and nothing reaches a receipt |
| Static verification of the rulebase by a solver | Implemented as a validation-time tool over a documented fragment: booleans, decimals and money as reals (currency unmodeled), dates as bounded integers, strings and codes as finite domains resolved from the ontology, and the IR operators that encode faithfully ([spec/pack-verification.md](../spec/pack-verification.md)). Constructs outside it are refused by name rather than approximated. `z3-solver` is an optional extra; the kernel neither imports it nor depends on it, and no solver output reaches a receipt |
| Business-editable decision tables compiled to the decision logic | Implemented for a deliberately narrow subset: DMN 1.3+ tables, S-FEEL cells, three of seven hit policies, mandatory per-row citation and effective date ([spec/dmn.md](../spec/dmn.md)). The compiler is an authoring surface, not a second engine — its output is an ordinary rule pack the same kernel executes |
| Rules browsed and edited as decision tables in a UI | Implemented as a *projection* of the rule IR, computed with the kernel's own expression parser ([demo/rules_api.py](../demo/rules_api.py), [tour §10](demo_tour.md)). It is not a DMN round trip: the compiler is one-way by design, so a guard relating several bindings is shown as a cross-input condition the grid cannot hold rather than flattened into a cell that would misstate it |
| Rule change measured before it is committed | Implemented: a candidate pack that exists only in memory is re-adjudicated over the full golden corpus, and — with the optional solver — proved decision- and trace-equivalent (or not, with a witness input) against the committed pack. The order matters more than the tooling: an impact number the author sees *before* writing the file is the only one that can change their mind |
| Evidence browsed as objects rather than as one decision's citations | Implemented ([demo/evidence_api.py](../demo/evidence_api.py), [tour §11](demo_tour.md#11-the-evidence-browser)): a case's documents — source bytes beside the extractor's rendition — and every fact ever asserted about it, at a knowledge time the reader chooses. Spans are drawn only on the rendition they are measured in, and liveness is recomputed from the event log rather than read off `as_of`, so superseded and not-yet-known facts stay visible instead of vanishing |
| A decision record its recipient can verify without trusting its producer | Implemented ([demo/receipts_api.py](../demo/receipts_api.py), [tour §12](demo_tour.md#12-the-receipt-viewer)): three independent checks — the receipt's hash from its own bytes, each pinned fact against its content hash, and a full re-adjudication compared byte-for-byte — reported separately, because a re-sealed forgery passes the first two. Checks whose inputs were not supplied report *not checked*; a pack whose version has moved is refused rather than substituted |
| Model-generated explanation constrained by a receipt | Possible extension; not current behavior |
| Natural-language-to-formal-query interface | Possible extension; not current behavior |
| RDF or property-graph decision core | Not implemented |
| Joint neural-symbolic training or differentiable logic | Out of scope for the current architecture |
| Datalog/Soufflé or ASP execution backend | Roadmap option after equivalence semantics and a real workload |
| Optimizer plans, symbolic layer decides admissibility | Implemented as a worked example ([examples/closing-scheduler](../examples/closing-scheduler/README.md)): every hard constraint given to CP-SAT is a table of adjudications, the scheduler holds no copy of any rule, and each planned date cites the receipt ids that constrained it. It plans and explains; it still does not execute |
| Agent plans, symbolic layer executes actions | Possible integration pattern; duly itself does not execute consequential actions |

## Failure modes a platform team should design for

### Deterministic garbage in, deterministic garbage out

The kernel can produce a perfectly replayable wrong decision from a
wrong-but-valid fact. Measure field-level extraction accuracy and audit
accepted facts, not only abstentions.

### Omitted evidence

No schema or graph can return a fact that was never extracted or modeled.
Document-set completeness, required evidence, and negative evidence need
explicit workflow semantics.

### Stale structured knowledge

Ontologies, rules, calendars, and mappings change as products, forms, and laws
change. Their maintenance is a permanent product, engineering, and domain
ownership function—not a one-time implementation task.

### Rule explosion

Defaults and exceptions can become difficult to review even when each rule is
correct. Keep packs bounded, cite every rule, test each reasoning shape, and
use static authoring tools to find overlap and unreachable coverage. The
[DMN compiler](../spec/dmn.md) addresses part of this at authoring time — a
`UNIQUE` decision table whose rows cannot be proven disjoint is a compile
error naming the row pairs, rather than a table whose overlap surfaces later
as an adjudication conflict. The [static pack verifier](../spec/pack-verification.md)
addresses the rest: `python -m duly_assurance prove` reports, for every pair of
same-priority rules concluding one attribute, either a proof that they cannot
both fire or a concrete assignment under which they do, and separately reports
the input regions where *no* rule concludes a declared decision attribute. Both
answers are witnessed — the coverage gap in `county-recording-us` for a
jurisdiction the pack does not encode is found without being told to look for
it. Neither answer changes a decision; the tool runs at validation time and its
output never enters a receipt.

### False confidence in integrity controls

Hashes detect mutation; they do not authenticate a producer. The append-only
SQLite API preserves history by convention, but direct database access is not
tamper-proof storage. Signatures, identity, authorization, retention, and
evidence custody belong in the deployment architecture.

### Distribution drift and biased labels

A new form template or extractor version can invalidate calibration
assumptions. Review-queue labels cover a selected slice of traffic. Production
evaluation needs representative sampling, segmentation by adapter/model
version, and explicit drift monitoring.

### Bypassed seams

Because duly is composable, callers can invoke the kernel without envelope,
schema, ontology, or store checks. Expose a narrow internal platform API that
enforces the whole admission and as-of sequence instead of letting every
application compose it differently.

## Integration guidance for a platform team

**Current maturity:** duly is pre-alpha, its contracts are v0 and may break
before v1.0, and its SQLite stores, in-process demo, and reference wiring are
not a production deployment blueprint. The responsibilities below describe
how a platform team should compose the current contracts, not a claim that the
repository already supplies enterprise operations.

A production integration should treat duly as a decision component inside a
larger workflow:

1. **Own the domain artifacts.** Version and retain the ontology, rule packs,
   calendars, citations, decision phrasing, and golden corpus — the wording an
   adjudicator reads is an adopter-owned artifact, not something inherited from
   this repository's reference wiring. Never mutate a released version in
   place.
2. **Wrap the extractor.** Require it to emit a content-addressed rendition,
   atomic grounded facts, confidence metadata, and a complete run envelope.
3. **Build one admission service.** Validate the JSON contract, verify the
   envelope and spans, enable the deployment's ontology registry, and write
   only through the append-only store API.
4. **Project before adjudicating.** Resolve the exact knowledge and effective
   times through the store, then pass that projection and the matching pack to
   `adjudicate()`. Never default to the wall clock.
5. **Persist the full evidence chain.** Source bytes, renditions, facts,
   envelopes, rule-pack artifacts, receipts, and correction events have
   different retention roles; a receipt alone cannot resolve a quote.
6. **Queue abstentions explicitly.** Call the review-queue integration, use
   optional `routedTo` labels for selection when packs provide them, and define
   queue ownership, service levels, correction authority, and the operational
   meaning of a default decision produced alongside an abstention.
7. **Keep actions outside the kernel, and reasoning too.** The orchestrator
   should consume the receipt, enforce authorization and freshness, and record
   any consequential side effect separately. That is only half the boundary: an
   integration can respect it perfectly at the API level and still hold a
   second copy of the rule — a business-day wait, a jurisdiction table, a
   threshold — beside the call that asked about it. Such a copy is invisible at
   the seam, because the seam still looks correct. It is detectable by
   mutation: change the rule in the pack, change nothing in the orchestrator,
   and the orchestrator's behaviour must change.
   [examples/closing-scheduler](../examples/closing-scheduler/README.md) is the
   first thing in this repository that demonstrates that boundary rather than
   asserting it, and that mutation is what it demonstrates it with. It plans
   and explains; it still executes nothing, so the *action* half of the
   boundary remains asserted rather than shown.
8. **Gate every change.** Run pack tests, schema and ontology checks, golden
   replay, and impact analysis before promoting a new artifact version.
9. **Measure layers separately.** Extraction accuracy, fact admission,
   abstention, rule correctness, decision outcomes, review rate, latency, and
   drift are different metrics.

For an executable walk through these artifacts, use the
[demo tour](demo_tour.md). For the actual JSON from source text through human
correction, use [Follow one fact](follow-one-fact.md).

## How the architecture can grow

These are extension paths, not commitments or a second roadmap. The
[README roadmap](../README.md#roadmap) is the canonical release plan.

| Demonstrated need | Credible extension | Invariant to preserve |
|---|---|---|
| Rule authors need safer tools | DMN-to-IR authoring, Z3 overlap/coverage analysis, and backward what-if queries (**all shipped** — see below), plus a rule-id convention with the pre-existing ids grandfathered rather than renamed | Authoring tools assist and solvers advise; only the deterministic kernel emits receipts, and no solver runs on the adjudication path |
| Rule authors need those tools *together* | A browsing/drafting surface that runs the validator, the pack's declared cases, an ad-hoc case, corpus impact and the solver over one draft (**shipped** — the demo's rule studio, [tour §10](demo_tour.md)) | A draft is a session artifact until a human commits it; nothing the studio does writes into `rulepacks/`, and every instrument it exposes is the shipped one called unmodified |
| An append-only history nobody can look at is indistinguishable from one that was edited | A surface that projects the case at any point on its own event log, showing what became of every fact rather than only which ones survive (**shipped** — the demo's evidence browser, [tour §11](demo_tour.md#11-the-evidence-browser)) | The browser reads; it never writes. Its projection must agree with the store's `as_of` at every horizon, and it must degrade to "there is no event log here" rather than presenting a disk fact set as a timeline with one point |
| A receipt is only as good as the recipient's ability to check it | A surface that opens any receipt — committed, or pasted from another deployment — and re-verifies it on open rather than on request (**shipped** — the demo's receipt viewer, [tour §12](demo_tour.md#12-the-receipt-viewer)) | Verification never renders what it cannot source: a missing fact set or a moved pack version is reported as unchecked, never approximated from whatever is on disk. The report is the kernel's own section structure in a third medium, never a second renderer |
| Production extraction quality must be managed | Second real adapter, representative evaluation, drift segmentation, bounded validate-and-repair before review | Every repaired proposal remains grounded, attributable, and reviewable |
| Long-running enterprise deployment | Postgres, migrations, durable queues and calibration artifacts, observability, backup/restore | Knowledge-time replay and append-only history remain semantically equivalent |
| Stronger governance | Signed run envelopes, RBAC, tenant isolation, retention controls, rule approval and rollback | Integrity, authenticity, authorization, and decision semantics remain distinct |
| Multiple entities and cross-document decisions | Quantified bindings, explicit relationships, completeness checkpoints, optional graph projection | Existing atomic facts and receipts remain canonical and old cases replay |
| Conversational investigation | Typed query API, validated natural-language-to-query translation, receipt-grounded rendering | A model may translate or phrase; it does not silently create facts or decisions |
| Governed agentic workflows | Receipt-aware action policies and idempotent orchestration adapters. The decision-consumption half now has a worked reference ([examples/closing-scheduler](../examples/closing-scheduler/README.md)); the action half — authorization, freshness, idempotency — remains open | duly remains decision authority, the orchestrator owns side effects, and the orchestrator holds no copy of the rule it just asked about |
| Higher-volume relational reasoning | Define cross-backend equivalence, then add a Datalog/Soufflé backend and differential testing | Decision semantics and trace fidelity match the reference kernel |
| Genuinely non-stratified rule fragments | Consider an ASP backend for the demonstrated fragment | Complexity is introduced locally, with deterministic selection and explainable receipts |

The durable design principle is not "use more symbolic technology." It is:

> Move only the meaning that must be governed into explicit, versioned,
> testable artifacts, and preserve the evidence at every boundary.

Better models should make the perception edge cheaper and more accurate
without changing that principle. Richer rules, graphs, or solvers should be
added only when they strengthen a demonstrated decision or governance
requirement without weakening replay.

## Reading and code map

- [Concepts](concepts.md) defines the repository's vocabulary precisely.
- [Follow one fact](follow-one-fact.md) traces a committed fact, receipt, and
  correction byte by byte.
- [Grounded-fact contract](../spec/grounded-facts.md) explains every fact and
  receipt design decision.
- [Rule IR](../spec/rule-ir.md) defines applicability, stratification,
  defeasibility, abstention, and receipt mapping.
- [Ontology conformance](../spec/ontology-conformance.md) defines the LinkML
  subset and the gate's honest boundaries.
- [PROV-O alignment](../spec/prov-o.md) explains the partial external
  provenance mapping.
- [Rule-pack authoring guide](../rulepacks/README.md) is the starting point for
  changing decision content.
- [`extraction/duly_extraction`](../extraction/duly_extraction) contains the
  adapter and run-envelope boundary.
- [`store/duly_store`](../store/duly_store) contains append-only bitemporal
  storage; [`demo/evidence_api.py`](../demo/evidence_api.py) reads that log
  back at an arbitrary horizon, which is the shortest way to see what the two
  time axes actually do.
- [`kernel/duly_kernel`](../kernel/duly_kernel) contains the reference
  interpreter and receipt builder.
- [`review/duly_review`](../review/duly_review) contains the review and
  correction loop.
- [`dmn/duly_dmn`](../dmn/duly_dmn) compiles DMN decision tables into rule
  packs, and refuses the tables it cannot compile honestly.
- [`demo/rules_api.py`](../demo/rules_api.py) is the rule studio: packs as
  decision-table grids, session-only drafts, and the validator, declared
  cases, ad-hoc adjudication, corpus impact and the solver all run over one
  candidate pack ([tour §10](demo_tour.md)).
- [`demo/receipts_api.py`](../demo/receipts_api.py) is the receipt viewer: the
  corpus browsable, any receipt openable, and three independent checks — hash,
  fact integrity, replay — run on open rather than on request
  ([tour §12](demo_tour.md#12-the-receipt-viewer)).
- [`kernel/duly_kernel/report.py`](../kernel/duly_kernel/report.py) builds one
  section structure that three renderers walk — Markdown, PDF, and
  JSON blocks for the browser — so a new medium is a new walk rather than a
  second account of the same decision.
- [`kernel/duly_kernel/rule_ids.py`](../kernel/duly_kernel/rule_ids.py) carries the
  rule-id convention and the explicit list of ids that predate it.

- [`examples/minimal-integration`](../examples/minimal-integration) is the
  shortest path from this document to running code: the five steps of an
  integration — your ontology, your facts, your pack, the adjudication, the
  verification — in about a hundred lines, checked against an installed wheel
  with duly's source tree absent.
- [`examples/closing-scheduler`](../examples/closing-scheduler) plans a mortgage
  closing with CP-SAT over adjudicated permissibility windows, and cites the
  receipt ids that constrained each date.
- [`whatif/duly_whatif`](../whatif/duly_whatif) solves a pack backwards for one
  freed input and verifies every answer by re-running the kernel on it.
- [`assurance/duly_assurance/prove.py`](../assurance/duly_assurance/prove.py)
  statically verifies a rule pack with a solver — disjointness, coverage, and
  equivalence between two packs — and names what it cannot encode instead of
  guessing.
- [`assurance/duly_assurance`](../assurance/duly_assurance) contains golden
  replay and rule-change impact analysis.
