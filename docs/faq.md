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

If you would rather see it than read about it, the demo's [evidence browser](demo_tour.md#11-the-evidence-browser) puts a knowledge-time dial over a case: drag it back past a reviewer's correction and the corrected fact becomes not-yet-known, the below-floor machine fact it replaced goes live again, and the questions that cite each one move with them.

## Can I see the actual document, or only the text your extractor pulled out of it?

Both, and the difference is deliberately not smoothed over. A fact's grounding cites two different things: the source document's SHA-256 — the bytes — and a character span into a *rendition*, which is one extractor's reading of those bytes. The [evidence browser](demo_tour.md#11-the-evidence-browser) serves the committed PDF beside the rendition and tells you whether the file still hashes to what the facts cite.

What it will not do is draw highlights on the PDF. Character offsets are not page coordinates, and no fact in the contract carries the latter; an overlay computed from offsets would be a guess presented with the authority of provenance. The spans are drawn where they are measured. (Facts may carry a bounding box as well as a span — see [D3](../spec/grounded-facts.md#d3-every-fact-says-where-it-came-from-a-span-or-an-attestation) — and a browser that drew those would be drawing something real; none of the committed starters carry one.)

## Who writes the rules, and what happens when a regulation changes?

Rule packs are YAML: each rule carries a legal citation, a priority, an effective window, and explicit exception relationships — designed for compliance analysts and domain experts, with a [step-by-step authoring guide](../examples/rulepacks/README.md). When a regulation changes, you add a new rule version with its own effective date; nothing retrains, old decisions still replay under the old rule, and CI reports exactly which historical decisions the change would flip. (A [decision-table authoring surface](../spec/dmn.md) for analysts who prefer DMN to YAML has shipped.)

## Can our existing data-governance or lineage tooling read duly's audit trail?

If it speaks RDF, yes — without a duly-specific importer. duly ships [PROV-O JSON-LD contexts](../spec/prov-o.md): external mapping files under which stored facts and receipts (bytes unchanged — they are content-addressed) expand to standard W3C PROV triples. Load them into any triple store and questions like *which decisions ever used a fact from this document?* or *which decisions relied on a human correction, and what did it supersede?* become ordinary SPARQL — there is a [runnable demonstration](../spec/provo_sparql_demo.py) answering exactly those, and the demo server exports any receipt as JSON-LD via `GET /api/report?format=jsonld`. One honest boundary: the mapping is deliberately partial — bitemporal effective time, confidence, and abstentions have no faithful PROV equivalent and stay in duly's own namespace, documented term by term.

## We already have a MISMO/ACORD/FHIR data dictionary. Do we have to adopt duly's schema?

No — the dependency points the other way: duly has no domain schema, and your facts declare *yours*. Every fact pins `schemaRef: {ontology, version}`, and a [conformance gate](../spec/ontology-conformance.md) checks the fact against the versioned LinkML artifact that pin names — entity type defined, attribute declared on that class, value kind matching, code values in range. Without the gate, a misspelled attribute from an extractor surfaced only as a rule silently failing to bind; with it, ingestion rejects the run loudly, naming the fact, the ontology version, and what failed. The repo ships two sample ontologies (what a starter user would have brought — including a name-verified crosswalk to MISMO and FIBO, since licensing forbids vendoring the standards themselves), and a [walkthrough](../examples/ontologies/README.md) for authoring an overlay of the standard subset your shop actually uses and pointing `schemaRef` at it. Nothing else changes when you swap: the kernel, packs, and receipts see CURIEs and pins, never the schema.

## Why are holiday dates hardcoded in rule packs instead of computed?

Because "last Monday in May" is legal content, not engine code. Jurisdictions differ on holiday sets and observance shifting (TILA's precise business day deliberately excludes § 6103(b) shifting, per the Reg Z commentary), so the dates live as data inside the pack — cited, reviewable where rules are reviewed, versioned inside the receipt's pack pin, and replayable forever. The trade (duplication across packs) and the future shared-registry shape are documented in [spec/rule-ir.md](../spec/rule-ir.md).

## Can I author rules as DMN decision tables instead of YAML?

Yes, for the subset duly can execute honestly. `python -m duly_dmn compile my-rules.dmn -o my-pack/pack.yaml` turns a DMN 1.3+ decision table into a rule pack; the kernel cannot tell the result from a hand-written one, and `examples/tests/test_equivalence.py` proves it by adjudicating the same facts under compiled and hand-written versions of the TRID rules, then comparing decision, rules fired, defeat chains, and input facts. Three things will surprise you. Every row needs `duly:ruleId`, `duly:citation`, and `duly:effectiveFrom` annotation columns — the compiler will not invent an id, a citation, or a date on your behalf. Only `UNIQUE`, `FIRST`, and `PRIORITY` compile; `COLLECT` and friends return lists, and a duly decision is one value for one attribute. And compiling is step 1 of the [authoring guide](../examples/rulepacks/README.md), not all of it — `expected.yaml`, a starter, demo verdict phrasing, and a golden-corpus generator template are still yours to write. The full supported subset, the annotation convention, and every refusal class: [spec/dmn.md](../spec/dmn.md).

## Do I have to edit YAML to work on rules?

No, though you should still read it. The demo ships a **rule studio** (<http://localhost:8788/rules>, [tour §10](demo_tour.md)) that renders every pack's rules as decision-table grids — rows are rules, columns are the inputs they bind — and lets you edit the cells, the rule forms, or the YAML text. What makes it more than a form over a file is the panel beside it: one click each for the kernel's validator, the pack's own declared cases, an ad-hoc case you build by changing input values, golden-corpus impact analysis, and (with the optional solver) a proof of whether your draft and the committed pack decide alike. Those instruments already existed as five separate command-line tools; the studio's contribution is putting them in one place, in the order that catches things, so a rule author sees them disagree. The stock demonstration is exactly that disagreement: change New York's 45-day minimum to 60, and all four declared cases still pass while the corpus reports one flipped decision.

Two things it deliberately does not do. It never writes into `examples/rulepacks/` — it hands you `pack.yaml` bytes and a diff, and `git add` is yours, the same rule as the golden-case export. And its decision tables are a *view* of the rule IR, not a DMN round trip: `duly_dmn` compiles DMN into the IR and does not decompile, so authoring through DMN is the import tab and that path is one-way on purpose.

## How do I know a rule pack does not contradict itself?

Two layers, answering different questions. The kernel refuses to load an ambiguous pack outright: two rules concluding the same attribute at the same priority are a validation error unless it can *prove* they never both apply. But its proof set is deliberately tiny — disjoint effective windows, or contradictory quoted-string equality guards — so a boolean split, a numeric range, or a guard on a derived value comes back "cannot prove", which is a statement about the validator, not about your rules. Authors then write an `overrides` or spread the priorities apart, and record the real argument in a code comment.

`python -m duly_assurance prove` closes that gap with a solver. It answers with a proof, with a concrete counterexample — the exact fee amount at which both rules fire — or by naming the construct it could not encode. Two comments in the shipped TILA pack claimed disjointness the validator could not see; both are now discharged mechanically, including one over a rescission deadline the pack *computes* from its own business-day calendar. It also answers the reverse question — which input regions your rules leave with no conclusion at all — which is how you find out whether a fail-closed gap is the one you intended.

It runs at validation time, never during adjudication. The solver is an optional dependency, the kernel does not import it, and nothing it produces reaches a receipt — so a green run tells you your rulebase is internally consistent, which is a real and previously uncheckable property, and still not the same thing as being right about the law. See [spec/pack-verification.md](../spec/pack-verification.md).

## You used a solver to pick that date. Why should I trust it?

You shouldn't, and the tool doesn't. A what-if answer — *"the notice had to be mailed by 2026-04-24"* — starts life as a satisfying assignment from Z3, and Z3 is reasoning about an *encoding* of the rulebase, not the rulebase. The encoding deliberately approximates in places (money loses its currency, decimals lose their scale), and those approximations are chosen to keep the static verifier's proofs sound — which has the side effect of making raw solver answers *less* reliable, not more.

So the solver proposes and the kernel disposes. Every value is handed back to `duly_kernel.api.adjudicate` — the same code that produced the original receipt — and the answer is reported only if the kernel agrees. Extremal answers get a second check: the kernel must also *refuse* one step beyond. If solver and kernel disagree, `python -m duly_whatif` raises with both artifacts instead of returning an answer, and a deliberately broken encoding is committed as a test to prove that guard fires.

Two things it still cannot promise, both stated wherever an answer appears rather than only in the spec. "No value works" (UNSAT) is not pointwise-verifiable — there is no point to hand the kernel — so it rests on the encoding alone, except over finite domains where every member is checked. And extremality means the kernel confirmed this value and refused the next step, not that nothing further out could work. See [spec/whatif.md](../spec/whatif.md).

## Someone hands me a receipt. How do I check it, without trusting them?

Open it in the receipt viewer (<http://localhost:8788/receipt>, or `/api/receipts/inspect`) and it runs three checks before it shows you anything. Their independence is the answer to your question, because each one closes a different hole.

**Its own hash.** Recompute SHA-256 over the receipt's canonical body and compare it to the `receiptSha256` it carries. This needs nothing but the receipt — not our repository, not our facts, not our packs — so it works on a receipt produced by somebody else's deployment years ago. It proves exactly one thing: nobody edited this document after it was sealed.

**Its facts.** Every fact pinned in `inputFacts` is present and hashes to the content hash in its own id. A receipt pins facts by hash rather than by value, so it cannot supply them itself; if you were handed the receipt alone, this check reports *not checked* rather than passing vacuously.

**Replay.** Re-run the kernel over those facts, that pack version, and the receipt's own asOf pair, and compare byte-for-byte. This is `python -m duly_assurance verify` narrowed to a single receipt.

The reason it is three checks and not one is the forgery that beats the first two. Edit a verdict, then recompute the hash: the document is now internally consistent, its facts are genuine and correctly hashed, and the report renders in fluent sentences with real statutory citations. Hash passes. Facts pass. Replay fails, because the rules do not produce that answer. **Sealed, internally consistent, and true are three different properties**, and a system that checks only the first has confused tamper-evidence for correctness.

Two honest limits. The hash is an integrity claim, not an authenticity one — it proves the document is unaltered, not who produced it; signing is an open question, the same one the [extraction run envelope](../spec/grounded-facts.md#resolved-questions) leaves open. And replay tells you the receipt is a faithful record of what this rulebase concludes, which is not a claim that the rulebase is right about the law. For that, read the citations — they are in the report, one per rule. See [demo tour §12](demo_tour.md#12-the-receipt-viewer).

## Who decides how the answer is worded?

The same person who wrote the rule. A pack declares both the question it can answer and the phrasing of the answer — verdict, supporting clause, and tone, with cases for the value concluded and the evidence behind it. Nothing about a verdict lives in the UI, so an organization replacing the rule packs replaces the wording with them and never forks the demo to do it. The wording is versioned with the rules but deliberately *outside* the receipt hash: what a decision **is** is `decision.value`, which is hashed and replays forever; how it **reads** has to stay improvable. See [Decision phrasing](../spec/rule-ir.md#decision-phrasing).

## We want to put duly inside a scheduler. How do we stop the scheduler learning the rules?

You make it structurally unable to. The scheduler never sees a rule — it sees a verdict and a receipt id. It asks `adjudicate()` for every candidate date and gets back a table of days that were permitted; that table is the constraint it hands the solver. The rule stays in the pack, in one copy, cited and effective-dated.

The failure this avoids is neither hypothetical nor exotic: an optimizer that encodes "wait three business days after consummation" beside the TILA pack has two sources of truth for one legal requirement, and the first person to discover that the § 1026.2(a)(6) rescission calendar counts *Saturdays* will fix only one of them.

The claim is testable, which is the part that matters. [examples/closing-scheduler](../examples/closing-scheduler/README.md) perturbs the TILA pack from three business days to five, edits no line of the scheduler, and requires the funding date to move; and it opens the wire desk on Saturdays and requires the compliance floor *not* to. A scheduler with its own copy of the rule fails the first test; one that confused staffing with law fails the second. Each date in the plan also cites the receipt ids that constrained it, so the boundary is legible in the output and not only in the tests.

## How much code do I actually have to write to use this?

About a hundred lines, and [examples/minimal-integration](../examples/minimal-integration/) is those lines. Five steps: load your ontology, admit your facts against it, load your rule pack, adjudicate at an as-of pair you choose, verify the receipt you got back. Everything else in this repository is either a teaching artifact (the six packs, the starters, the corpus) or a tool you run rather than code you write (the studio, the verifier, impact analysis).

Two things about that example are worth more than its size. It brings its own ontology and its own pack, in its own directory, so it demonstrates the bring-your-own path rather than borrowing duly's insurance vocabulary. And it is checked by building a wheel, installing it into a clean virtualenv, and running the example with duly's source tree *absent* — because a test that passes inside this repository cannot tell a toolkit from a repository with a library-shaped subdirectory. Writing it is also what surfaced the rough edges M5 is fixing; they are listed in the plan's appendix rather than smoothed over.

## What does installing this drag into my service?

PyYAML. That is the whole list — `pip install duly` brings two packages, duly and PyYAML, because a rule pack is YAML and the document→receipt path needs a parser and nothing else. Every surface built on that path is an optional extra you opt into by name: `duly[demo]` for the two HTTP apps (the demonstration workspace and the review queue's API — one dependency, FastAPI and uvicorn, serving both), `duly[report]` for the PDF audit report, `duly[prove]` for the SMT solver behind pack verification and what-if, `duly[extraction]` for the Docling stack. The OR-Tools scheduler example declares its own solver inside the example rather than as an extra here, because an example's dependency should leave when the example does.

This was not always true, and the correction is worth more than the number. Until M5, a kernel-only install pulled a web framework, an ASGI server and a PDF library, because the demo and the audit report were declared as dependencies *of* the toolkit rather than as surfaces built *on* it. "The audit toolkit installed a web server" is a bad first line in a security review, and the reason it is a bad line is specific: every package that can execute in the process that seals a receipt is inside the boundary that receipt's guarantees are drawn against. So the floor is asserted rather than promised — [`check_wheel.sh`](../examples/minimal-integration/check_wheel.sh) installs a built wheel into a clean virtualenv and fails if a third package appears, in the same run that proves the example works with duly's source tree absent.

One honest gap remains, documented in [SECURITY.md](../SECURITY.md): the review queue validates a human correction with `jsonschema`, which no extra declares, so `ReviewQueue.resolve()` on a bare install raises rather than enforcing the rule it exists to enforce. Install `jsonschema` alongside duly until that is resolved.

## Is this a product I can deploy?

Not yet — it is a pre-alpha specification with a working reference implementation. What runs today: six rule packs across two domains, an interactive demo of the full extract → decide → abstain → correct loop, and a 351-case corpus that replays byte-for-byte on every push. Breaking changes are expected until v1.0. The most useful thing an early adopter can do is try it against a real document workflow and report where the contract fits and where it fights — the [PRD's open questions](guiding-prd.md#open-questions) name exactly what only an adopter can answer, and no amount of reading the spec substitutes for that report.
