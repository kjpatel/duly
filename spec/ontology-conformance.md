# Ontology conformance — v0 draft

[Grounded-facts D10](grounded-facts.md#d10-ontology-by-reference) made a promise with two halves: facts reference the user's ontology by CURIE + version, and duly *validates conformance* while defining no domain terms. This document is the second half made concrete: what an ontology artifact IS in duly, the two committed samples ([`ontologies/`](../ontologies/)), and the gate ([`conformance/duly_conformance`](../conformance/duly_conformance/)) that rejects a nonconforming fact loudly at the contract line.

The failure this kills: before the gate, an adapter emitting a misspelled attribute or the wrong value kind sailed through ingestion and surfaced only as a rule silently failing to bind — the quiet cousin of confident wrongness. Runnable demonstration: [`conformance_gate_demo.py`](conformance_gate_demo.py).

As with the fact contract, everything below is a design decision with its rationale and the alternative that was rejected.

---

## C1. An ontology artifact is a versioned, immutable LinkML file; the registry is `<name>/<version>.yaml`

An ontology in duly is one LinkML schema file at `ontologies/<name>/<version>.yaml`, immutable once committed — exactly the discipline rule packs follow. A fact pinning `{ontology: duly-mortgage-closing, version: "0.1.0"}` validates against that file's committed bytes forever; changes go in a new version file beside it.

**Why immutable:** `schemaRef` sits inside the fact's content hash. If 0.1.0's meaning could drift, a fact that conformed at ingestion could become nonconformant with no byte of the fact changing — the gate's verdict would stop being a property of the pinned pair. Immutability makes "conformed to duly-mortgage-closing@0.1.0" a permanent, replayable statement, the same way "decided under pack 2026.1.0" is.

**Why version pinning is exact:** no semver ranges, no "latest", no fallback across versions. A gate that quietly validated a 0.1.0 fact against 0.2.0 would be lying about what the fact's producer claimed conformance to. A registry miss is a loud `unknown_ontology` rejection that names the known versions.

**Rejected:** a database or service registry (an artifact in git versions, diffs, and reviews the way rule packs do); mutable ontology files with an internal changelog (see above — the hash pin makes mutation a lie).

## C2. Two sample ontologies, split by DOMAIN, not by vertical

The repo commits two artifacts:

- **`duly-starter-notice` 0.1.0** — insurance: the `nc:` terms the termination-notice starter and pack use. It KEEPS the exact name + version the committed insurance facts already cite.
- **`duly-mortgage-closing` 0.1.0** — mortgage closing: ALL FIVE mortgage namespaces (`trid:`, `ron:`, `pkg:`, `resc:`, `rec:`) as prefixes of one schema.

**Why by domain:** this is how real organizations model. MISMO's reference model spans all of mortgage closing; ACORD's standards span insurance lines. The five earlier names (`duly-starter-trid`, `-ron`, `-esign`, `-resc`, `-recording`) were one-per-starter — an artifact of how the demos were authored, not of how the domain is shaped. The fee, the notarization, the signing route, the rescission window, and the recording submission are facets of *one closing*.

**Why the insurance name did not consolidate too:** `golden/cases/review-0001` is the repo's only human-provenance golden case — born from a real review-arc correction, preserved forever because no seed can regenerate it ([golden/README.md](../golden/README.md)). Its facts pin `duly-starter-notice@0.1.0` inside their content hashes; renaming the ontology would strand them. The name is imperfect and kept deliberately — an honest cost of the immutability rule, recorded here rather than papered over.

**What consolidation cost, handled deliberately:** pointing the five mortgage verticals at the new name changed those facts' bytes → hashes → receipts. The starter facts were re-extracted, fixture hashes recomputed, and the golden corpus regenerated as a documented baseline change — with `notice-*` and `review-*` cases byte-untouched and impact analysis confirming 0 of 351 decisions flip (the change is identity, not semantics).

**Rejected:** one ontology per rule pack (couples vocabulary to pack boundaries — two packs over the same closing would fork its vocabulary); one global ontology (erases the domain seam and would force the insurance rename).

## C3. LinkML is the source language; the samples are genuine LinkML

The artifacts are LinkML YAML: classes with `class_uri`, attributes with `slot_uri` and typed ranges, enums with permissible values, prefixes, and standard `close_mappings`.

**Why LinkML:** it is the one schema language whose toolchain natively emits the three formats this milestone's roadmap names — JSON Schema, SHACL, and dataclasses — from a single definition, and it is YAML, reviewable in the same diffs as rule packs. The "SHACL" half of the roadmap bullet is real *through* LinkML: `linkml.generators.shaclgen` compiles the committed schema to SHACL shapes, and pyshacl validates instance data against them.

**Proven, not asserted:** marker-gated tests ([`conformance/tests/test_real_linkml.py`](../conformance/tests/test_real_linkml.py), docling-pattern — skipped when the tooling is absent) load both schemas under linkml-runtime, expand the CURIEs, generate SHACL, validate an RDF projection of a committed fact against the shapes, reject an out-of-enum mutation, and check the shapes coexist with the PROV-O export. Run them:

```bash
uv run --with linkml --with pyshacl pytest conformance/tests -m linkml
```

**Rejected:** SHACL as the authoring format (SHACL is a great validation target and a poor authoring surface; LinkML generates it); JSON Schema as the authoring format (no class/slot URIs, no mappings vocabulary, no SHACL path); OWL (expressive power nothing here needs, at a review-ability cost everything here would pay).

## C4. The enforcing validator is a pure-Python interpreter of a constrained LinkML subset

`duly_conformance` reads the YAML with stdlib + yaml and interprets exactly the subset the gate enforces. It does not import linkml-runtime.

**Why:** linkml-runtime transitively drags rdflib into the runtime, and this repo deliberately keeps RDF tooling out of its dependencies (the PROV-O work established the pattern: rdflib "stands in for the RDF tooling you already run" and is invoked via `uv run --with`). The gate runs on every envelope verification; it must not cost the project its dependency posture. The files stay genuine LinkML — provable with real tooling (C3) — while the hot path stays at zero new dependencies.

**The subset, exactly** (also in [`linkml_subset.py`](../conformance/duly_conformance/linkml_subset.py)'s docstring):

| Interpreted | Meaning to the gate |
|---|---|
| `name`, `version` | the identity a fact's `schemaRef` pins |
| `prefixes` | declared CURIE prefixes; an undeclared prefix is a load error |
| `classes.*.class_uri` | the entity-type CURIE a class defines |
| `classes.*.attributes.*.slot_uri` | the attribute CURIE, scoped to its class |
| `attributes.*.range` | mapped to a duly value kind: built-ins `string`/`decimal`/`date`/`datetime`/`boolean` map to the kind of the same name; a schema-local type with `uri: duly:money` (or `duly:entityRef`) maps to that kind; an enum range maps to `code` |
| `attributes.*.required` | parsed and carried, NOT enforced (C6) |
| `enums.*.permissible_values` | closed membership for `code` values |
| `enums.*.annotations.codeSystem` | the code-system string a fact's code value must carry |
| `enums.*.annotations.openCodeSet` | external standard (e.g. ISO 3166-2): identity checked, membership not vendored |

Everything else — descriptions, `close_mappings`/`exact_mappings`, `annotations.mismo`, `annotations.derived`, `code_set`, `imports`, `default_range` — is documentation the gate deliberately ignores. A range outside the subset is a **load-time** `OntologySubsetError`, never a silent skip at check time: the gate refuses to enforce an ontology it cannot fully interpret.

**Rejected:** depending on linkml-runtime at runtime (the dependency posture above); silently skipping unrecognized constructs (a validator that ignores what it doesn't understand converges on validating nothing).

## C5. What conformance checks — and every rejection is attributable

For each fact, in order:

1. **Registry resolution** — the `schemaRef` (ontology, version) pair exists, pinned exactly (C1).
2. **Entity type** — `entity.type` is a class the ontology defines.
3. **Attribute** — the attribute CURIE is declared *on that class*. An attribute that exists on a different class is a distinct `misattached_attribute` rejection naming both classes; an unknown attribute gets a nearest-name suggestion ("did you mean `nc:noticeMailedDate`?").
4. **Value kind** — the value's `kind` matches the slot's declared range.
5. **Code values** — for `code` kinds: the `codeSystem` string matches the enum's declared one, and for closed enums the value is a permissible value (open code sets check identity only — the gate does not vendor ISO 3166-2's membership).

Every issue carries the fact id, the pinned `ontology@version`, an issue code, and a message stating what failed — the loud, attributable rejection the roadmap bullet promised. `check_fact` returns *all* issues, not just the first.

## C6. What conformance deliberately does not check

- **Spans and hashes** — run integrity is the envelope's job (`verify_envelope` checks manifest hash, fact hashes, spans against the rendition). The gate assumes an honest artifact and asks whether its *vocabulary* is right; the two layers compose but do not overlap.
- **Required-ness / record completeness** — facts are atomic (D1); no single fact can witness a missing sibling. Completeness failures already have a first-class, replayable surface: an adjudication-time abstention on the receipt. `required` is parsed so a future record-level checkpoint could enforce it, and enforced nowhere today — stated here so nobody mistakes the parse for a check.
- **`codeSystemVersion`** — which revision of a code system a value cites is the code system's versioning policy, not the ontology's; pinning it in the gate would force every external code-system revision to become an ontology revision.
- **Cross-fact consistency** (one live fact per attribute, entity cardinality) — kernel and store semantics, versioned and tested there.

## C7. Where the gate enforces

Three surfaces, one library:

- **The extraction seam** — `verify_envelope(envelope, facts, rendition_text, registry=None)` takes an OPTIONAL `OntologyRegistry`. Provided: a nonconforming fact fails the whole run with the gate's attribution, and `ingest_envelope` writes nothing. Absent: byte-for-byte the pre-gate behavior — no existing call site changes. The gate is opt-in at the seam because the registry is the *deployment's* artifact set; the library hard-wires no repo path.
- **Spec validation** — `uv run spec/validate.py` additively checks every committed example fact against the committed ontologies.
- **CLI** — `uv run python -m duly_conformance --ontologies DIR check <paths...>` sweeps fact files or directories; `... list` prints the registry. The registry directory has no default (`DULY_ONTOLOGIES` also works): duly does not know where an adopter keeps their ontologies, and guessing its own layout is right exactly once (every class, attribute, kind, and code set). The repo-wide guarantee — every committed fact conforms — is a standing test ([`test_repo_conformance.py`](../conformance/tests/test_repo_conformance.py)).

**Why not enforce inside the store:** the store is the system of record for *what was asserted*, including facts predating an ontology version or citing an ontology this deployment doesn't hold; refusing writes there would make the store's contents a function of registry configuration. The seam (ingestion) is where a deployment's policy belongs.

## C8. A standards crosswalk instead of vendored standards

The mortgage ontology carries a crosswalk to the standards a real deployment would map to — as *references*, never as content:

- **MISMO / UCD** — MISMO's Residential reference model is distributed under license terms that do not permit redistribution, so no MISMO-derived schema content (containers, enumerations, definitions) is committed. Slots instead carry the *name* of the corresponding MISMO v3.4 data point in an `annotations.mismo` tag (`"FEE_DETAIL.FeeType"`). Name-only annotations rather than LinkML mappings, because a LinkML mapping slot holds a URI or CURIE and MISMO publishes no public term IRIs — minting fake ones under mismo.org would be exactly the invented reference this crosswalk refuses to contain.
- **FIBO** — MIT-licensed with public IRIs, so where a FIBO concept genuinely fits it appears in real `close_mappings` (e.g. `resc:Loan` → FIBO `Loan` and `LoanSecuredByRealEstate`; the `Money` type → FIBO `MonetaryAmount`).
- **ACORD** — insurance's standards body is membership-gated; the insurance ontology name-checks it in prose and carries no ACORD references at all.

Every committed MISMO name and FIBO IRI was verified against public sources before committing (the GSE UCD documentation corroborated by a public MISMO v3.4 schema binding; FIBO's published Turtle files); terms with no verifiable counterpart carry no reference — the verification notes, including what was deliberately left unmapped and why, are in [`ontologies/README.md`](../ontologies/README.md). Sparse-and-real beats complete-and-invented.

**Rejected:** vendoring MISMO/ACORD subsets (their licenses forbid it — and the gate's design goal is precisely that duly never needs to ship domain content); inventing IRIs so MISMO names could sit in `close_mappings` (a fake IRI is worse than a name honestly labeled as a name); a FIBO mapping on every slot for completeness (FIBO models financial instruments, not page-margin measurements — a stretched mapping is misinformation with a namespace).

## Honest boundaries

- **These ontologies describe the starter corpus, nothing more.** They are what a *user of the starters* brought; duly still defines no domain terms. Enums list only observed and pack-referenced values — `NoticeType` has one value because the corpus has one; that is a statement about the corpus, not about insurance.
- **The gate validates vocabulary, not truth.** A wrong-but-well-typed date conforms. Truth lives with grounding, confidence, review, and replay.
- **The pure-Python validator trusts, and proves elsewhere, that the file is LinkML.** Within the enforced subset the two implementations agree by construction (the subset is defined by what the interpreter reads); outside it, LinkML semantics the interpreter never sees cannot affect the gate's verdict. The marker-gated suite is what keeps the files honest LinkML as they evolve — and since [`.github/workflows/optional-deps.yml`](../.github/workflows/optional-deps.yml) landed it actually runs, on every change to `ontologies/` or `conformance/`, on every merge to `main`, and weekly. Before that it ran only when someone remembered, which made this sentence a hope rather than a control: the pure-Python gate would have gone on passing while the files drifted out of real LinkML, and nothing would have said so.
- **Code-system identifiers kept their original names.** Fact values still cite `codeSystem: "duly-starter-trid/fee-types"` even though the ontology consolidated to `duly-mortgage-closing`. Deliberate: a code system's identity is separate from the ontology that binds to it (FHIR's value sets versus profiles is the same separation), the enum's `annotations.codeSystem` declares which identifier its values live under, and renaming the strings would have churned every mortgage fact a second time for zero semantic gain.
- **`ron:Closing` exists for one fact.** The starter's closing-date fact attaches to a Closing entity, not the Notarization; the class is as small as the data that needs it.

## Seeing it work

- **[`conformance_gate_demo.py`](conformance_gate_demo.py)** — the committed TRID fee fact passes; a misspelled attribute, a wrong value kind, and an out-of-enum code are each rejected with fact id, ontology@version, and reason. `uv run python spec/conformance_gate_demo.py`.
- **`uv run python -m duly_conformance --ontologies ontologies check starters golden/cases rulepacks spec/examples`** — all committed facts conform.
- **`uv run --with linkml --with pyshacl pytest conformance/tests -m linkml`** — the real-tooling proof (C3).
- **Adopting your organization's ontology** — the swap walkthrough is in [`ontologies/README.md`](../ontologies/README.md): author a LinkML overlay of the MISMO subset your shop uses, point `schemaRef` at it, and the same gate enforces it; nothing else changes.
