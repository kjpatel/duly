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

## Is this a product I can deploy?

Not yet — it is a pre-alpha specification with a working reference implementation. What runs today: six rule packs across two domains, an interactive demo of the full extract → decide → abstain → correct loop, and a 351-case corpus that replays byte-for-byte on every push. Breaking changes are expected until v1.0. The most useful thing an early adopter can do is pressure-test the [contract's open questions](../spec/grounded-facts.md#open-questions) against a real workflow.
