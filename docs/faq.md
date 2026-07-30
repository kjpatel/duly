# FAQ

Questions people actually ask when they first see this project, answered in plain terms. The full arguments live in the [README's design-choices section](../README.md#design-choices-and-why) and the [specs](../spec/grounded-facts.md); this page is the short form.

## Why not just an LLM with citations?

Because a model's stated reasoning is not its actual reasoning. An LLM can attach citations to an answer, but the citation is part of the *output*, not evidence of the *process* — there is no guarantee the cited passage produced the conclusion, and no way to re-run the same question two years later and get the same answer under the rules that applied then. duly uses the model where models are strong (reading messy documents and proposing facts) and a deterministic rules engine where accountability lives (deciding what those facts mean). The audit trail is a byproduct of evaluation, not a narrative about it.

## How is this different from RAG with a verification step?

RAG retrieves text to help a model answer; the model is still the decision-maker, and a "verifier" checks its output after the fact. In duly the relationship is inverted: extraction produces *typed, span-grounded facts*, and the decision comes from versioned, cited, effective-dated rules — the deterministic layer *is* the decision procedure, not a checker bolted onto a generative one. The practical differences: the same inputs produce byte-identical receipts forever, a rule change is a versioned edit with an impact report ("this flips N of M historical decisions"), and when the extraction is uncertain the system abstains and routes to a human instead of guessing fluently.

## Then why not a rules engine alone? Those have existed for decades.

Rules engines assume structured input, and documents are not structured input. The gap between "a PDF" and "facts a rules engine can bind" is where these projects historically die — someone hand-builds a brittle extraction layer, confidence is lost at the handoff, provenance evaporates, and nobody can say later why the engine believed what it believed. duly's whole scope is that seam: a contract for how a probabilistic extractor hands facts to a deterministic reasoner with source spans, calibrated confidence, abstention semantics, and two time axes intact.

## What does "neurosymbolic" mean here, concretely?

A division of labor, not a hybrid inference algorithm: **perception proposes, logic disposes.** The neural layer (any document-AI extractor — the interface is pluggable) reads documents and proposes grounded facts with confidence scores. The symbolic layer (a deterministic rule interpreter) decides. Neither does the other's job: the model never concludes, the rules never read. If you replace the extractor with a better one next year, no rule changes and no decision silently shifts — new facts, new receipts, old receipts still replay.

## What happens when the extraction is wrong?

The expensive failure mode in regulated work is not being wrong — it is being *confidently* wrong. duly's architecture converts that into explicit abstention: rule packs carry confidence floors, a below-floor fact is excluded from binding and recorded on the receipt as an abstention with routing, a human reviews and corrects it, the correction enters the store as a first-class superseding fact, the decision re-runs, and the whole arc is frozen as a regression case so the same mistake is caught automatically forever after. You can walk this loop in the [demo](demo_tour.md) in about two minutes.

## Why "bitemporal"? One timestamp has always been enough for my systems.

The defining query of regulated replay is: *evaluate a March file under March rules, as we understood the facts in March.* That needs two independent time axes — when a fact or rule applies in the world (effective time) and when the system learned it (knowledge time) — because they routinely disagree: a correction learned in November changes what we know, not what was true in March. One timestamp can answer "what do we believe now"; it cannot answer "what would we have decided then," and the second question is the one an auditor asks. Retrofitting the second axis onto a unitemporal store is a rewrite, which is why duly carries both from day one.

## Who writes the rules, and what happens when a regulation changes?

Rule packs are YAML: each rule carries a legal citation, a priority, an effective window, and explicit exception relationships — designed for compliance analysts and domain experts, with a [step-by-step authoring guide](../rulepacks/README.md). When a regulation changes, you add a new rule version with its own effective date; nothing retrains, old decisions still replay under the old rule, and CI reports exactly which historical decisions the change would flip. (A decision-table authoring surface for analysts who prefer DMN to YAML is on the [roadmap](../README.md#roadmap).)

## Can our existing data-governance or lineage tooling read duly's audit trail?

If it speaks RDF, yes — without a duly-specific importer. duly ships [PROV-O JSON-LD contexts](../spec/prov-o.md): external mapping files under which stored facts and receipts (bytes unchanged — they are content-addressed) expand to standard W3C PROV triples. Load them into any triple store and questions like *which decisions ever used a fact from this document?* or *which decisions relied on a human correction, and what did it supersede?* become ordinary SPARQL — there is a [runnable demonstration](../spec/provo_sparql_demo.py) answering exactly those, and the demo server exports any receipt as JSON-LD via `GET /api/report?format=jsonld`. One honest boundary: the mapping is deliberately partial — bitemporal effective time, confidence, and abstentions have no faithful PROV equivalent and stay in duly's own namespace, documented term by term.

## We already have a MISMO/ACORD/FHIR data dictionary. Do we have to adopt duly's schema?

No — the dependency points the other way: duly has no domain schema, and your facts declare *yours*. Every fact pins `schemaRef: {ontology, version}`, and a [conformance gate](../spec/ontology-conformance.md) checks the fact against the versioned LinkML artifact that pin names — entity type defined, attribute declared on that class, value kind matching, code values in range. Without the gate, a misspelled attribute from an extractor surfaced only as a rule silently failing to bind; with it, ingestion rejects the run loudly, naming the fact, the ontology version, and what failed. The repo ships two sample ontologies (what a starter user would have brought — including a name-verified crosswalk to MISMO and FIBO, since licensing forbids vendoring the standards themselves), and a [walkthrough](../ontologies/README.md) for authoring an overlay of the standard subset your shop actually uses and pointing `schemaRef` at it. Nothing else changes when you swap: the kernel, packs, and receipts see CURIEs and pins, never the schema.

## Why are holiday dates hardcoded in rule packs instead of computed?

Because "last Monday in May" is legal content, not engine code. Jurisdictions differ on holiday sets and observance shifting (TILA's precise business day deliberately excludes § 6103(b) shifting, per the Reg Z commentary), so the dates live as data inside the pack — cited, reviewable where rules are reviewed, versioned inside the receipt's pack pin, and replayable forever. The trade (duplication across packs) and the future shared-registry shape are documented in [spec/rule-ir.md](../spec/rule-ir.md).

## Can I author rules as DMN decision tables instead of YAML?

Yes, for the subset duly can execute honestly. `python -m duly_dmn compile my-rules.dmn -o rulepacks/my-pack/pack.yaml` turns a DMN 1.3+ decision table into a rule pack; the kernel cannot tell the result from a hand-written one, and `dmn/tests/test_equivalence.py` proves it by adjudicating the same facts under compiled and hand-written versions of the TRID rules, then comparing decision, rules fired, defeat chains, and input facts. Three things will surprise you. Every row needs `duly:ruleId`, `duly:citation`, and `duly:effectiveFrom` annotation columns — the compiler will not invent an id, a citation, or a date on your behalf. Only `UNIQUE`, `FIRST`, and `PRIORITY` compile; `COLLECT` and friends return lists, and a duly decision is one value for one attribute. And compiling is step 1 of the [authoring guide](../rulepacks/README.md), not all of it — `expected.yaml`, a starter, demo verdict phrasing, and a golden-corpus generator template are still yours to write. The full supported subset, the annotation convention, and every refusal class: [spec/dmn.md](../spec/dmn.md).

## How do I know a rule pack does not contradict itself?

Two layers, answering different questions. The kernel refuses to load an ambiguous pack outright: two rules concluding the same attribute at the same priority are a validation error unless it can *prove* they never both apply. But its proof set is deliberately tiny — disjoint effective windows, or contradictory quoted-string equality guards — so a boolean split, a numeric range, or a guard on a derived value comes back "cannot prove", which is a statement about the validator, not about your rules. Authors then write an `overrides` or spread the priorities apart, and record the real argument in a code comment.

`python -m duly_assurance prove` closes that gap with a solver. It answers with a proof, with a concrete counterexample — the exact fee amount at which both rules fire — or by naming the construct it could not encode. Two comments in the shipped TILA pack claimed disjointness the validator could not see; both are now discharged mechanically, including one over a rescission deadline the pack *computes* from its own business-day calendar. It also answers the reverse question — which input regions your rules leave with no conclusion at all — which is how you find out whether a fail-closed gap is the one you intended.

It runs at validation time, never during adjudication. The solver is an optional dependency, the kernel does not import it, and nothing it produces reaches a receipt — so a green run tells you your rulebase is internally consistent, which is a real and previously uncheckable property, and still not the same thing as being right about the law. See [spec/pack-verification.md](../spec/pack-verification.md).

## Is this a product I can deploy?

Not yet — it is a pre-alpha specification with a working reference implementation. What runs today: six rule packs across two domains, an interactive demo of the full extract → decide → abstain → correct loop, and a 351-case corpus that replays byte-for-byte on every push. Breaking changes are expected until v1.0. The most useful thing an early adopter can do is pressure-test the [contract's open questions](../spec/grounded-facts.md#open-questions) against a real workflow.
