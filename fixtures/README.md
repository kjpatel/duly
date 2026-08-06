# `fixtures/` — the corpus the toolkit owns

Everything here exists so that **duly's own test suites do not depend on duly's
teaching content**. It is deliberately boring: one invented domain, one pack
with its declared cases, five cases, five receipts, one ontology, one scenario
and two DMN inputs. Nobody should learn anything from it.

## Why it exists

`rulepacks/`, `starters/`, `golden/` and `dmn/examples/` are *example content* —
they demonstrate the toolkit, and M5 relocates them under an `examples/`
umbrella that an adopter can delete. The claim being tested is that
`git rm -r examples/` leaves a **working, empty toolkit**.

A test suite that reaches into example content cannot check that claim. Delete
the content and such a test does not fail — it stops being collected, skips, or
quietly asserts nothing, which reads exactly like success. So every suite
asserting *toolkit* behaviour moves onto this fixture corpus, and what stays
pointed at `examples/` is the set of tests whose subject genuinely is the
example content (that the six packs load, that their declared outcomes hold,
that every committed fact conforms) — those move with it.

The rule, stated once: **a test that would still pass if its subject were
deleted is not a test.**

## What is here

| Path | What it is |
|---|---|
| `ontology/duly-fixture/0.1.0.yaml` | The vocabulary the fixture facts pin. Invented; models nothing real |
| `pack.yaml` | One rule pack: a default, an exception that defeats it, a derived intermediate, an effective-dated pair, an abstention floor, and a **non-boolean decision with a `phrasing:` block** |
| `expected.yaml` | The pack's **declared outcomes**, run by the rule studio beside impact analysis. Declared cases catch a pack that *breaks*; only the corpus catches one whose *meaning moved* — the studio shows both, so the fixtures have to supply both |
| `cases/fx-000N/` | Five cases: `case.yaml` plus content-addressed facts |
| `receipts/fx-000N.json` | The receipt each case produces, committed |
| `scenario/` | One *scenario*, which is what the demo surfaces read: a document, the extractor's rendition of it, and facts grounded in character spans of that rendition |
| `dmn/` | Two DMN decision tables: one that compiles, one that is refused. The studio's import panel and the compiler's happy path were reachable only through `dmn/examples/`, which an adopter deletes |
| `build.py` | Regenerates the cases, receipts and scenario, deterministically |

Five cases, chosen to cover what the toolkit's own tests need rather than to
teach anything:

- **`fx-0001`** — the exception fires and defeats the default. A derived value
  feeds the deciding rule, so the derivation tree has depth.
- **`fx-0002`** — nothing overrides, so the default presumption stands. Empty
  `inputFacts` on the deciding rule, which is a shape worth having.
- **`fx-0003`** — one fact scores below the pack's confidence floor, so the
  receipt carries a `low_confidence` abstention and still reaches a decision.
- **`fx-0004`** — `fx-0003` after review: the correction supersedes the
  below-floor fact, the abstention is answered and the decision flips. It
  commits the *post-correction projection*, because supersession is a
  store-level projection and `adjudicate` is handed a fact list, not a store.
- **`fx-0006`** — restricted *and* above the threshold, so the category matches
  and the exception still does not fire. It exists for one reason: its score
  (60) is the only one in the corpus that sits **between** the two thresholds
  this pack has ever declared. Every other case scores 12 or 80, so an edit to
  the threshold moves all three restricted cases together or none — and a
  corpus that can only answer "everything moved" cannot demonstrate what impact
  analysis is *for*, which is a pack whose meaning moved while every declared
  outcome stayed green.

And one scenario, which is a different artifact from a case:

- **`fx-0005`** (`scenario/`) — a generated PDF, its rendition, and three facts
  grounded in **character spans** of that rendition — one below the confidence
  floor, and one marked `sensitivity: pii` so the report renderer's redaction
  path has something to redact (the name is invented and refers to nobody). The cases above all use attestation grounding, which is honest for
  synthetic data and leaves the span machinery — the evidence browser's
  highlighting, quotes in the audit report, span verification itself — with
  nothing to exercise. Spans are *found* in the rendition text by the builder,
  never typed: a hand-counted offset is a fact that lies about its own
  evidence.

## Regenerating

```bash
uv run python fixtures/build.py
```

Deterministic: no wall clock, no randomness, every timestamp fixed in the
script. Re-running it on an unchanged tree rewrites the same bytes, and
`git diff -- fixtures/` is the check that it did.

**Regenerating is a deliberate act, exactly as it is for `golden/`.** These
receipts are pinned by toolkit tests — replay, decision digests, the semantics
guard — so a diff here means one of two things: you changed the fixture
content on purpose, or you changed what the kernel *means*. The second is a
semantics change ([docs/release-process.md](../docs/release-process.md) §4) and
this corpus is not the place to discover it; `golden/` is.

## Rules for adding to it

- **Keep it minimal.** Add a case only when a toolkit behaviour cannot be
  asserted with the ones that exist. This corpus is a test dependency, not a
  second demonstration vertical. The bar that has been met twice: `fx:permitted`
  is boolean, so it takes the kernel's Yes/No fallback and never reaches a
  `phrasing:` block — the *whole* phrasing machinery was unreachable until the
  pack grew `fx:assessedFee`. That is what "cannot be asserted otherwise"
  looks like. `fx-0006` met the same bar from the other direction: not a
  behaviour that was unreachable, but a *distinction* the corpus could not
  draw, since every existing case moved together under the edit that mattered.
- **Growing the pack is a rebuild, not an edit.** `pack.version` is inside
  every receipt, so adding a rule moves every receipt, the decision-digest
  vectors and the corpus aggregate. Bump the version, re-run both builders, and
  re-pin what moved — the tests name what they are pinning, so the failures
  read as instructions. Batch growth into one rebuild where you can: two
  separate additions cost two rounds of re-pinning across four files, and the
  second round is the one where a pinned literal quietly becomes wrong.
- **Invent nothing that looks real.** No statute numbers, no jurisdictions, no
  plausible citations. `FX-` rule ids, `fx:` attributes, a `citation.text` that
  says it is fictional. A reader must never mistake this for domain content —
  which is the same honest-labeling discipline the packs follow, pointed the
  other way.
- **It is toolkit, so it never moves.** `fixtures/` stays put when `examples/`
  is deleted. Anything here that only one suite needs belongs in that suite's
  own `tests/fixtures/` instead.
