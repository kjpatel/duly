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
| `assurance/` | Golden-corpus generator, replay verifier, rule-change impact analysis, static pack verifier (`prove`, optional z3) |
| `conformance/` | Ontology conformance gate: pure-Python LinkML-subset validator, registry, CLI (`python -m duly_conformance`) |
| `ontologies/` | Versioned, immutable LinkML ontology artifacts (`<name>/<version>.yaml`) the facts' `schemaRef`s pin — read `ontologies/README.md` before touching |
| `rulepacks/` | Six packs (insurance + mortgage closing), each `pack.yaml` + `expected.yaml` (+ `fixtures/`) |
| `starters/` | Synthetic documents, renditions, span-verified facts, one demo scenario per vertical |
| `golden/` | 351 committed cases + receipts — the replay/impact baseline |
| `whatif/` | Backward queries: free one input, solve the pack for it, verify every answer by re-running the kernel (`python -m duly_whatif`, optional z3) |
| `dmn/` | DMN 1.3+ decision-table compiler: S-FEEL cell compiler, hit-policy mapping, deterministic pack emitter, CLI (`python -m duly_dmn`) — [dmn/README.md](dmn/README.md) |
| `examples/` | Reference wiring: duly consumed from *outside*, by software that is not duly. First resident is the CP-SAT closing scheduler — [examples/README.md](examples/README.md) |
| `demo/` | FastAPI + vanilla-JS decision workspace |

## Verify

```bash
uv sync                              # add --extra extraction for live Docling (tests are marker-gated without it)
uv run pytest kernel/tests demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
uv run python -m duly_assurance verify    # all 351 golden receipts, byte-for-byte
uv run python -m duly_assurance impact    # what your change flips vs the committed baseline
uv run spec/validate.py                   # spec examples: schemas + hashes
uv run python3 starters/tools/check_facts.py   # starter facts: schema, hashes, quote spans
uv run python -m duly_conformance check starters golden/cases rulepacks spec/examples   # every committed fact vs ontologies/
uv run --with z3-solver python -m duly_assurance prove rulepacks/*/pack.yaml   # disjointness + coverage (optional dep)
uv run uvicorn demo.app:app --port 8788   # the demo
```

The three marker-gated suites are **skipped** by the command above — they need optional dependencies the kernel deliberately does not require. They run in their own workflow ([.github/workflows/optional-deps.yml](.github/workflows/optional-deps.yml)); run them locally with:

```bash
uv run --with linkml --with pyshacl pytest conformance/tests -q -m linkml   # ontologies are real LinkML
uv sync --extra prove  && uv run pytest assurance/tests  -q -m z3           # verifier encoding is sound
uv sync --extra prove  && uv run pytest whatif/tests     -q -m z3           # what-if answers survive kernel verification
uv sync --extra scheduling && uv run pytest examples/closing-scheduler -q -m ortools   # the closing scheduler example
uv sync --extra extraction && uv run pytest extraction/tests -q -m docling  # live adapter (heavy: pulls torch)
```

Run the full suite, replay, and spec validation before any commit. A change that flips golden decisions is not necessarily wrong — but the flip must be intentional, explained, and visible (`impact` reports it; CI comments it on PRs touching `rulepacks/`).

## Invariants (breaking these breaks the product)

- **Determinism everywhere.** No wall clock in library code — timestamps are caller-supplied. No unseeded randomness (tests use `random.Random(seed)`). Same inputs must produce byte-identical outputs, forever.
- **Content addressing.** Facts, receipts, and envelopes are hashed: SHA-256 over canonical JSON (`sort_keys=True`, separators `(",", ":")`, `ensure_ascii=False`) excluding `id` and the hash field. Never mutate a stored document — a correction is a *new* fact that `supersedes` the old one; an export format *wraps*, never edits (adding a key in place changes every hash).
- **Golden replay.** The 351 receipts in `golden/` replay byte-for-byte on every push. Regenerating the corpus is a deliberate baseline change, documented in the commit; `review-*` cases are preserved by the generator (no seed can recreate them).
- **Honest labeling.** Every rule cites its authority or carries `TODO(verify)` naming what wasn't confirmed. Invented history is marked `DEMO-SYNTHETIC`. Scripted demo values (e.g. a below-floor confidence) say so in a comment. When the IR can't express something, document the boundary (see the `MODELING BOUNDARY` header in `rulepacks/tila-rescission-us-federal/pack.yaml`) — a documented limitation is a contribution; a silent approximation is a defect.

## Gotchas that have actually bitten

- **CP-SAT is nondeterministic by default and lies about why.** It parallelises and randomises, so an optimum can differ between machines: set `num_workers = 1` and `random_seed = 0`, and make the objective's optimum *unique* (a tie lets search order pick the answer). Set `num_workers` **only** — it and the legacy `num_search_workers` are mutually exclusive, and setting both returns `MODEL_INVALID`, which reads exactly like an infeasible problem until you print the status. Treat `MODEL_INVALID`/`UNKNOWN` as a raise, never as "no solution".
- **`examples/` is not in the main pytest paths, on purpose.** Example suites need optional solvers, so they live behind markers and run in [.github/workflows/optional-deps.yml](.github/workflows/optional-deps.yml). Consequence before you edit a pack: `rulepacks/**` is deliberately absent from that workflow's paths filter, so a pack change that moves the scheduler's committed plan surfaces on the merge to main rather than on your PR. The fix is a date update in `test_the_plan_is_the_committed_demo_output`, in the same spirit as a golden regeneration.
- **A what-if answer is a proposal until the kernel has run.** `whatif/` reuses `prove`'s SMT encoding unmodified but stands in the *opposite* relation to it: `prove` lives on UNSAT, where widening the input space is safe; what-if lives on SAT, where widening is exactly what makes an answer unreliable. So every value it returns is re-adjudicated through `duly_kernel.api.adjudicate`, and extremals are boundary-verified. Never add a return path that skips that — a spurious SAT must become a `SolverKernelContradiction`, not an answer. And never write a second encoder: `test_the_encoding_is_the_one_prove_uses` asserts class identity so divergence has to be deliberate.
- **`prove` only ever sees packs the kernel already blessed.** `validate_pack` refuses any same-priority pair concluding one attribute unless it can prove disjointness syntactically or the author wrote an `overrides` — so a pack with an *unproven* same-priority overlap cannot load, and `python -m duly_assurance prove` cannot meet one in a committed pack. Its non-zero exit is a **differential check between two proof systems**, not a routine gate: it firing would mean Z3 refuted a proof `_equality_guards` accepted. Don't write a test that reaches it through `load_pack` — build the pack dict and call `analyze_pack` directly.
- **An `overrides` can mean two different things, and only a solver tells them apart.** `PKG-NOTE-31 overrides PKG-NOTE-30` is an authored legal exception over rules that genuinely overlap (a registered eNote *is* a promissory note); TILA's manufactured priority gap is a workaround for a proof the validator cannot perform. Both look identical in the pack. Run `prove` before adding either — if the pair comes back PROVED-DISJOINT you were working around the validator, and the comment saying so belongs on the rule.
- **Only `attribute` bindings can prove disjointness — `derived` ones cannot.** Narrower than the boolean-guard gotcha below and less visible: `_equality_guards` inspects only `when` items whose variable resolves to an *attribute* binding, so `category == "ZeroTolerance"` on a `derived` binding proves nothing however string-equal it looks. Two same-priority rules separated only by a derived-value guard need an explicit `overrides`.
- **Test filenames collide across suites.** Test dirs have no `__init__.py`, so pytest imports by basename: `dmn/tests/test_cli.py` broke collection against `kernel/tests/test_cli.py`. Before adding a suite, run `find . -name "test_*.py" | sed 's#.*/##' | sort | uniq -d`.
- **Boolean guards don't prove disjointness.** The pack validator's same-priority check accepts only *quoted-string* equality guards (`state == "US-NY"`) as a disjointness proof. Two rules split by `x == true` / `x == false` need an explicit `overrides`, even though they look disjoint.
- **`expected.yaml` is not the corpus.** Pack outcome declarations run in CI, but impact analysis runs *over `golden/`*. A pack without a generator template in `assurance/duly_assurance/generate.py` gets "0 decisions flip" for every edit. Both are required.
- **Non-boolean decisions need *pack* phrasing.** A decision that isn't boolean renders as a bare `attribute = value` unless its `decisions[]` entry carries a `phrasing:` block ([spec/rule-ir.md](spec/rule-ir.md), "Decision phrasing"). The fix is in the pack, never in `demo/app.py`; `validate_pack` rejects a malformed block, an unknown placeholder, or a tone outside `pos/neg/warn/""` where the pack loads. Booleans still get a Yes/No fallback. Phrasing is presentation and must stay out of every hashed body — putting it in a receipt would change every hash.
- **Rule ids are permanent, and now conventional.** Ids sit in `rulesFired` on every receipt that cited them, so an id encoding a day count, a year, or a statute section is wrong forever once the law moves — `NY-NR-45` is in 76 golden receipts. New ids are `<PREFIX>-<TOPIC>[-QUALIFIER][-NN]` with `PREFIX = pack.idPrefix`; `validate_pack` refuses digits outside the two-digit tail, a tail echoing the rule's own numbers, and an id outside the pack's family. The 46 pre-convention ids are exempt by an explicit list in [kernel/duly_kernel/rule_ids.py](kernel/duly_kernel/rule_ids.py) — 17 of them would fail today. Checks run only for packs declaring `idPrefix`; a kernel test requires every committed pack to declare one.
- **Scripted confidences need the stub pin.** If a scenario depends on an exact confidence value, set `"demoExtractor": "stub"` in its `scenario.json` — Docling emits its own measured confidence and silently overrides the scripted one. No test warns about this at authoring time.
- **One entity per `entityType` per case; one live fact per attribute.** Per-document decisions mean one case per document, or the document type as an attribute of a single entity. Two live facts on one attribute is a conflict (lone human outranks; anything else abstains).
- **`engine.backend` is inside the receipt hash.** A second evaluation backend cannot produce byte-identical receipts by construction; cross-backend equivalence is an open M5 spec decision. Don't design around an assumption either way.
- **Calendars are pack data and coverage is a wall.** `add_business_days` walks only the pack's `calendars:` block; a walk touching any day outside the calendar's `coverage` window raises rather than guessing. The TILA calendar reconciles by test with the corpus generator's 6103(a) derivation — edit either and the suite tells you.
- **Kernel abstention policy is pack-versioned.** Adding `abstentionPolicy` to a pack changes receipts (bump the pack version, expect corpus churn for that pack). Packs without one must stay byte-identical — there is a pinned-hash test proving the pre-policy kernel's output.
- **`schemaRef` is inside the fact hash — renaming an ontology is corpus churn.** A fact's `schemaRef` sits in its content-hashed bytes, so re-pointing facts at a different ontology name changes fact hashes, receipt `inputFacts`, and therefore every affected golden receipt. The M4 consolidation (five `duly-starter-*` mortgage names → `duly-mortgage-closing`) touched 555 golden files while flipping 0 of 351 decisions; do it that way — targets + fixtures + generator templates updated together, `impact` run before accepting regeneration, `notice-*`/`review-*` proven byte-untouched. This is also why `duly-starter-notice` keeps its awkward name forever: `review-0001` is preserved-forever and pins it.

## Definition of done

A feature is not shipped when the code merges. It is shipped when it is **documented, discoverable, demoable, and reconciled** — all four in the PR that introduces it, not in follow-ups.

- **Documented** — spec/README coverage in house style, including the honest "deliberately does not do" boundaries.
- **Discoverable** — audit the newcomer entry points and update the ones that should now lead here: README components table and roadmap bullet, `docs/concepts.md` glossary, `docs/faq.md` if a skeptic would ask, this file's gotchas if agents will trip on it, and the component README a practitioner actually reads (`rulepacks/README.md` for anything touching pack authoring).
- **Demoable** — something runnable that shows the benefit, executed before you claim it works.
- **Reconciled** — [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) is the system mental model, and a mental model describing a shipped capability as "a possible extension" is worse than one omitting it. Check five places: the *how the architecture can grow* table, the *adjacent patterns* table, the *artifacts that carry meaning* table, the reading/code map, and — the one that carries real content — **whether the work sharpened a claim the doc already makes**. The DMN track turned "a receipt identifies its pack by name and version" into *pack identity is inside the hashed body, so two packs are two identities*; the verifier track located the unexamined middle between "reproducible" and "true" and named it *internally consistent*. Those paragraphs were each worth more than the factual corrections around them.

## Conventions

- **Branches/PRs**: never commit to `main`; branch, PR, squash-merge. CI runs the full test matrix plus rule-impact.
- **Commits**: imperative subject; body says *why*, includes test counts and (for rule/corpus changes) the impact result.
- **New packages** register in `pyproject.toml` `[tool.hatch.build.targets.wheel] packages`. Heavy optional deps go in an extras group with marker-gated tests (see `docling`).
- **Test helpers** are `<pkg>test_helpers.py` modules, not `conftest.py` (test dirs have no `__init__.py`; identical filenames across suites collide).
- **Demo discipline**: verdict wording is **pack data**, rendered server-side by `_determination()` from the decision's `phrasing:` block — never in JS, and never re-hardcoded per pack in `demo/app.py`; no `innerHTML` with server data anywhere; status pill modes are styled per state; the demo must degrade honestly when the kernel or store is unavailable (fixture mode refuses questions it can't answer rather than answering the wrong one).
- **Auto-discovery over registration** wherever possible: `rulepacks/*/expected.yaml`, `starters/*/scenario.json`, and per-template corpus generation are all glob-driven. Prefer extending a registry of data to adding dispatch code.

## Documentation map

- [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) — the platform-engineer mental model: architecture, trust boundaries, guarantees, and extension paths
- [CHANGELOG.md](CHANGELOG.md) — what each release turned out to mean; read it before assuming why something is the way it is
- [docs/guiding-prd.md](docs/guiding-prd.md) — who this is for, the product principles, what is out of scope, and how success is measured; read it before proposing work that widens the surface
- [docs/concepts.md](docs/concepts.md) — the vocabulary this repo uses precisely; read it before assuming a term means what it usually means
- [docs/faq.md](docs/faq.md) — the objections a skeptical reader raises first, answered in one place
- [rulepacks/README.md](rulepacks/README.md) — authoring a pack end to end, including what is *not* auto-wired
- [spec/pack-verification.md](spec/pack-verification.md) — the static verifier's fragment, its per-operator encoding, and what a green `prove` run does and does not license
- [spec/whatif.md](spec/whatif.md) — backward queries, the solver-proposes/kernel-disposes contract, and why UNSAT is the weaker verdict
- [examples/README.md](examples/README.md) — reference wiring for adopters: duly consumed from outside, starting with the OR-Tools closing scheduler
- [ontologies/README.md](ontologies/README.md) / [spec/ontology-conformance.md](spec/ontology-conformance.md) — the ontology registry, the crosswalk rules (verify or omit), and the conformance gate's exact subset
- [starters/README.md](starters/README.md) — starter layout and shared tooling
- [golden/README.md](golden/README.md) — corpus contract, case-id series, regeneration rules
- [spec/grounded-facts.md](spec/grounded-facts.md) / [spec/rule-ir.md](spec/rule-ir.md) — the contract, with open questions at the bottom (check them before "fixing" something deliberate)
- [review/README.md](review/README.md), [calibration/README.md](calibration/README.md) — component contracts and their honest caveats
