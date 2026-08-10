# Compatibility — the stability policy

Who this is for: an adopter deciding whether to build on duly, and whoever is about to change something that adopter depends on. [docs/release-process.md](../docs/release-process.md) is the mechanical companion — which number moves for a given change, what to run before tagging. This document is what those numbers *mean*.

Every contract in this repository carried "v0 — may break" from M1 to v1.0. This is what that stops meaning, stated per contract, because the three contracts break differently and stabilising them is three different acts.

The one-sentence version: **duly holds the bytes stable, and prices a break rather than forbidding one.** A fact, a receipt or a pack written against v1.0 goes on meaning exactly what it meant. What the toolkit can *additionally* express afterwards is governed by the semantics version (C3), not by this policy — which is why the policy can be strict without being a ceiling.

**Read C9 first if you read one clause.** It is the load-bearing one, and the reason every clause above it can be strict: a break here is not forbidden, it is *procedural*. What this project deliberately does not claim is the unauditable version of the promise —

> "We will never break this" is a claim no reader can check and no test can hold anyone to. "Every break is a major version, follows a written procedure, and is caught by a named check if it is taken by accident" is a claim this repository **enforces**, and the enforcement is the thing worth reading. The adjective is not the guarantee; the machinery is.

The machinery is what v1.0 actually ships: content addressing over canonical bytes, a decision-semantics version with a replay guard that refuses receipts it has no standing to check, committed canonical-form and decision-digest vectors, a corpus of 351 receipts that replays byte-for-byte on every push, and the version-scope discipline in [release-process.md](../docs/release-process.md). That is an architecture that **can** be locked, and every clause below is duly holding itself to it.

**The pre-adoption clause.** duly has no external adopters yet — [first adoption is an M6 item](../README.md#m6--durable-deployment-and-extraction-evaluation), reported by an outside team rather than claimed here. Until one exists, these contracts are held stable by policy and by the checks above rather than by anyone's dependency on them, and **a break remains a move this project is willing to make**: a deliberate, versioned, documented major-version event, not the betrayal of a promise. What real adoption changes is not the discipline — none of it is loosened by the absence of an adopter — but the *cost* of a break, which is exactly the pressure that should decide whether one is worth taking. Stating this is the point: a stability claim that outruns its evidence is the kind of claim this project spends the rest of its documentation refusing to make.

Two of the clauses below are behaviour rather than intention, and both run: [`compatibility_demo.py`](compatibility_demo.py) takes a committed receipt, shows four run-level changes that move its hash and not its decision digest (C4), and has this kernel refuse a perfectly-sealed receipt claiming semantics it does not implement (C3).

As with the fact contract, the DMN compiler, the conformance gate and the static verifier, everything below is a decision with its rationale and the alternative that was rejected.

---

## C1. What is held stable, and what that means for each

| Contract | Held stable means | A break is | Detected by |
|---|---|---|---|
| **Fact** ([schema](../core/duly_core/schemas/grounded-fact.schema.json)) | the schema is closed; a given fact's hashed bytes never change | any schema change at all | `spec/validate.py`, conformance sweep |
| **Receipt** ([schema](../core/duly_core/schemas/decision-receipt.schema.json)) | the same, and there is no extension point (C2) | any schema change at all | `verify` |
| **Rule IR** ([spec](rule-ir.md)) | a pack that loads under v1.0 loads under every later 1.x, and decides the same way | a pack that used to load doesn't, or loads and decides differently | `examples/tests/test_rulepacks.py`, each pack's `expected.yaml` |

The fact and receipt rows say *any change at all* for a reason that is structural rather than strict: both schemas are `additionalProperties: false` and both bodies are hashed whole. **"Additive and backward-compatible" does not exist for a content-addressed document.** Adding an optional field nobody sets still changes the canonical bytes of every document that adopts it, and a document that declines to adopt it is a document the new schema and the old one disagree about. There is no version of this that is only slightly breaking.

The IR row is different in kind: it is a **floor, not a ceiling**. Later 1.x versions may accept more syntax than v1.0 accepts. They may never accept less, and they may never make an accepted pack mean something else. Both halves matter, and the second is the one that will be violated by accident:

> **A validator that gets stricter is a breaking change**, even though it adds no syntax and fixes a real problem.

[rule-ir.md](rule-ir.md) open question 4 — should `validate_pack` type-check expressions — is exactly this shape. Answering it *yes* after v1.0 rejects packs that used to load. It stays open, and this is the sentence that prices it.

**Rejected:** *stating the IR's stability by capability ("v1.0 supports these constructs") rather than by pack ("a pack that loads keeps working").* Capability lists sound more precise and are unenforceable — no test in this repository can assert a capability list, and every test can assert that the six committed packs still load and still produce their declared outcomes. A promise the corpus can check is worth more than a promise the prose is more specific about.

## C2. The receipt has no extension point

The receipt schema is closed. Nothing may be added to it — not by duly, not by an adopter, not behind a feature flag. This is a v1.x prohibition with a real argument behind it, not a vow: a major version could decide otherwise, and C4 is careful to leave that door open (the digest is a function, never a field, so nothing has been committed to the alternative). What follows is the argument, which is what should keep the door shut. Anything that wants to travel with a receipt travels **beside** it, in a separately-hashed document that references it by `receiptSha256`. This is the idiom [prov-o.md](prov-o.md) already established for exports: *wrap, never edit*.

Three candidates were on the table when this was decided, and each has a home that is not the receipt:

| Candidate | Where it lives instead |
|---|---|
| `rulePack.compiledFrom` — source path and hash of the DMN table a pack was compiled from ([dmn.md](dmn.md) OQ1) | the pack, which already carries it as an emitted comment, and a sidecar if it must be machine-readable |
| A declared disjointness proof for a same-priority pair ([pack-verification.md](pack-verification.md) OQ1) | the pack, as an annotation — see below |
| Envelope or receipt signatures ([grounded-facts.md](grounded-facts.md) OQ1) | a sidecar (C7) |

What they have in common is why the answer is uniform: **every one of them is producer-asserted metadata that a verifier would recompute or re-derive rather than trust.** A receipt is the one artifact here whose entire value is that a stranger can check it without trusting whoever produced it. Fields that only a trusting reader benefits from do not belong inside the thing the untrusting reader verifies.

That settles the blocking sub-question [pack-verification.md](pack-verification.md) OQ1 identified — *what does a replaying kernel do with a declared proof it cannot re-verify?* — with the only answer that keeps the trust boundary intact:

> **Nothing.** A declared proof is an annotation, for humans and for `prove`. `validate_pack` still proves disjointness itself or demands an explicit `overrides`; a pack author cannot widen kernel behaviour by asserting a proof.

**Rejected:** *a reserved `extensions` object, excluded from the hash.* It is the standard move and it is wrong here specifically: it makes the hash cover less than the document. A reader who verifies `receiptSha256` would have verified a strict subset of what they were handed, and could not tell from the receipt alone which part. That is the one property a content-addressed artifact exists to deny. A sidecar has the same information and the opposite failure mode — an absent sidecar is visibly absent, and nothing in the receipt depended on it.

## C3. The replay guarantee is scoped to semantics, not to kernels

> A receipt sealed under semantics version **V** replays byte-identically under any kernel implementing **V**. A kernel MAY implement more than one V. A semantics change is a new V, never a redefinition of an existing one. The project promises replay for every V present in the committed corpus — today, one: `0.0.1`.

Three things follow, and the third needed code.

**A semantics rev stops being catastrophic.** [release-process.md](../docs/release-process.md) §4 could previously only say that revving `SEMANTICS_VERSION` invalidates every committed receipt, and therefore that a rev was blocked. Under this clause a kernel that implements both V1 and V2 replays V1 receipts under V1 semantics; the corpus keeps its V1 cases and gains V2 ones. What was an unsurvivable event becomes an ordinary support-window question.

**Additive capability is a new V, not a free extension.** This is the counterintuitive half. A kernel that grows a construct the IR did not have — quantified bindings, say (C5) — cannot keep claiming V1, because a receipt produced from a pack using that construct would be stamped V1 and would *not* replay under an honest V1 kernel. This policy does not forbid new expressive power. It prices it: one semantics version each.

**A kernel that meets a V it does not implement must refuse.** Not attempt and fail, and not attempt and succeed by coincidence — refuse, naming the version. Before this document nothing read `engine.version` at all: `duly_assurance.verify` re-adjudicated every receipt without ever checking whose semantics it claimed, which meant the guarantee had no mechanism. [`duly_kernel.semantics`](../kernel/duly_kernel/semantics.py) is that mechanism, and it is deliberately tiny.

**Rejected:** *promising replay under "any duly kernel", with the version as documentation.* It is the promise adopters would prefer and it cannot be kept: a bug in the evaluator is fixed by changing what the kernel means, and the fix is right. Naming the semantics is what lets duly correct itself without either lying about old receipts or refusing to improve.

## C4. `decision_digest()` — what was decided, versus which run decided it

`receiptSha256` identifies an **artifact**. Two adjudications that reached the same conclusion, by the same rules, from the same facts, on different machines with different backends produce different receipt hashes — correctly, because they are different artifacts. Nothing until now could say they were the same *decision*.

[`decision_digest()`](../kernel/duly_kernel/digest.py) is that function: a pure SHA-256 over the receipt's determinant fields, in the same canonical form as every other hash here.

| In the digest | Out of it |
|---|---|
| `decision` | `id`, `receiptSha256` — they identify the artifact, and one of them is the answer |
| `asOf` | `caseId` — bookkeeping; see below |
| `rulePack.name`, `rulePack.version` | `rulePack.gitCommit`, `rulePack.url` — where a pack was *fetched from* is not what it *says* |
| `rulesFired` | `engine.kernel`, `engine.backend` — see below |
| `derivation` | |
| `inputFacts` | |
| `abstentions` | |
| `engine.version` | |

The organising principle: **everything excluded identifies the run rather than the adjudication.** A pack's identity is its name and version — that claim is already load-bearing elsewhere in this system, and `gitCommit`/`url` are provenance attached to a fetch. `engine.version` is *in* because different semantics genuinely can mean different decisions (C3), which is the whole reason that number exists.

`caseId` is the exclusion worth arguing. Dropping it means two different cases with identical inputs share a digest. That is the feature: the digest answers "was the same thing decided the same way", and noticing that two cases were decided identically is a use, not a collision. A caller who needs "this receipt, for this case" already has `receiptSha256`.

**This is how cross-backend agreement is defined.** `engine.backend` stays inside the hashed body, so a second evaluation backend cannot produce byte-identical receipts — that was always true and was recorded as an open M5 question. The question was never really "can the bytes match" but "what does agreement mean when they can't", and:

> Two receipts agree iff their decision digests are equal. Byte equality is agreement *plus* having been produced by the same run.

Nothing hashes the digest into any document, and nothing may. It is a function over a receipt, not a field in one, which is exactly what keeps it outside C2's prohibition — and what keeps the rejected option-B design (a digest field inside the receipt) recoverable by a future major version that decides differently, without any artifact having been committed to it.

**Rejected:** *removing `engine.backend` from the hashed body so that backends agree byte-for-byte.* It is a one-line change that makes the appealing property true, and it costs the receipt its answer to "what evaluated this". A receipt that cannot say which implementation produced it is a worse audit record in exchange for a convenience the digest already provides.

## C5. v1.0 holds the IR at one entity per type

[rule-ir.md](rule-ir.md) open question 1 — quantified bindings, "two fees on one loan" — **is deferred past v1.0**, and v1.0 states the boundary rather than working around it.

The honest statement of what a v1.0 pack can say: a rule binds at most one entity per `entityType` per case. A domain with genuinely repeating structure models each occurrence as its own case, or lifts the distinguishing attribute onto a single entity. The TRID pack does the former — one fee entity per case — and says so.

Three reasons, in the order they mattered:

1. **No committed pack needs it.** Six packs across two verticals; one workaround, documented at the site.
2. **It is not a change this milestone could absorb.** [pack-verification.md](pack-verification.md) OQ6 states the real cost: quantified bindings mean quantified formulas, and the decidable fragment that keeps `prove`'s `PROVED` an actual proof would have to be re-established. That is solver design.
3. **C3 makes deferral safe.** Quantified bindings arrive as a new semantics version whose kernel also implements this one. Packs written against v1.0 keep loading and deciding identically; their receipts keep replaying.

The README's concern when this was sequenced was that a guide teaching the pre-quantifier binding model would have to be rewritten. It would need a paragraph, not a rewrite — and a documented limitation an adopter can check against their own domain is worth more than a silent approximation, which is a discipline this project applies to rules and should not exempt itself from.

**Rejected:** *shipping quantified bindings inside M5.* It would be the one M5 change that moves the corpus, against a locked decision that every M5 change is inert; and it would land a rule-IR redesign in the same milestone that promises the rule IR is stable.

## C6. A review resolution supersedes the fact it rules on

[grounded-facts.md](grounded-facts.md) open question 2 is **decided: yes, for `low_confidence` items.** Resolving one is, by construction, a ruling on one specific fact, and `supersedes` is the truthful record of that act.

The evidence made this easier than the argument did. `review-0001` — the preserved-forever golden case, which no seed can recreate — already uses the superseding form, and its receipt's `abstentions` array is empty. The coexisting form, which leaves the below-floor fact live and therefore leaves a permanent `low_confidence` entry on every future receipt for an attribute that *was* used, is a branch no committed artifact exercises. Declaring a contract stable while a reachable state contradicts that contract's own definition of `abstentions` is precisely what a stability review exists to catch.

Scope, deliberately narrow:

- **Enforced at the queue boundary**, not in the store. `duly_review` refuses a `low_confidence` resolution whose correction does not supersede the item's abstained fact, and names the fact id it must carry.
- **The store keeps accepting independent human facts.** A value known from a phone call is not a ruling on an extraction, and the conflict policy already handles it.
- **`conflict` items are not covered.** Their entries carry several facts and the analogous rule is not obvious; the current behaviour stands until someone has a reason. Saying so is part of the decision.

The original sketch of this rule had the queue *stamp* `supersedes` from the entry's own fact id rather than trust a caller. It cannot: a correction arrives content-addressed, so writing a field into it changes its hash and therefore its identity, and the queue would be handing the store a document its author never sealed. Refusing and naming the required value achieves the same invariant without any component rewriting a hashed document behind its author's back — which is the rule the stamping design would have broken to enforce this one.

One cost, stated because it is real: supersession requires the store to have held the fact, which the envelope-ingest pipeline satisfies and the demo's from-disk facts do not. That is a boundary of where the queue applies, not a defect in the rule.

**Rejected:** *making it a pack-versioned policy knob.* A knob reintroduces the contradictory state under configuration, and the thing wrong with the coexisting form is not that some deployments dislike it.

## C7. Authenticity arrives in a sidecar, and the envelope reserves nothing

[grounded-facts.md](grounded-facts.md) open question 1 — should the run envelope reserve a `signatures` affordance for a later asymmetric-signature scheme — is **decided: no affordance, and none is needed.**

A signature inside the envelope's hashed body is circular: `contentHash` covers every field, so signing the canonical bytes and then storing the signature changes the bytes that were signed. The escape is to exclude `signatures` from the hash, and that is C2's rejected `extensions` object wearing a different hat — the hash would cover less than the document.

So signatures travel as a separately-hashed sidecar keyed by the envelope's `contentHash`, exactly as receipt sidecars are keyed by `receiptSha256`. The consequence is that the v1.0 envelope shape needs no hole for a feature that has not been designed, and the existing claim that "adding signatures later breaks nothing" stops being a hope and becomes a mechanism.

**Rejected:** *reserving an optional `signatures` array now, excluded from the hash.* A field with no reader, that nothing forces to move, in a document whose value is that everything in it is covered by one hash.

## C8. Version scopes: one package number, and what a pack version means

Two conventions [release-process.md](../docs/release-process.md) recorded as unresolved, resolved here.

### The package `__version__` strings

**`duly_kernel.__version__` stays. The other six are deleted** (`duly_core`, `duly_store`, `duly_assurance`, `duly_calibration`, `duly_review`, `duly_extraction`); `duly_conformance`, `duly_dmn` and `duly_whatif` never had one.

The kernel's is kept because it is the only one that expresses a decision the project has actually made: the kernel package stays `0.0.1` while the distribution goes `1.0.0`, because the kernel's code did not change meaning while the distribution's promise did. Delete it and there is nowhere to say that. It also has a reader — [`test_engine_identity.py`](../kernel/tests/test_engine_identity.py) manipulates it to prove `SEMANTICS_VERSION` is not coupled to it.

The other six expressed nothing. They had no reader, no rule forcing them to move, and three packages had already skipped the convention without anyone noticing — which is the diagnosis, not an inconsistency to tidy up. A number nobody reads and nothing forces to move becomes a lie the first time a package changes. Adopters who want the shipped version read `importlib.metadata.version("duly")`, which is maintained by packaging rather than by memory. [`kernel/tests/test_engine_identity.py`](../kernel/tests/test_engine_identity.py) pins the count at one so the convention cannot quietly regrow.

### Rule-pack versions

The scheme was never written down, and — worth knowing before reading the rule — **it has never been exercised**: all six packs were committed at their current version and no component has ever moved. `2026.3.0` was a birth number, not the third revision of anything. What follows is therefore a rule going forward, not a description of the past.

`pack.version` is **`<content-year>.<substantive>.<clarifying>`**, and the split is drawn where the receipt draws it:

- **content-year** — the calendar year of the legal content the pack states, not the year it was released. Moving it resets the other two.
- **substantive** — a change that can flip a decision: rule logic, guards, priorities, effective windows, a rule added or removed. `impact` is expected to report flips, or the PR explains why a genuine logic change moved nothing.
- **clarifying** — a change that reaches the receipt but cannot flip a decision: citation text or URL corrections, a rule's own `version`. `rulesFired` carries all three, so these *are* corpus churn; `impact` must report zero flips against a non-empty `examples/golden/` diff.
- **no component moves** for a change that reaches no receipt at all: `phrasing:`, `question`, comments, `MODELING BOUNDARY` headers. This is already what [release-process.md](../docs/release-process.md) §3 records, and the reason presentation is excluded from every hashed body in the first place.

The third bullet is the one worth having, because it is the only version rule in this repository whose correctness CI can check: *clarifying bump ⇒ zero flips and a non-empty diff* is a mechanical assertion, and it fails loudly on a substantive change mislabelled as a typo fix.

A pack version is never changed in place ([release-process.md](../docs/release-process.md) §9). Replay rests on the repository's immutability discipline, not on a hash of the pack's bytes — which is exactly why the version has to carry meaning that a reader can rely on without re-reading the pack.

**Rejected:** *semver for packs.* `MAJOR.MINOR.PATCH` invites "is this breaking?", and for a rule pack the honest answer is almost always yes-for-somebody: any substantive change flips a decision for whoever was on the boundary. The year-led form says the useful thing instead — *which law, as of when* — and leaves "does this move my decisions" to `impact`, which answers it precisely rather than in one digit.

## C9. How a break happens

This is the clause the other eight rest on, and it is stated last only because it needs their vocabulary. **A break is available.** Every rule above can be absolute — *any schema change at all*, *never a redefinition of an existing V*, *no committed ontology version file is edited* — precisely because there is a named, affordable, visible way to make one when it is genuinely right. A contract with no break procedure is not stricter than one with a break procedure; it is a contract whose breaks happen off the record.

Within `1.x`, nothing in C1's table changes. Specifically: no field is added to or removed from the fact or receipt schema, no committed ontology version file is edited, and no pack that loads stops loading.

A break requires a **major version**, and with it:

- a CHANGELOG entry saying what stopped being true and why the alternative was worse;
- for the fact and receipt contracts, either a converter from the previous form or an explicit statement that none is possible and why;
- for a semantics change, a new V and a kernel that implements both for at least one minor version (C3).

A **Python or HTTP API** symbol is deprecated for one minor version before removal, with the replacement named in the deprecation.

### An accidental break is a red check, not a discovery

The procedure above governs breaks somebody *chose*. The reason to believe this document at all is what happens to the ones nobody chose — and in every contract it covers, that is a named failing check rather than a reader noticing:

| An unintended break in | Fails at |
|---|---|
| a fact's or receipt's hashed bytes | [`spec/validate.py`](validate.py), `python -m duly_assurance verify` over 351 committed receipts, the eleven canonical-form vectors in [`canonical-vectors.json`](canonical-vectors.json) |
| the digest's determinant set (C4) | [`decision-digest-vectors.json`](decision-digest-vectors.json) and the corpus-aggregate digest in [`test_decision_digest.py`](../kernel/tests/test_decision_digest.py) |
| what the kernel *means* (C3) | `check_replayable` refuses a foreign `engine.version` on every replay path; `impact` reports the flipped decisions |
| the rule IR's floor (C1) | [`examples/tests/test_rulepacks.py`](../examples/tests/test_rulepacks.py) and each pack's `expected.yaml` |
| the version-scope discipline (C8) | [`test_engine_identity.py`](../kernel/tests/test_engine_identity.py), which fails on `SEMANTICS_VERSION` being re-coupled to any package number |

Two of the checks are worth their asymmetry. `verify` catches a break in the bytes without knowing what the bytes are *for*; the digest vectors catch a change to what "the same decision" means, which no byte comparison can see because it is a change to the comparison itself.

**Rejected:** *promising that the contracts will never break.* It is the sentence an adopter wants and the one that costs the most to have written, in two directions at once. It cannot be kept — an evaluator bug is fixed by changing what the kernel means, and the fix is right (C3) — and it cannot be checked, so it converts an auditable engineering claim into a matter of the project's word. The version discipline is strictly stronger: it survives being wrong.

### What this policy does not cover

Stated plainly, because a policy that quietly covers everything is not believed:

- **The four demo surfaces** and their HTTP APIs. The demo is toolkit, not a product; its routes carry their own `FastAPI(version=…)` and move independently.
- **CLI output formats** for `prove`, `whatif`, `impact` and the conformance gate. Their *verdicts* are stable vocabulary; their rendering is not.
- **The calibration package**, which is deliberately unfitted and whose interfaces expect to move when real labels exist.
- **The six rule packs, the starters, and the golden corpus.** They are example content (`examples/`), not contract. The corpus's replay property is a promise; its contents are not.

## Open questions

1. **How long is a semantics support window?** C3 says a kernel MAY implement more than one V and that the corpus carries cases at every promised V. It does not say for how many, and with exactly one V in existence there is no evidence to choose from. The first rev is when this must be answered.
2. **Do `conflict` review items get an analogous supersession rule?** C6 covers `low_confidence` only, on purpose.
3. **`validate_pack` type-checking** ([rule-ir.md](rule-ir.md) OQ4) is open, and C1 now prices it: answering yes after v1.0 is a breaking change. That may make one of the two narrower shapes — inferring kinds from the pack's own `then.value` declarations, or keeping the check in `prove` — the only affordable answers.
4. **Digest stability across a semantics rev.** `engine.version` is inside the digest, so a V1 and a V2 receipt for the same conclusion have different digests even when both kernels agreed. That is correct for "same decision under the same semantics" and unhelpful for "did the rev change this outcome" — which impact analysis answers instead, over the corpus. Whether a semantics-free variant earns its place is not yet clear.
