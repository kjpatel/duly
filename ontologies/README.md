# Ontologies

The bring-your-own-ontology registry: one LinkML schema file per
`<name>/<version>.yaml`, **immutable once committed** — a fact pinning
`schemaRef: {ontology, version}` validates against that exact file forever,
the same discipline rule packs follow. The full design, decision by
decision: [spec/ontology-conformance.md](../spec/ontology-conformance.md).
The gate that enforces these: [conformance/duly_conformance](../conformance/duly_conformance/).

## Honest labeling

These are the ontologies a *user of the starters* brought to duly — duly
itself still defines no domain terms (README, "Why bring-your-own
ontology"). They describe exactly the vocabulary the committed starter
corpus, golden cases, and rule packs use: enums list only observed and
pack-referenced values, and classes are as small as the data that needs
them. A real deployment replaces them (see the swap walkthrough below).

| Artifact | Domain | Covers |
|---|---|---|
| [`duly-starter-notice/0.1.0.yaml`](duly-starter-notice/0.1.0.yaml) | insurance | `nc:` — the policy and the termination notice. Keeps the exact name the committed insurance facts (including the preserved-forever `golden/cases/review-0001`) already pin inside their content hashes. |
| [`duly-mortgage-closing/0.1.0.yaml`](duly-mortgage-closing/0.1.0.yaml) | mortgage closing | `trid:`, `ron:`, `pkg:`, `resc:`, `rec:` — one artifact for the whole domain, the way MISMO's model spans all of mortgage closing. Carries the standards crosswalk. |

Both files are genuine LinkML — not merely acceptable to duly's own
pure-Python subset validator. Real LinkML tooling proves it, and
[CI runs that proof](../.github/workflows/optional-deps.yml) on every change
under `ontologies/`, on every merge to `main`, and weekly. Run it yourself the
same way (marker-gated, skipped when the tooling is absent — the docling
pattern):

```bash
uv run --with linkml --with pyshacl pytest conformance/tests -m linkml
```

This matters more than it looks. The hot-path gate deliberately does not import
linkml-runtime, so it would keep passing on a file that had stopped being valid
LinkML. This suite is the only thing standing between "duly's validator accepts
it" and "it is what we say it is".

## Useful commands

```bash
uv run python -m duly_conformance --ontologies . list                    # registry contents
uv run python -m duly_conformance --ontologies . check ../starters ../golden/cases ../rulepacks ../spec/examples
uv run python spec/conformance_gate_demo.py                              # the gate, loudly
```

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
