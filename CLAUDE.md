# Working on duly

duly is a neurosymbolic document-adjudication toolkit: extractors *propose* grounded facts, a deterministic kernel applies versioned effective-dated rules and emits a content-addressed receipt. The product is not the answer — it is the answer plus a byte-replayable audit chain. Every convention below serves that.

New to the codebase? README for the argument, [docs/demo_tour.md](docs/demo_tour.md) for the walkthrough, [rulepacks/README.md](rulepacks/README.md) before touching any rule pack.

## Layout

| Directory | What lives there |
|---|---|
| `spec/` | The contract: grounded-fact + receipt specs (decision/why/rejected format), JSON Schemas, committed examples, `validate.py` |
| `kernel/` | Reference interpreter: IR validation, evaluation, defeat semantics, receipt + audit-report emission |
| `store/` | Append-only bitemporal fact store (SQLite, Postgres-portable) |
| `extraction/` | Adapter protocol, Docling adapter, scripted stub, run envelopes (verify/ingest/revoke) |
| `calibration/` | Temperature/Platt/conformal math — deliberately unfitted; labels come from review |
| `review/` | Review queue: abstention routing, human corrections, golden-case export, calibration pairs |
| `assurance/` | Golden-corpus generator, replay verifier, rule-change impact analysis |
| `conformance/` | Ontology conformance gate: pure-Python LinkML-subset validator, registry, CLI (`python -m duly_conformance`) |
| `ontologies/` | Versioned, immutable LinkML ontology artifacts (`<name>/<version>.yaml`) the facts' `schemaRef`s pin — read `ontologies/README.md` before touching |
| `rulepacks/` | Six packs (insurance + mortgage closing), each `pack.yaml` + `expected.yaml` (+ `fixtures/`) |
| `starters/` | Synthetic documents, renditions, span-verified facts, one demo scenario per vertical |
| `golden/` | 351 committed cases + receipts — the replay/impact baseline |
| `demo/` | FastAPI + vanilla-JS decision workspace |

## Verify

```bash
uv sync                              # add --extra extraction for live Docling (tests are marker-gated without it)
uv run pytest kernel/tests demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests conformance/tests -q
uv run python -m duly_assurance verify    # all 351 golden receipts, byte-for-byte
uv run python -m duly_assurance impact    # what your change flips vs the committed baseline
uv run spec/validate.py                   # spec examples: schemas + hashes
uv run python3 starters/tools/check_facts.py   # starter facts: schema, hashes, quote spans
uv run python -m duly_conformance check starters golden/cases rulepacks spec/examples   # every committed fact vs ontologies/
uv run uvicorn demo.app:app --port 8788   # the demo
```

Run the full suite, replay, and spec validation before any commit. A change that flips golden decisions is not necessarily wrong — but the flip must be intentional, explained, and visible (`impact` reports it; CI comments it on PRs touching `rulepacks/`).

## Invariants (breaking these breaks the product)

- **Determinism everywhere.** No wall clock in library code — timestamps are caller-supplied. No unseeded randomness (tests use `random.Random(seed)`). Same inputs must produce byte-identical outputs, forever.
- **Content addressing.** Facts, receipts, and envelopes are hashed: SHA-256 over canonical JSON (`sort_keys=True`, separators `(",", ":")`, `ensure_ascii=False`) excluding `id` and the hash field. Never mutate a stored document — a correction is a *new* fact that `supersedes` the old one; an export format *wraps*, never edits (adding a key in place changes every hash).
- **Golden replay.** The 351 receipts in `golden/` replay byte-for-byte on every push. Regenerating the corpus is a deliberate baseline change, documented in the commit; `review-*` cases are preserved by the generator (no seed can recreate them).
- **Honest labeling.** Every rule cites its authority or carries `TODO(verify)` naming what wasn't confirmed. Invented history is marked `DEMO-SYNTHETIC`. Scripted demo values (e.g. a below-floor confidence) say so in a comment. When the IR can't express something, document the boundary (see the `MODELING BOUNDARY` header in `rulepacks/tila-rescission-us-federal/pack.yaml`) — a documented limitation is a contribution; a silent approximation is a defect.

## Gotchas that have actually bitten

- **Boolean guards don't prove disjointness.** The pack validator's same-priority check accepts only *quoted-string* equality guards (`state == "US-NY"`) as a disjointness proof. Two rules split by `x == true` / `x == false` need an explicit `overrides`, even though they look disjoint.
- **`expected.yaml` is not the corpus.** Pack outcome declarations run in CI, but impact analysis runs *over `golden/`*. A pack without a generator template in `assurance/duly_assurance/generate.py` gets "0 decisions flip" for every edit. Both are required.
- **Non-boolean decisions need demo phrasing.** A new decision attribute renders through `_determination()` in `demo/app.py` or leaks a raw CURIE (a demo test catches this — in `demo/tests`, where pack authors don't look). Booleans get a Yes/No fallback.
- **Scripted confidences need the stub pin.** If a scenario depends on an exact confidence value, set `"demoExtractor": "stub"` in its `scenario.json` — Docling emits its own measured confidence and silently overrides the scripted one. No test warns about this at authoring time.
- **One entity per `entityType` per case; one live fact per attribute.** Per-document decisions mean one case per document, or the document type as an attribute of a single entity. Two live facts on one attribute is a conflict (lone human outranks; anything else abstains).
- **`engine.backend` is inside the receipt hash.** A second evaluation backend cannot produce byte-identical receipts by construction; cross-backend equivalence is an open M5 spec decision. Don't design around an assumption either way.
- **Calendars are pack data and coverage is a wall.** `add_business_days` walks only the pack's `calendars:` block; a walk touching any day outside the calendar's `coverage` window raises rather than guessing. The TILA calendar reconciles by test with the corpus generator's 6103(a) derivation — edit either and the suite tells you.
- **Kernel abstention policy is pack-versioned.** Adding `abstentionPolicy` to a pack changes receipts (bump the pack version, expect corpus churn for that pack). Packs without one must stay byte-identical — there is a pinned-hash test proving the pre-policy kernel's output.
- **`schemaRef` is inside the fact hash — renaming an ontology is corpus churn.** A fact's `schemaRef` sits in its content-hashed bytes, so re-pointing facts at a different ontology name changes fact hashes, receipt `inputFacts`, and therefore every affected golden receipt. The M4 consolidation (five `duly-starter-*` mortgage names → `duly-mortgage-closing`) touched 555 golden files while flipping 0 of 351 decisions; do it that way — targets + fixtures + generator templates updated together, `impact` run before accepting regeneration, `notice-*`/`review-*` proven byte-untouched. This is also why `duly-starter-notice` keeps its awkward name forever: `review-0001` is preserved-forever and pins it.

## Conventions

- **Branches/PRs**: never commit to `main`; branch, PR, squash-merge. CI runs the full test matrix plus rule-impact.
- **Commits**: imperative subject; body says *why*, includes test counts and (for rule/corpus changes) the impact result.
- **New packages** register in `pyproject.toml` `[tool.hatch.build.targets.wheel] packages`. Heavy optional deps go in an extras group with marker-gated tests (see `docling`).
- **Test helpers** are `<pkg>test_helpers.py` modules, not `conftest.py` (test dirs have no `__init__.py`; identical filenames across suites collide).
- **Demo discipline**: verdict wording lives server-side in `_determination()` — never in JS; no `innerHTML` with server data anywhere; status pill modes are styled per state; the demo must degrade honestly when the kernel or store is unavailable (fixture mode refuses questions it can't answer rather than answering the wrong one).
- **Auto-discovery over registration** wherever possible: `rulepacks/*/expected.yaml`, `starters/*/scenario.json`, and per-template corpus generation are all glob-driven. Prefer extending a registry of data to adding dispatch code.

## Documentation map

- [rulepacks/README.md](rulepacks/README.md) — authoring a pack end to end, including what is *not* auto-wired
- [ontologies/README.md](ontologies/README.md) / [spec/ontology-conformance.md](spec/ontology-conformance.md) — the ontology registry, the crosswalk rules (verify or omit), and the conformance gate's exact subset
- [starters/README.md](starters/README.md) — starter layout and shared tooling
- [golden/README.md](golden/README.md) — corpus contract, case-id series, regeneration rules
- [spec/grounded-facts.md](spec/grounded-facts.md) / [spec/rule-ir.md](spec/rule-ir.md) — the contract, with open questions at the bottom (check them before "fixing" something deliberate)
- [review/README.md](review/README.md), [calibration/README.md](calibration/README.md) — component contracts and their honest caveats
