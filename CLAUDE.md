# Working on duly

duly is a neurosymbolic document-adjudication toolkit: extractors *propose* grounded facts, a deterministic kernel applies versioned effective-dated rules and emits a content-addressed receipt. The product is not the answer — it is the answer plus a byte-replayable audit chain. Every convention below serves that.

New to the codebase? README for the argument, [docs/demo_tour.md](docs/demo_tour.md) for the walkthrough, [examples/rulepacks/README.md](examples/rulepacks/README.md) before touching any rule pack.

**Executing M5 work?** [docs/m5-plan.md](docs/m5-plan.md) is the execution plan: locked decisions, phase graph, per-phase tasks with acceptance criteria and landmines. Read your phase in full before touching anything; the decisions in its §1 are settled — do not re-litigate them in a PR.

## Layout

| Directory | What lives there |
|---|---|
| `core/` | What a duly document *is*: canonical form, content addressing, and the JSON Schemas — all shipped in the wheel, so two packages cannot disagree and no path reaches for the repo. Narrow charter, amended once and only once (`duly_core`) |
| `spec/` | The contract *argued*: grounded-fact + receipt specs (decision/why/rejected format), committed examples, canonical-form vectors, `validate.py`. The schemas themselves live in `core/` because they ship |
| `kernel/` | Reference interpreter: IR validation, evaluation, defeat semantics, receipt + audit-report emission |
| `store/` | Append-only bitemporal fact store (SQLite, Postgres-portable) |
| `extraction/` | Adapter protocol, Docling adapter, scripted stub, run envelopes (verify/ingest/revoke) |
| `calibration/` | Temperature/Platt/conformal math — deliberately unfitted; labels come from review |
| `review/` | Review queue: abstention routing, human corrections, golden-case export, calibration pairs |
| `assurance/` | Golden-corpus generator, replay verifier, rule-change impact analysis, static pack verifier (`prove`, optional z3) |
| `conformance/` | Ontology conformance gate: pure-Python LinkML-subset validator, registry, CLI (`python -m duly_conformance`) |
| `fixtures/` | The corpus **duly's own suites** run on: one invented domain, five cases, committed receipts, declared outcomes, a scenario, DMN inputs. Toolkit, so it survives `git rm -r examples/` — read [fixtures/README.md](fixtures/README.md) before adding to it |
| `whatif/` | Backward queries: free one input, solve the pack for it, verify every answer by re-running the kernel (`python -m duly_whatif`, optional z3) |
| `dmn/` | DMN 1.3+ decision-table compiler: S-FEEL cell compiler, hit-policy mapping, deterministic pack emitter, CLI (`python -m duly_dmn`) — [dmn/README.md](dmn/README.md) |
| `examples/` | **Everything an adopter deletes**, and the claim is that deleting it leaves a working toolkit. The teaching content: `rulepacks/` (six packs), `starters/` (synthetic documents + scenarios), `golden/` (351 committed cases + receipts, the replay/impact baseline), `ontologies/` (versioned immutable LinkML artifacts — read its README before touching), `dmn/` (the TRID decision-table example + refusals), `tests/` (the example content's own tests, run in CI while the content exists), plus the reference wiring: `minimal-integration` (the whole contract at its smallest, proved to run with the source tree absent) and `closing-scheduler` (CP-SAT) — [examples/README.md](examples/README.md) |
| `demo/` | FastAPI + vanilla-JS decision workspace (`app.py`), rule studio (`rules_api.py` + `static/rules.*`), evidence browser (`evidence_api.py` + `static/evidence.*`) and receipt viewer (`receipts_api.py` + `static/receipt.*`). Content directories come from `content.py` (`DULY_DEMO_CONTENT`, default `examples/`; the content-root contract is flat — `starters/`, `golden/`, `rulepacks/`, `ontologies/`, `dmn/` directly under the root) — never a per-module `REPO_ROOT` |

## Verify

```bash
uv sync                              # add --extra extraction for live Docling (tests are marker-gated without it)
uv run pytest core/tests kernel/tests demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
uv run pytest examples/tests -q           # the example content's own tests (deleted with examples/)
uv run python -m duly_assurance verify    # all 351 golden receipts, byte-for-byte
uv run python -m duly_assurance impact    # what your change flips vs the committed baseline
uv run spec/validate.py                   # spec examples: schemas + hashes
uv run python3 examples/starters/tools/check_facts.py   # starter facts: schema, hashes, quote spans
uv run python -m duly_conformance --ontologies examples/ontologies check examples/starters examples/golden/cases examples/rulepacks spec/examples   # every committed fact
uv run --with z3-solver python -m duly_assurance prove --ontologies examples/ontologies examples/rulepacks/*/pack.yaml   # disjointness + coverage (optional dep)
uv run uvicorn demo.app:app --port 8788   # the demo (/ decision workspace, /rules rule studio, /evidence evidence browser, /receipt receipt viewer)
```

Tests behind the four optional-dependency markers (`linkml`, `z3`, `ortools`, `docling` — six suites carry them) are **skipped** by the command above — they need optional dependencies the kernel deliberately does not require. They run in their own workflow ([.github/workflows/optional-deps.yml](.github/workflows/optional-deps.yml)); run them locally with:

```bash
uv run --with linkml --with pyshacl pytest examples/tests -q -m linkml      # teaching ontologies are real LinkML
uv sync --extra prove  && uv run pytest assurance/tests  -q -m z3           # verifier encoding is sound
uv sync --extra prove  && uv run pytest whatif/tests examples/tests -q -m z3   # what-if answers survive kernel verification
uv sync --extra prove  && uv run pytest demo/tests       -q -m z3           # the rule studio's equivalence panel
uv sync --extra scheduling && uv run pytest examples/closing-scheduler -q -m ortools   # the closing scheduler example
uv sync --extra extraction && uv run pytest extraction/tests -q -m docling  # live adapter (heavy: pulls torch)
```

Run the full suite, replay, and spec validation before any commit. A change that flips golden decisions is not necessarily wrong — but the flip must be intentional, explained, and visible (`impact` reports it; CI comments it on PRs touching `examples/rulepacks/`).

## Invariants (breaking these breaks the product)

- **Determinism everywhere.** No wall clock in library code — timestamps are caller-supplied. No unseeded randomness (tests use `random.Random(seed)`). Same inputs must produce byte-identical outputs, forever.
- **Content addressing.** Facts, receipts, and envelopes are hashed: SHA-256 over canonical JSON (`sort_keys=True`, separators `(",", ":")`, `ensure_ascii=False`) excluding `id` and the hash field. Never mutate a stored document — a correction is a *new* fact that `supersedes` the old one; an export format *wraps*, never edits (adding a key in place changes every hash).
- **Golden replay.** The 351 receipts in `golden/` replay byte-for-byte on every push. Regenerating the corpus is a deliberate baseline change, documented in the commit; `review-*` cases are preserved by the generator (no seed can recreate them).
- **Honest labeling.** Every rule cites its authority or carries `TODO(verify)` naming what wasn't confirmed. Invented history is marked `DEMO-SYNTHETIC`. Scripted demo values (e.g. a below-floor confidence) say so in a comment. When the IR can't express something, document the boundary (see the `MODELING BOUNDARY` header in `rulepacks/tila-rescission-us-federal/pack.yaml`) — a documented limitation is a contribution; a silent approximation is a defect.

## Gotchas that have actually bitten

The cross-cutting set lives here. The rest are **routed to where the work happens**, in files that load exactly when you touch that area — a gotcha in a file nothing auto-loads is a gotcha nobody reads:

- [demo/CLAUDE.md](demo/CLAUDE.md) — the four surfaces: studio re-emission, JSON fidelity, the evidence browser's projections and reload discipline, the receipt viewer's three checks, the review arc
- [examples/rulepacks/README.md](examples/rulepacks/README.md) — everything about authoring pack content: disjointness proofs, `overrides`, phrasing, rule ids, calendars, abstention policy, `expected.yaml`
- [assurance/CLAUDE.md](assurance/CLAUDE.md) — what a green `prove` run means, `impact`'s in-memory overrides
- [whatif/CLAUDE.md](whatif/CLAUDE.md) — solver proposes, kernel disposes
- [examples/CLAUDE.md](examples/CLAUDE.md) — CP-SAT determinism, the optional-deps paths filter. **Deleted by the deletion gate on purpose** — route there only what dies with `examples/`

- **Test filenames collide across suites.** Test dirs have no `__init__.py`, so pytest imports by basename: `dmn/tests/test_cli.py` broke collection against `kernel/tests/test_cli.py`. Before adding a suite, run `find . -name "test_*.py" | sed 's#.*/##' | sort | uniq -d`.

- **A test that would still pass with its subject deleted is not a test, and that is why `fixtures/` exists.** The toolkit's suites assert *toolkit* behaviour, so they run on [`fixtures/`](fixtures/README.md) — never on `golden/`, `rulepacks/` or `starters/`, which are example content M5 relocates under `examples/` for an adopter to delete. Delete the example content and a suite pointed at it does not fail: it stops being collected, or skips, or asserts over an empty glob, all of which read exactly like success. **The two loudest-looking forms are the quietest**, and `test_rules_api` had both: a `for path in glob(...)` loop whose body simply never ran, and a `@pytest.mark.parametrize` over a glob — parametrize is evaluated at *collection*, so an empty directory produced zero test cases and pytest reported only the count that remained. The fix in each is one line: assert the glob is non-empty before using it, and loop inside the test rather than parametrizing over the filesystem. Two consequences. Writing a toolkit test, reach for `fixtures/`; writing a test whose *subject* is the example content (that the six packs load, that their declared outcomes hold), leave it pointed there — it moves with them. And the rule reaches further than tests: `spec/decision-digest-vectors.json` was a **contract artifact** generated from `golden/` receipts, which is the same defect with a longer fuse.

- **Scripted confidences need the stub pin.** If a scenario depends on an exact confidence value, set `"demoExtractor": "stub"` in its `scenario.json` — Docling emits its own measured confidence and silently overrides the scripted one. No test warns about this at authoring time.

- **`ReviewQueue.resolve` refuses a `low_confidence` correction that supersedes nothing, and cannot fix it for you.** Resolving such an item is a ruling on the one fact it abstained over, so the correction must carry `supersedes` ([spec/compatibility.md](spec/compatibility.md) C6) — otherwise the below-floor fact stays live and every future receipt carries a `low_confidence` entry for an attribute the decision *used*, which contradicts the fact spec's own definition of `abstentions`. The obvious fix — have the queue stamp the field in from the entry — is unavailable and instructive: a correction arrives content-addressed, so writing into it changes its hash and its identity, and the queue would hand the store a document its author never sealed. It names the required fact id and refuses. Three carve-outs, all deliberate: `conflict` items are untouched (their entries name several facts), `FactStore.ingest` still takes an independent human fact that supersedes nothing (a value from a phone call is not a ruling on an extraction), and `duly_review.golden`'s converter stays permissive because it is handed items by callers it does not control.

- **One entity per `entityType` per case; one live fact per attribute.** Per-document decisions mean one case per document, or the document type as an attribute of a single entity. Two live facts on one attribute is a conflict (lone human outranks; anything else abstains).

- **Replay is scoped to a semantics version, and "the digest" is not the receipt hash.** Two things the freeze ([spec/compatibility.md](spec/compatibility.md)) made load-bearing. First: every replay path calls `duly_kernel.semantics.check_replayable` *before* re-adjudicating, and a receipt whose `engine.version` is not in `IMPLEMENTED` is refused rather than replayed. The failure that guard exists for is silent — a kernel implementing V2 replaying a V1 receipt and **passing**, on the subset of cases where the two semantics happen to agree — so never "fix" a refusal by widening `IMPLEMENTED`: an entry there is a claim that this kernel reproduces that version byte-for-byte, substantiated only by corpus cases at that version. Second: `decision_digest()` is a pure function over a receipt's *determinant* fields and is never stored in any document (the receipt schema is closed; a digest inside the body it digests is exactly the extension point C2 refuses). It excludes `caseId`, `rulePack.gitCommit`/`url`, `engine.kernel` and `engine.backend` — everything identifying the run rather than the adjudication — which is what makes it, and not byte equality, the definition of two evaluation backends agreeing. Changing the determinant set is a breaking change to a published contract, not a refactor; [`spec/decision-digest-vectors.json`](spec/decision-digest-vectors.json) and a corpus-aggregate digest both fail on it.

- **The whole `engine` block is inside the receipt hash, and `engine.version` is NOT a package version.** It is the version of the kernel's **decision semantics** (`receipt.SEMANTICS_VERSION`), deliberately decoupled from `duly_kernel.__version__` and the distribution version — all three read `0.0.1` today by coincidence. **Never bump `SEMANTICS_VERSION` as part of a release**: it moves only when what the kernel *means* changes, and moving it invalidates every committed receipt. [kernel/tests/test_engine_identity.py](kernel/tests/test_engine_identity.py) fails on the re-coupling edit — exactly the tidying-up someone does while packaging — and [docs/release-process.md](docs/release-process.md) is the decision procedure for which of the four version scopes moves for a given change. Also: `engine.backend` being hashed means a second evaluation backend cannot produce byte-identical receipts by construction; cross-backend agreement is digest equality (C4), not byte equality.
- **A path relative to a *package* resolves everywhere; a path relative to the *repository* resolves here only.** This is one defect wearing several costumes, and Phase 1 found four instances: `duly_review` read the fact schema from `parents[2]/spec/schemas` (not in any wheel — its central operation raised for every adopter), `duly_conformance`'s CLI defaulted `--ontologies` to duly's own directory, `verify`/`generate` resolved case packs against their own install location, and the demo computed `REPO_ROOT` four times. Every test here passed each time, because in a checkout the assumption is true. The rules now: library code takes its roots from the caller (`load_repo_registry` is the shape), data a package needs at runtime ships *inside* that package (`duly_core/schemas`), and anything claiming to work outside the repo is proved by [`.github/scripts/wheel_smoke.py`](.github/scripts/wheel_smoke.py), which runs one real entry point per package from an installed wheel and refuses to run from the source tree. Three more turned up after those four were fixed — `duly_whatif`'s CLI, then `prove`'s, then `prove-equivalent`'s — so sweep rather than patch, and **sweep by behaviour rather than by filename or by file**: the fifth survived a `__main__.py` hunt because `prove`'s CLI is not in one, and the seventh survived the sweep that caught the fifth because it is the *second parser in a file whose first parser was already fixed* — a sweep that stops at the first clean hit per file misses every later one — and it carries the sharper form of the lesson: **a default that is right in this repository hides the wrong-path case *and every exception behind it*.** Deleting `--ontologies`'s repo-relative default immediately surfaced packs that cannot be encoded without a registry at all, a path that had been raising an uncaught `OutOfFragment` where a diagnostic belongs, unreachable for as long as the default kept quietly supplying duly's own ontologies.

- **`schemaRef` is inside the fact hash — renaming an ontology is corpus churn.** A fact's `schemaRef` sits in its content-hashed bytes, so re-pointing facts at a different ontology name changes fact hashes, receipt `inputFacts`, and therefore every affected golden receipt. The M4 consolidation (five `duly-starter-*` mortgage names → `duly-mortgage-closing`) touched 555 golden files while flipping 0 of 351 decisions; do it that way — targets + fixtures + generator templates updated together, `impact` run before accepting regeneration, `notice-*`/`review-*` proven byte-untouched. This is also why `duly-starter-notice` keeps its awkward name forever: `review-0001` is preserved-forever and pins it.

## Definition of done

A feature is not shipped when the code merges. It is shipped when it is **documented, discoverable, demoable, and reconciled** — all four in the PR that introduces it, not in follow-ups.

**Every PR ends with a documentation pass, and it is the last thing you do.** Not a follow-up PR, not a checkbox ticked while the code is still moving — a deliberate pass over the docs *after* the change is written and verified, in the same PR. Do not wait to be asked for it.

The ordering is the point. Documentation written before the work is finished describes what you intended; the interesting part is almost always what the work *taught*, and that is only knowable at the end. Several of this repo's most useful paragraphs exist because a doc pass came last and found the claim the code had just falsified — the architecture guide describing a review resolution as "usually" superseding after C6 made that state unrepresentable; `fixtures/README.md` never mentioning a case the corpus had grown two PRs earlier.

The pass is mechanical enough to run every time:

1. **Does any doc now say something false?** Grep for the thing you changed — the flag, the path, the count, the command — and read every hit. **Never `| head` a completeness sweep**: it turns a correct answer into a wrong one and leaves no trace. Pipe to `wc -l` first.
2. **Does the newcomer path still lead here?** README components table, `docs/concepts.md`, `docs/faq.md` if a skeptic would ask, and the component README a practitioner actually reads.
3. **Does [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) still model the system?** Check its five places, and especially whether the work *sharpened a claim it already makes* — that paragraph is usually worth more than the corrections around it.
4. **Does [CHANGELOG.md](CHANGELOG.md) say what this turned out to mean?** Not what you did; what it taught. A correction to a claim the project previously made is worth more space than the feature that found it.
5. **Do the executable docs still execute?** Run any command you touched, exactly as written.
6. **Did this work turn a gotcha into a check?** A gotcha exists because nothing catches the defect. When a validator, a test, or a helper starts catching it, collapse the bullet to a line naming the check — the prose that remains should carry only what the check cannot: the *why*. An executable check beats prose, including this file's.

- **Documented** — spec/README coverage in house style, including the honest "deliberately does not do" boundaries.
- **Discoverable** — audit the newcomer entry points and update the ones that should now lead here: README components table and roadmap bullet, `docs/concepts.md` glossary, `docs/faq.md` if a skeptic would ask, this file's gotchas if agents will trip on it, and the component README a practitioner actually reads (`examples/rulepacks/README.md` for anything touching pack authoring).
- **Demoable** — something runnable that shows the benefit, executed before you claim it works.
- **Reconciled** — [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) is the system mental model, and a mental model describing a shipped capability as "a possible extension" is worse than one omitting it. Check five places: the *how the architecture can grow* table, the *adjacent patterns* table, the *artifacts that carry meaning* table, the reading/code map, and — the one that carries real content — **whether the work sharpened a claim the doc already makes**. The DMN track turned "a receipt identifies its pack by name and version" into *pack identity is inside the hashed body, so two packs are two identities*; the verifier track located the unexamined middle between "reproducible" and "true" and named it *internally consistent*. Those paragraphs were each worth more than the factual corrections around them.

## Conventions

- **Branches/PRs**: never commit to `main`; branch, PR, squash-merge. CI runs the full test matrix plus rule-impact.
- **Commits**: imperative subject; body says *why*, includes test counts and (for rule/corpus changes) the impact result.
- **New packages** register in `pyproject.toml` `[tool.hatch.build.targets.wheel] packages`. Heavy optional deps go in an extras group with marker-gated tests (see `docling`).
- **Test helpers** are `<pkg>test_helpers.py` modules, not `conftest.py` (test dirs have no `__init__.py`; identical filenames across suites collide).
- **Demo discipline**: verdict wording is **pack data**, rendered server-side by `_determination()` from the decision's `phrasing:` block — never in JS, and never re-hardcoded per pack in `demo/app.py`; no `innerHTML` with server data anywhere; status pill modes are styled per state; the demo must degrade honestly when the kernel or store is unavailable (fixture mode refuses questions it can't answer rather than answering the wrong one).
- **One shape per job, across all four pages.** Navigation is text with a rule under the current item — the header nav *and* the in-pane view switchers (`.tabs`/`.tab` in `style.css`, shared, not copied per page). The pill shape (`border-radius: 999px`) is reserved for labels that state a fact and cannot be clicked: status, counts, hit policy, priority, Computed/Fixture. There are no clickable pills; adding one makes it the only one. A new page's orientation strip is a `data-guide` key in [demo/static/guide.js](demo/static/guide.js), never inline copy — `demo/tests/test_guide.py` fails a page without a guide and a guide without a page. Watch for `display` on an element that also ships `hidden`: an author declaration beats the UA's `[hidden] { display: none }`, which is how the guide strip's dismiss button silently stopped working.
- **Auto-discovery over registration** wherever possible: `rulepacks/*/expected.yaml`, `starters/*/scenario.json`, and per-template corpus generation are all glob-driven. Prefer extending a registry of data to adding dispatch code.

## Documentation map

- [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md) — the platform-engineer mental model: architecture, trust boundaries, guarantees, and extension paths
- [docs/release-process.md](docs/release-process.md) — which of the four version scopes moves for a given change, what counts as breaking per contract, and the release checklist; read it **before** bumping any version or tagging anything
- [CHANGELOG.md](CHANGELOG.md) — what each release turned out to mean; read it before assuming why something is the way it is
- [docs/guiding-prd.md](docs/guiding-prd.md) — who this is for, the product principles, what is out of scope, and how success is measured; read it before proposing work that widens the surface
- [docs/concepts.md](docs/concepts.md) — the vocabulary this repo uses precisely; read it before assuming a term means what it usually means
- [docs/follow-one-fact.md](docs/follow-one-fact.md) — one committed fact traced byte by byte from PDF text to receipt to human correction; the fastest way to see the actual shapes rather than their descriptions
- [docs/faq.md](docs/faq.md) — the objections a skeptical reader raises first, answered in one place
- [examples/rulepacks/README.md](examples/rulepacks/README.md) — authoring a pack end to end, including what is *not* auto-wired
- [spec/compatibility.md](spec/compatibility.md) — what v1.0 promises per contract, what the freeze deliberately does not cover, and the decisions behind the receipt having no extension point; read it before proposing a field on any hashed document
- [spec/pack-verification.md](spec/pack-verification.md) — the static verifier's fragment, its per-operator encoding, and what a green `prove` run does and does not license
- [spec/whatif.md](spec/whatif.md) — backward queries, the solver-proposes/kernel-disposes contract, and why UNSAT is the weaker verdict
- [examples/README.md](examples/README.md) — reference wiring for adopters: duly consumed from outside, starting with the OR-Tools closing scheduler
- [examples/ontologies/README.md](examples/ontologies/README.md) / [spec/ontology-conformance.md](spec/ontology-conformance.md) — the ontology registry, the crosswalk rules (verify or omit), and the conformance gate's exact subset
- [examples/starters/README.md](examples/starters/README.md) — starter layout and shared tooling
- [examples/golden/README.md](examples/golden/README.md) — corpus contract, case-id series, regeneration rules
- [spec/grounded-facts.md](spec/grounded-facts.md) / [spec/rule-ir.md](spec/rule-ir.md) — the contract, with open questions at the bottom (check them before "fixing" something deliberate)
- [review/README.md](review/README.md), [calibration/README.md](calibration/README.md) — component contracts and their honest caveats
