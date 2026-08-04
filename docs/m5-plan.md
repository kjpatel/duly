# M5 execution plan — working document

**Audience:** any agent or human executing a piece of M5. Read
[CLAUDE.md](../CLAUDE.md) first — its invariants and gotchas apply to every
task below and are not repeated here. Then read the phase you are executing,
in full, before touching anything.

**Authority:** the decisions in §1 were made by Kushan (2026-08-01) after the
trade-offs were argued. Do not re-litigate them in a PR; if you find evidence
one is wrong, stop and raise it instead of working around it.

**Lifecycle:** this file is a working document, updated by the PR that
completes each task (tick the checkbox, add a line to Appendix B). It is deleted when
M5 closes; anything in it worth keeping graduates to the README, a spec, or
CLAUDE.md by then.

**Prerequisite (met):** [PR #37](https://github.com/kjpatel/duly/pull/37)
(`SEMANTICS_VERSION` pin + [docs/release-process.md](release-process.md)) is
merged. Several sections reference both.

---

## 1. Locked decisions

| # | Decision | The short why |
|---|---|---|
| D1 | **One distribution, `duly`, with extras** — not per-package distributions | Nine packages would mean nine compatibility matrices; pre-1.0 that cost buys nothing |
| D2 | **`demo/` is toolkit**, not example content | After `examples/` is deleted it must still boot and honestly report "no scenarios" — that *is* the degrade-honestly discipline, and a better seam test than deleting it |
| D3 | **Receipt extension: option A** — the schema is frozen with **no extension point**; anything that wants to travel with a receipt travels in a **separately-hashed sidecar** referencing it (the PROV-O idiom: *wrap, never edit*) | Every candidate field is producer-asserted metadata a verifier would recompute anyway; a `decision_digest()` is a pure function of the receipt, so option B stays recoverable without ever being shipped |
| D4 | **`engine.version` is decision semantics, pinned as `SEMANTICS_VERSION = "0.0.1"`**, decoupled from the kernel package version and the distribution version | Landed in PR #37. Three scopes, nested one way: semantics change ⇒ kernel code change ⇒ release, never the reverse |
| D5 | **Kernel package stays `0.0.1`; distribution goes `1.0.0` at M5 close** | The kernel's code did not change meaning; the distribution's promise did |
| D6 | **The corpus is never regenerated during M5** | Every M5 change is a seam, path, or packaging change; `git diff -- golden/` empty is the proof each one was inert |
| D7 | **Claims starter: deferred** | The roadmap admits it only to expose a semantic gap; none has surfaced |
| D8 | **`golden/` moves with the packs** in the separation | The corpus is the baseline *for the six teaching packs*; a toolkit carrying receipts for rules it no longer ships is incoherent |

## 2. Phase graph

```
Phase 0 (probe) ──► Phase 1 (seam) ──┬──► Phase 2 (freeze) ──┬──► Phase 4 (distribution) ──► Phase 5 (guide)
                                     └──► Phase 3 (move) ────┘
```

Phases 2 and 3 are independent of each other and may run in parallel. The
hard edges: 1 before 3 (seam before move), 2 and 3 both before 4 (you publish
the frozen contract and the separated layout, not the mixed state), 4 before 5
(the guide documents what actually ships).

~15–17 PRs total (two added in Phase 1 and Phase 4 after Phase 0 measured what they must fix). Every PR satisfies CLAUDE.md's definition of done
(documented, discoverable, demoable, reconciled) **in that PR**, not in
follow-ups.

## 3. Rules for every executor

1. **Branch, PR, squash-merge. Never commit to `main`.**
2. Before every commit: the full suite, `python -m duly_assurance verify`,
   `spec/validate.py`. `git diff -- golden/` must be empty (D6) — if it is
   not, your change was not inert; fix the change, do not regenerate.
3. Read [docs/release-process.md](release-process.md) before touching any
   version number or tag. Never touch `SEMANTICS_VERSION`.
4. New test files: check for basename collisions first
   (`find . -name "test_*.py" | sed 's#.*/##' | sort | uniq -d` — test dirs
   have no `__init__.py`, so pytest imports by basename).
5. Commit messages: imperative subject, body says *why* and includes test
   counts. PR descriptions include the verification commands you ran.
6. When a task says **ASK**, the decision belongs to Kushan. Present the
   options in the PR or in chat; do not pick silently.
7. Tick your checkbox here and append one line to Appendix B in the same PR.
8. **A finding is not filed until some phase owns it.** If your work turns up
   a defect you are not fixing, recording it in Appendix A is half the job:
   also add or amend the task in the phase that will fix it, and say which
   finding it answers. Appendix A is evidence; the phase task lists are the
   work. Phase 0 recorded two findings whose subject matched none of Phase 1's
   clusters, and they would have been skipped by an executor who read only §5.
   If a finding fits no phase, say so explicitly in Appendix A — "not phase
   work" is a decision, and an unrouted finding is an oversight that reads
   identically.
9. **Correct the plan when the work contradicts it.** These sections were
   written before the code was measured; where a task turns out to rest on a
   wrong assumption, fix the task in the same PR and note what moved. Phase 0
   shipped three rules where §4 specified two, and narrowed an **ASK** that
   had been asking the wrong question — both belong in the plan, next to the
   ticked box, not only in a PR description nobody re-reads.

---

## 4. Phase 0 — the probe (1 PR)

**Objective:** the roadmap's *minimal integration example* — three facts, two
rules, one adjudication, one receipt, in author-owned code — built
deliberately from **outside** the repository, so every place the toolkit
secretly assumes the repo layout surfaces as a failure here rather than as a
code-review opinion. This is both a deliverable and the instrument that
produces Phase 1's defect list.

- [x] `examples/minimal-integration/`: a standalone script (or tiny package)
      that defines its own ontology, three grounded facts with correct content
      hashes, a two-rule pack (a default and an override that defeats it),
      calls `duly_kernel.api.adjudicate`, and verifies the returned receipt's
      `receiptSha256` by recomputing it. A README in house style: what each
      artifact is, what the example deliberately does not do.
      *Shipped with **three** rules, not two: the default and its override as
      specified, plus the policy constant they measure against, because the IR
      has no money literal (A5). The default/override defeat relation — the
      point of the requirement — is unchanged and asserted.*
- [x] It runs against an **installed wheel, not the source tree**: `uv build`,
      create a clean venv, `pip install dist/duly-*.whl`, run the example with
      the repo *not* on `sys.path`. A small CI job does exactly this.
      *`check_wheel.sh` + `.github/workflows/minimal-integration.yml`. The
      wheel run reproduces the in-repo `receiptSha256` byte-for-byte.*
- [x] Every friction point encountered — an import that reaches for a repo
      root, a default path that assumes `rulepacks/` exists, a function that
      cannot be called without repo files — is recorded in Appendix A verbatim, with
      file and line. Do not fix them in this PR; the fix is Phase 1's scope.
      *Six findings, A1–A6. Phase 1: A1, A3, A4 (each now has a task in §5).
      Phase 4: A2. A5 was a documented IR boundary and A6 a live bug; both
      were fixed in the same PR, since a compiler emitting a pack that fails
      at adjudication is not phase work.*

**Landmines:**
- `examples/` is deliberately not in the main pytest paths; the example's
  check runs in its own CI job (it needs no optional deps, so it does not
  belong in optional-deps.yml's marker pattern — a plain job is fine).
- Facts must satisfy `spec/schemas/grounded-fact.schema.json` including
  `schemaRef`; check what the schema actually requires rather than assuming.
  If the conformance gate wants a registry, build one from the example's own
  ontology via `duly_conformance` — that is the bring-your-own path working.
- Hashing rules are in CLAUDE.md invariants (canonical JSON, exclude `id` and
  the hash field). Get them from `duly_kernel.receipt.content_hash` /
  `spec/validate.py` rather than re-implementing.

**Acceptance:** the CI job is green from a wheel in a clean venv; Appendix A is
populated; the README exists.

## 5. Phase 1 — the seam (4–5 PRs)

**Objective:** library code takes caller-supplied content roots everywhere;
repo-layout discovery is demoted to thin convenience loaders. The pattern to
copy is [`conformance/duly_conformance/registry.py`](../conformance/duly_conformance/registry.py):
*"Library code takes a registry, never a repo path"* — with
`load_repo_registry` as the convenience loader for this repo's layout.

No file moves in this phase. Golden replay byte-identical proves every PR
inert.

Known seam violations (from the Phase 0-era survey; Appendix A adds more):

- [ ] **Assurance cluster (1 PR):** `verify.py` `repo_root()`;
      `generate.py`'s hardcoded pack-path constants and `STATE_TEMPLATES` —
      make the template set a registry that example content populates from
      outside the package (auto-discovery over registration where possible);
      `impact.py` root resolution.
- [ ] **Review + whatif (1 PR):** `review/duly_review/queue.py` `_REPO_ROOT`;
      `whatif/duly_whatif/__main__.py` root discovery.
- [ ] **Demo (1 PR):** the four `REPO_ROOT` constants in `app.py`,
      `rules_api.py`, `evidence_api.py`, `receipts_api.py` become one
      configurable content root (env var or explicit config), defaulting to
      the repo layout so `uvicorn demo.app:app` still works unchanged.
- [x] **Kernel + conformance entry points (1 PR)** — added after Phase 0
      measured them (A1, A3), and the only Phase 1 work on the *adoption*
      path rather than the repo-layout one:
      - re-export `content_hash` from `duly_kernel`'s package root. Every
        integration must content-address its own facts before it can call
        anything, so it is a first-contact API reachable only as
        `duly_kernel.receipt` — a module path that reads private. Consider
        also `seal_fact()`: `examples/minimal-integration/run.py`'s nine-line
        `seal()` will otherwise be copied verbatim into every adopter's code.
      - `duly_conformance`'s CLI must not default `--ontologies` to a
        repo-relative `ontologies`, and must not surface a missing directory
        as an uncaught `OntologySubsetError` traceback from `registry.py:61`.
        Two defects on one line: the repo-layout default, and a stack trace
        where a diagnostic belongs.
- [ ] **Empty-corpus semantics.** Phase 0 measured this and it is *smaller*
      than first written. `verify` on an empty `cases/` already exits **0**
      (`verified 0 cases`) and only a *missing* directory exits 1, which is
      defensible as it stands. `impact` on the same empty corpus exits **2**.
      So the decision was not "what should verify do" but "may either command
      fail an adopter's day-one CI run, and should the two agree?"
      **DONE.** **DECIDED (Kushan, 2026-08-04): succeed, but say so unmissably.** `impact`
      exits 0 on an empty corpus like `verify` already does, and both print a
      line nobody can mistake for coverage. Exit 0 keeps day-one adoption
      unblocked; the message exists because the alternative is the trap
      [rulepacks/README.md](../rulepacks/README.md) already documents — a
      cheerful "0 of N decisions flip" that means the tool could not see
      anything, read as a pass. A `--require-cases N` flag is the natural
      follow-on if a real workload wants CI strictness; not built until one
      does.

**Landmines:**
- `kernel/duly_kernel/report.py` renders a `rulepacks/<name>/pack.yaml` path
  *string* into reports — that string is cosmetic but appears in committed
  report examples; changing it is not inert. Leave it or prove it inert.
- `demo/tests/test_api.py` sets `DULY_DEMO_FORCE_FIXTURE=1` at import time,
  process-wide (CLAUDE.md gotcha). Any new demo configuration must not
  collide with that mechanism.
- `impact.analyze`'s `pack_overrides` is keyed by *resolved* pack path
  (CLAUDE.md gotcha) — root configurability must not silently change what
  those keys resolve to.

**Acceptance per PR:** full suite green, `verify` 351 byte-for-byte,
`git diff -- golden/` empty, and the Phase 0 example still passes from a
fresh wheel.

## 6. Phase 2 — the freeze (2 PRs)

**Objective:** `spec/compatibility.md` — the stability promise v1.0 makes —
plus the code that backs its one claim needing code.

- [ ] **The decision memo + policy (1 PR).** `spec/compatibility.md` in house
      style (decision / rationale / rejected alternative), covering:
      - **Option A stated normatively** (D3): the receipt schema has no
        extension point; the sidecar is the blessed mechanism; named
        candidates (`rulePack.compiledFrom`, declared disjointness proofs,
        signatures) and where each would live instead. This closes
        [spec/dmn.md](../spec/dmn.md) open question 1 and
        [spec/pack-verification.md](../spec/pack-verification.md) open question 1 —
        update both files' open-questions sections to point here.
      - **The semantics-scoped replay guarantee**: a receipt sealed under
        semantics version V replays byte-identically under any kernel
        implementing V; a semantics change is a new V; the corpus carries
        cases at every V still promised. Resolves the PENDING in
        release-process.md §4.
      - **The version-scope policy**, resolving release-process.md's other
        two PENDINGs: the five reader-less package `__version__` strings
        (**ASK**: keep `duly_kernel.__version__` — it gains a reader in the
        verifier-identity line — and drop the other five as decorative, or
        keep all), and the rule-pack `2026.x.y` scheme (**ASK**: what the
        components mean has never been written down; Kushan defines, the PR
        records).
      - What "frozen" means for the fact, receipt, and IR contracts, and the
        deprecation policy for a major-version break.
- [ ] **`decision_digest()` (1 PR).** A pure function over a receipt's
      determinant fields (`decision`, `asOf`, `rulePack.{name,version}`,
      `rulesFired`, `derivation`, `inputFacts`, `abstentions` — the memo
      fixes the exact list, including where `rulePack.gitCommit`/`url` land),
      with committed test vectors over the golden corpus. Nothing *hashes*
      it into any document — it exists so the determinant boundary is code,
      not prose, and so option B stays recoverable. Its consumer is the
      compatibility policy itself; say so in the docstring.
- [ ] **Changelog + architecture reconciliation.** The freeze sharpens claims
      the architecture doc already makes (the two-hash question, "which
      artifact decided vs what was decided") — check the five places
      CLAUDE.md's definition-of-done names.

## 7. Phase 3 — the move (2–3 PRs)

**Objective:** teaching content relocates under `examples/`; toolkit
directories contain zero example content; `git rm -r examples/` leaves a
working, empty toolkit. Mechanical, **no behavior change**, golden replay
proves it.

- [ ] **Toolkit-owned fixtures first (1 PR).** Before anything moves, the
      toolkit suites that currently test through the six real packs get
      their own tiny fixture packs (extend the `kernel/tests/fixtures/`
      pattern). Otherwise the deletion test passes vacuously — suites that
      silently skip because their subject matter left. 27 of 53 test files
      currently touch example content; not all need fixtures (some *are*
      example tests and move with the content), but the ones asserting
      toolkit behavior do.
- [ ] **The move itself (1 PR).** `git mv` of `rulepacks/`, `starters/`,
      `golden/` (D8), the teaching ontologies, `dmn/examples/`, and the
      generator templates (now a registry per Phase 1) under an `examples/`
      umbrella — propose the exact layout in the PR. Update: CI workflow
      paths and the optional-deps paths filter, CLAUDE.md's layout table and
      verify commands, every README path reference. `review-0001` is
      preserved-forever and pins `duly-starter-notice` — it moves intact;
      `schemaRef` is a name, not a path, so no hash moves.
- [ ] **The deletion gate (1 PR).** A CI job: `git rm -r examples/`, run the
      toolkit suites, run `verify` (expect `verified 0 cases` per Phase 1),
      **boot the demo and assert the honest empty state** — the surfaces
      must stand up and say "no scenarios", not crash. "Tests pass" alone is
      weaker than the roadmap's claim.

**Landmines:**
- The closing scheduler's `test_the_plan_is_the_committed_demo_output` and
  the optional-deps paths filter (CLAUDE.md gotcha) — paths in that workflow
  change in the move PR.
- `demo/tests/test_api.py`'s import-time env var, again.
- The M4 ontology consolidation (CLAUDE.md's `schemaRef` gotcha) is the
  template for how to verify a mass path move: targets + fixtures + templates
  together, `notice-*`/`review-*` proven byte-untouched.

## 8. Phase 4 — distribution (3–4 PRs)

**Objective:** `pip install duly` gives an adopter the seam.

- [ ] **`demo` becomes `duly_demo` (1 PR).** It is not currently a package —
      no `__init__.py`, generic top-level name that would collide in
      site-packages, `static/` not package data. Rename, package, ship
      static assets as package data, keep `uvicorn duly_demo.app:app`
      working, update tests. No hash implications.
- [ ] **Dependencies (1 PR)** — added after Phase 0 measured it (A2). A
      kernel-only `pip install duly` installs 18 packages including `fastapi`,
      `starlette`, `uvicorn`, `pydantic`, `reportlab`, `pillow`, `click`,
      `anyio` and `h11`. They are declared unconditionally in
      [`pyproject.toml`](../pyproject.toml) `[project] dependencies` and serve
      the demo server and the PDF audit report; only `pyyaml` is on the
      document→receipt path. Move them behind extras (`demo`, `report`), keep
      the demo working, and make the Phase 0 wheel check assert the *core*
      install stays small — otherwise this regresses silently the next time
      someone adds a convenience import. "The audit toolkit installed a web
      server" is a bad first line in a security review.
- [ ] **Packaging (1 PR).** Distribution version to `1.0.0` (release-process
      §3: distribution only — kernel stays `0.0.1` per D5, and
      `test_engine_identity.py` enforces the receipt side). Console entry
      points for the CLIs currently reachable only as `python -m …`
      (**ASK**: which ones; recommend `duly-verify`, `duly-impact`,
      `duly-conformance`, `duly-dmn`, `duly-whatif`). Decide the
      `scheduling` extra (**ASK**: its only consumer is the deletable
      closing-scheduler example — move the dependency declaration into the
      example, or keep the extra as a courtesy).
- [ ] **The smoke gate.** CI: build the wheel, install into a clean venv,
      run the Phase 0 example against it. (May already exist from Phase 0 —
      then just assert it still covers the final layout.)
- [ ] **Tag `v1.0.0`** at milestone close per release-process §6 — the first
      tag that is both milestone and package release; the checklist in §7
      of that doc runs in full, including every marker-gated suite.

## 9. Phase 5 — adopter's guide + contribution path (2–3 PRs)

**Objective:** the v1.0 exit criterion — an independent engineering team can
install duly, integrate its own document and extractor, author a pack, and
reproduce its own receipt without a repository fork or maintainer assistance.
The PRD's bar: one working day.

- [ ] **Adopter's guide.** One end-to-end bring-your-own walkthrough:
      documents → extraction adapter → grounded facts → ontology conformance
      → rule packs → golden corpus → review queue → calibration labels.
      Written against the *final* layout, executed literally start-to-finish
      before it is claimed done. The model for its "not automatic" honesty is
      [rulepacks/README.md](../rulepacks/README.md)'s three-things-are-not
      section.
      *Start from [`examples/minimal-integration`](../examples/minimal-integration/),
      which already covers the walkthrough's first five steps in code an
      adopter can run — the guide's job is the rest (a real extractor, the
      store, the review loop, a corpus) plus the seams a reader trips on.
      Carry over the idiom Phase 0 found the hard way: a threshold is a rule,
      not a number in a guard ([spec/rule-ir.md](../spec/rule-ir.md),
      "A threshold is a rule, not a number in a guard").*
- [ ] **Contribution path.** Complete the authoring guide and contribution
      checks across packs, ontologies, starters, and golden-corpus coverage
      — now phrased for content living under `examples/`.
- [ ] **Close-out.** README status + roadmap updated; changelog entry written
      (what M5 turned out to mean); this file deleted, with anything durable
      graduated to its permanent home.

---

## Appendix A — Phase 0 defect list (populated by the probe; consumed by Phase 1)

> Executor: append findings here verbatim — file, line, what failed, what the
> example had to do to work around it. Do not fix in Phase 0.

Probe run 2026-08-01 against `duly-0.0.1-py3-none-any.whl` in a clean venv,
example copied outside the repository, source tree off `sys.path`.

**The headline is that the kernel path is clean.** `adjudicate`,
`content_hash`, `parse_ontology`, `OntologyRegistry` and `assert_conformant`
all work with no repository present, and the wheel-run receipt hash is
byte-identical to the in-repo one. Every finding below is at the edges.

**A1 — `content_hash` is not exported from the package root.**
[`kernel/duly_kernel/__init__.py`](../kernel/duly_kernel/__init__.py) exports
only `adjudicate`; `dir(duly_kernel)` shows no `content_hash`. Every
integration must content-address its own facts before it can call anything,
so this is a *first-contact* API, and it is reachable only as
`from duly_kernel.receipt import content_hash` — a module path that reads
private. The example imports it anyway because reimplementing the canonical
form would produce facts nobody else can verify. **Phase 1:** re-export at
the package root (and consider `seal_fact()`, which every integration writes
by hand — `run.py`'s `seal()` is nine lines that will be copied verbatim into
every adopter's codebase).

**A2 — a kernel-only install pulls a web framework and a PDF library.**
`pip install duly` installs 18 packages including `fastapi`, `starlette`,
`uvicorn`, `pydantic`, `reportlab`, `pillow`, `click`, `anyio`, `h11`. They
come from [`pyproject.toml`](../pyproject.toml) `[project] dependencies`,
which lists `fastapi`, `uvicorn` and `reportlab` unconditionally — they serve
the demo server and the PDF audit report, neither of which an embedding
integration uses. Only `pyyaml` is needed on the document→receipt path.
**Phase 4** (not Phase 1): move them behind extras (`demo`, `report`). Worth
flagging early because it is a packaging decision D1 touches, and because
"the audit toolkit installed a web server" is a bad first impression for a
security review.

**A3 — `duly_conformance`'s CLI defaults to a repo-relative path and
tracebacks when it is wrong.**
[`conformance/duly_conformance/__main__.py`](../conformance/duly_conformance/__main__.py)
defaults `--ontologies` to `ontologies`, i.e. duly's own directory relative to
cwd. Outside the repository both verbs fail — and fail as an *uncaught*
`OntologySubsetError` traceback from `registry.py:61`, not as a CLI
diagnostic. Two defects, one line: the default assumes the repo layout, and
the failure mode is a stack trace. Passing `--ontologies <dir>` works
perfectly, which is the shape Phase 1 wants everywhere. **Phase 1:** no
repo-relative default (require the flag, or resolve nothing), and catch the
error into a message with an exit code.

**A4 — `verify` and `impact` disagree about what an empty corpus means.**
Measured: `verify --golden <dir-with-empty-cases/>` → `verified 0 cases`,
**exit 0**. `verify --golden <missing-dir>` → exit 1. `impact` on the same
empty corpus → **exit 2**. So the Phase 1 ASK is narrower than §5 states:
`verify` already treats an empty corpus as success and only a *missing*
directory as an error, which is defensible. The real inconsistency is
`impact`, which an adopter with a day-one empty corpus hits on their first CI
run. **Phase 1:** decide the trio together — missing dir, empty dir, and
which of the two commands may fail a build.

**A7 — `content_hash` is implemented seven times.** Found while fixing A1.
`kernel/duly_kernel/receipt.py`, `store/duly_store/store.py`,
`assurance/duly_assurance/generate.py`, `calibration/duly_calibration/facts.py`,
`whatif/duly_whatif/casefacts.py`, `spec/validate.py` and
`starters/tools/check_facts.py` each carry their own `canonical()` +
`content_hash()`. **All seven agree today** — measured, not assumed — so this
is duplication rather than a live bug. But it is the project's most
invariant-critical function, and a drift would be silent and misattributed
(CLAUDE.md's JS-number gotcha is the same failure: "the symptom accuses the
wrong party").

Consolidation is *not* mechanical, which is why it is not in the A1 PR.
`duly_kernel`, `duly_store`, `duly_conformance` and `duly_calibration` are all
leaf packages — none imports another — so pointing `duly_store` at
`duly_kernel` means the store cannot be used without the kernel. And two of
the seven should stay independent on purpose: `spec/validate.py` and
`starters/tools/check_facts.py` are differential checks *on* the
implementation, and importing it would make them tautologies (the same
argument the evidence browser's projection makes against calling `as_of`).

**DECIDED (Kushan, 2026-08-04): a shared `duly_core` package, plus spec test
vectors.** The recommendation this replaces was "keep them independent and add
a differential test", and the argument against it is worth keeping because it
corrects a mistake in this plan's own reasoning: **copies of a function are not
independent implementations.** duly's real differential checks have algorithmic
diversity — `prove`'s SMT solving against `validate_pack`'s syntactic matching,
the evidence browser's log replay against the store's survivor projection.
Seven copies of three identical lines have none. A test asserting they agree
proves only that nobody typo'd, while borrowing the credibility of a check that
does much more, and it crowds out the one that would work.

The oracle for a canonicalization function is a **spec**, not a sibling copy.
Concretely: the fact schema says content hashes are "SHA-256 over RFC 8785
(JCS) canonical JSON", and Python's `sort_keys=True` orders keys by code point
while RFC 8785 orders by UTF-16 code unit — they disagree for non-BMP
characters. All seven implementations agree with each other *and* are equally
unable to say whether the RFC claim holds. Committed `(document, digest)`
vectors are what closes that, and they double as the artifact another language
needs to implement duly's fact contract at all.

So: one implementation in `duly_core` (narrow charter — canonical form and
content addressing, nothing else), `content_hash(doc, hash_field)` with no
default, all seven call sites migrated including `spec/validate.py` and
`check_facts.py`, `duly_kernel` re-exporting so adopters need not know a second
package exists, and vectors in `spec/`. The RFC 8785 gap is resolved rather
than left: measured across 1772 committed documents, **zero have non-ASCII
object keys**, so adopting true UTF-16 key ordering is provably inert — the
label becomes true instead of being weakened. **DONE**, and the inertness held:
351 receipts replay byte-for-byte with the sort order changed.

**A6 — the DMN compiler could emit a pack that fails at adjudication, and
called it success.** Found by chasing A5. A money column with `> 200` in it is
the most natural cell a business analyst writes; it is valid S-FEEL, renders
to valid duly source, and yields a pack `validate_pack` *accepts* — the rule
IR type-checks nothing at load time. `compiled 1 rule(s)` was printed, and the
pack died on the first real fact with `cannot compare money with decimal`.
[spec/dmn.md](../spec/dmn.md)'s own posture is that a compiler emitting a pack
the kernel rejects has compiled nothing; this was worse, because the kernel
*accepted* it. **Fixed in this PR** rather than deferred: it is a bug, not
phase work. `compile_definitions` now takes an optional attribute → value-kind
mapping (`--ontologies DIR` on the CLI) and refuses the cell by name; without
the mapping it says nothing rather than guessing, the same posture as
conformance being optional at the envelope seam. Committed as a refusal
example with the rest.

**A5 — the IR has no money literal, and nothing says so where an author
looks.** A money threshold cannot be written in a guard: the expression
grammar ([`kernel/duly_kernel/expr.py`](../kernel/duly_kernel/expr.py), module
docstring) admits `NUMBER | STRING | "true" | "false"` only, and every
committed pack compares money to money (`actual > disclosed`). The example
expresses its $200 limit as its own rule (`EXP-LIMIT-00`) bound through
`derived:`. **This is an IR expressiveness boundary, not a seam defect** — and
arguably the right one, since it turns a constant into a cited, effective-dated,
impact-measurable rule. **Documented rather than removed, in this PR:** the
kernel's type error now names the idiom instead of only diagnosing the
mismatch, and [spec/rule-ir.md](../spec/rule-ir.md) states the absence where
the operator table is with a worked example — it was previously discoverable
only by reading the parser. No money literal was added: no consumer wants one
(not one committed pack uses an inline numeric literal in *any* guard), and it
would touch the parser, `prove`'s SMT fragment, the DMN compiler, the studio's
grid projection and whatif to make packs worse at the effective-dating
regulated domains need most.

## Appendix B — Progress log

> One line per merged PR: date, PR #, phase, what moved.

- 2026-08-01 — [#37](https://github.com/kjpatel/duly/pull/37) — pre-plan —
  `SEMANTICS_VERSION` pinned; `docs/release-process.md`; the version-scope
  model (D4/D5) landed with its behavioral guard.
- 2026-08-01 — [#38](https://github.com/kjpatel/duly/pull/38) — pre-plan —
  this plan committed; CLAUDE.md points to it.
- 2026-08-01 — [#39](https://github.com/kjpatel/duly/pull/39) — pre-plan —
  architecture guide and PRD reconciled; docs accuracy sweep; one unified
  architecture diagram.
- 2026-08-01 — **Phase 0 complete** — `examples/minimal-integration` plus its
  wheel-check workflow; Appendix A populated with five findings (A1–A5).
- 2026-08-04 — **Phase 1, `duly_core` + empty-corpus semantics** — A7 done:
  one canonical implementation, seven call sites migrated, `spec/canonical-vectors.json`
  committed as baseline and interop artifact, and RFC 8785 key ordering made
  true rather than approximate (provably inert — 351 receipts byte-identical).
  Empty-corpus option C done: `impact` now agrees with `verify` and both
  refuse to let "0 of 0" read as a pass.
- 2026-08-03 — **Phase 1, kernel + conformance entry points** — A1 fixed
  (`content_hash` and a new `seal_fact` exported from `duly_kernel`'s root;
  the minimal-integration example now uses them and its receipt is
  byte-identical), A3 fixed (no repo-relative `--ontologies` default,
  `DULY_ONTOLOGIES` accepted, a missing registry diagnosed rather than
  raised, exit 2 distinct from exit 1). First tests for the conformance CLI —
  its absence is why both defects shipped. A7 recorded and routed.
- 2026-08-03 — Phase 0 follow-up — chasing A5 found A6, a live bug: the DMN
  compiler emitted a pack that adjudication rejects and reported success.
  Fixed with the kernel's teaching type error and the spec statement (A5),
  and the same gap closed in the rule studio's import panel. Phase 1 and
  Phase 4 each gained a task; the empty-corpus ASK narrowed.
