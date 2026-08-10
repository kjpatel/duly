# Ontologies

The bring-your-own-ontology registry: one LinkML schema file per
`<name>/<version>.yaml`, **immutable once committed** — a fact pinning
`schemaRef: {ontology, version}` validates against that exact file forever,
the same discipline rule packs follow. The full design, decision by
decision: [spec/ontology-conformance.md](../../spec/ontology-conformance.md).
The gate that enforces these: [conformance/duly_conformance](../../conformance/duly_conformance/).

## Honest labeling

These are the ontologies a *user of the starters* brought to duly — duly
itself still defines no domain terms (README, "Why bring-your-own
ontology"). They describe exactly the vocabulary the committed starter
corpus, golden cases, and rule packs use: enums list only observed and
pack-referenced values, and classes are as small as the data that needs
them. A real deployment replaces them (see the swap walkthrough below).

| Artifact | Domain | Covers |
|---|---|---|
| [`duly-starter-notice/0.1.0.yaml`](duly-starter-notice/0.1.0.yaml) | insurance | `nc:` — the policy and the termination notice. Keeps the exact name the committed insurance facts (including the preserved-forever `examples/golden/cases/review-0001`) already pin inside their content hashes. |
| [`duly-mortgage-closing/0.1.0.yaml`](duly-mortgage-closing/0.1.0.yaml) | mortgage closing | `trid:`, `ron:`, `pkg:`, `resc:`, `rec:` — one artifact for the whole domain, the way MISMO's model spans all of mortgage closing. Carries the standards crosswalk. |

Both files are genuine LinkML — not merely acceptable to duly's own
pure-Python subset validator. Real LinkML tooling proves it, and
[CI runs that proof](../../.github/workflows/optional-deps.yml) on every change
under `examples/ontologies/`, on every merge to `main`, and weekly. Run it yourself the
same way (marker-gated, skipped when the tooling is absent — the docling
pattern):

```bash
uv run --with linkml --with pyshacl pytest examples/tests -q -m linkml
```

This matters more than it looks. The hot-path gate deliberately does not import
linkml-runtime, so it would keep passing on a file that had stopped being valid
LinkML. This suite is the only thing standing between "duly's validator accepts
it" and "it is what we say it is".

The suite is [`examples/tests/test_real_linkml.py`](../tests/test_real_linkml.py),
and it lives there because its subject is *these two artifacts* — it dies with
them. That line used to read `pytest conformance/tests -m linkml`, which after
the move collected **zero tests and exited 0**: the loudest-looking check in
this file, saying nothing, in the exact shape CLAUDE.md warns about. Run a
marker-gated suite once and read the collected count, not the exit code.

## Useful commands

Run from this directory (`examples/ontologies/`) — `--ontologies .` is the
registry root, and the check paths are relative to it:

```bash
uv run python -m duly_conformance --ontologies . list                    # registry contents
uv run python -m duly_conformance --ontologies . check ../starters ../golden/cases ../rulepacks ../../spec/examples
uv run python ../../spec/conformance_gate_demo.py                        # the gate, loudly
```

The same sweep from the repository root, which is the form CI and the
pack-authoring guide use:

```bash
uv run python -m duly_conformance --ontologies examples/ontologies \
    check examples/starters examples/golden/cases examples/rulepacks spec/examples
```

`--ontologies` has no default and will not acquire one: a registry path that is
right in this repository is wrong for every adopter, and the default that used
to supply duly's own directory hid an entire class of unencodable-pack
diagnostics behind it (CLAUDE.md, "a path relative to a *package* resolves
everywhere"). `DULY_ONTOLOGIES` works too.

## Adding terms for a new rule pack

Step 2 of [authoring a pack](../rulepacks/README.md#before-you-open-it-in-this-order),
and the one that fails in a suite pack authors do not expect to touch.

1. **Never edit a committed version file.** `schemaRef` is inside every fact's
   content hash, so an in-place edit silently breaks the relationship between
   the facts already committed and the vocabulary they claim to speak. New
   terms go in a new `<name>/<version>.yaml`, and the facts that need them pin
   the new version.
2. **A new domain gets a new directory; an existing domain gets a new version
   of its own artifact.** `duly-mortgage-closing` carries five prefixes
   (`trid:`, `ron:`, `pkg:`, `resc:`, `rec:`) on purpose — one artifact spanning
   a domain, the way MISMO's model does. Splitting per pack would multiply
   `schemaRef`s across facts that describe the same closing.
3. **Declare everything the pack or its targets name** — entity types,
   attributes, and every code value, including the ones only a rule's guard
   mentions. [`examples/tests/test_example_conformance.py`](../tests/test_example_conformance.py)
   sweeps every committed fact and fails loudly; a code value that only appears
   in a `when` clause fails less loudly, as a rule that never binds.
4. **Crosswalk annotations are verify-or-omit.** A MISMO data-point name goes in
   `annotations.mismo` only if you checked it against a public source; a FIBO
   `close_mappings` IRI only if you fetched it. Sparse and real over complete
   and invented — the deliberately-unmapped list above is what that discipline
   looks like written down, and adding to it is a contribution.
5. **Renaming an ontology is corpus churn, forever.** The name sits in every
   fact's hashed bytes, so a rename rewrites fact hashes, receipt `inputFacts`,
   and every affected golden receipt. `duly-starter-notice` keeps its awkward
   name for exactly this reason: the preserved-forever
   `examples/golden/cases/review-0001` pins it.

## The standards crosswalk (and why the standards are not vendored)

**MISMO** distributes its Residential reference model under license terms
that do not permit redistribution, and **ACORD**'s standards are
membership-gated — so no schema content derived from either is committed
here. Instead, mortgage slots carry the *name* of the corresponding MISMO
v3.4 data point as an `annotations.mismo` tag (`"FEE_DETAIL.FeeType"`);
name-only, because MISMO publishes no public term IRIs a LinkML mapping
could carry, and this crosswalk does not mint fake ones. **FIBO** is
MIT-licensed with public IRIs, so genuinely fitting FIBO concepts appear
as real `close_mappings`.

Every committed reference was verified against public sources
(2026-07-30): the MISMO data-point names against the GSE Uniform Closing
Dataset documentation, corroborated by a public MISMO v3.4 schema binding;
the FIBO IRIs by fetching the published Turtle files at
spec.edmcouncil.org. Deliberately left unmapped, because no public
verification was possible: `ron:notarizationMethod` (the public MISMO v3.4
model predates RON data points), `pkg:esignConsentObtained`,
`resc:securedByPrincipalDwelling`, the rescission window booleans, the
recording page-format measurements, and every derived decision attribute
except `resc:rescissionDeadline`. FIBO's `PromissoryNote` was checked and
found absent from current FIBO master, so the `PromissoryNote` document
type carries no FIBO mapping. Sparse and real over complete and invented.

## Adopting your organization's ontology

The point of the gate is that this directory is *replaceable*. To make a
duly deployment speak your shop's MISMO profile (the same recipe applies
to ACORD, FHIR, or anything project-local):

1. **Author a LinkML overlay of the MISMO subset your shop uses** — say
   `acme-mismo-profile/1.0.0.yaml`. One class per entity your extractors
   emit, `class_uri`/`slot_uri` CURIEs under your prefix, ranges from the
   supported subset (`string`/`decimal`/`date`/`datetime`/`boolean`, a
   `duly:money` type, enums for your code sets — closed where you own the
   values, `openCodeSet` where an external standard does). Because it is
   your license and your file, it can be as MISMO-faithful as your
   membership allows — duly never needs to see MISMO itself.
2. **Point `schemaRef` at it** — your adapters emit
   `{"ontology": "acme-mismo-profile", "version": "1.0.0"}` on every fact.
3. **Hand the registry to the seam** —
   `verify_envelope(..., registry=load_repo_registry("ontologies"))` (or
   an `OntologyRegistry` built from wherever you keep the files). Every
   nonconforming fact now rejects the run loudly, with attribution.

Nothing else changes: the kernel, packs, store, receipts, and replay are
ontology-agnostic by construction — they see CURIEs and pinned
`schemaRef`s, never the schema. Version your overlay like a rule pack: new
version file per change, old facts keep validating against the version
they pin.
