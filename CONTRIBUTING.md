# Contributing to duly

The most useful contribution right now is not a patch. It is **trying duly against
a real document workflow and telling us where it does not fit** — the vocabulary it
cannot express, the rule shape it cannot state, the seam that assumes something your
organization does differently. duly has one author and no adopters yet — its contracts
are at v1.0 and held stable, but nothing has ever depended on them; the
gap between "the design is coherent" and "the design survives contact" is the thing
we cannot close alone. Open an issue describing the workflow, not a feature request.

If you do want to write code, everything below applies.

---

## Before you start

Read [CLAUDE.md](CLAUDE.md). It is written for coding agents and is equally the
fastest orientation for a human: the layout, the four invariants, the verification
commands, and — most valuable — a list of gotchas that have **actually bitten**,
each with the symptom that made it hard to find. Most of a first PR's surprises are
already written down there.

Then read the component README for whatever you are touching:
[examples/rulepacks/](examples/rulepacks/README.md) before any rule pack,
[examples/ontologies/](examples/ontologies/README.md) before any ontology,
[examples/starters/](examples/starters/README.md) before any starter documents or facts,
[examples/golden/](examples/golden/README.md) before anything that regenerates the corpus,
[extraction/](extraction/README.md) before any extraction adapter.

## The four invariants

A change that breaks one of these is wrong even if every test passes. They are
stated in full in [CLAUDE.md](CLAUDE.md); in short:

1. **Determinism everywhere.** No wall clock in library code — timestamps are
   caller-supplied. No unseeded randomness. Same inputs, byte-identical outputs,
   forever.
2. **Content addressing.** Facts, receipts and envelopes are hashed over their
   canonical JSON. Never mutate a stored document: a correction is a *new* fact
   that supersedes the old one, and an export format *wraps* rather than edits.
3. **Golden replay.** The 351 committed receipts replay byte-for-byte on every
   push. A change that moves them is not necessarily wrong, but it must be
   intentional, explained, and visible.
4. **Honest labeling.** Every rule cites its authority or carries `TODO(verify)`
   naming what was not confirmed. Invented history is marked `DEMO-SYNTHETIC`.
   When the IR cannot express something, document the boundary — *a documented
   limitation is a contribution; a silent approximation is a defect.*

## Setup and verification

```bash
uv sync
uv run pytest core/tests kernel/tests duly_demo/tests assurance/tests store/tests \
  calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
uv run python -m duly_assurance verify    # all 351 golden receipts, byte-for-byte
uv run python -m duly_assurance impact    # what your change flips vs the baseline
uv run spec/validate.py                   # spec examples: schemas + hashes
```

Run all four before every commit. Tests behind the four optional-dependency markers
(`linkml`, `z3`, `ortools`, `docling`) are skipped by that pytest line and run in
their own workflow; [CLAUDE.md](CLAUDE.md) lists how to run them locally.

**`git diff -- examples/golden/` should be empty** unless regenerating the corpus is the
point of your change. If it is not empty and you did not mean it, your change was
not inert — fix the change rather than the corpus.

## Pull requests

- **Branch, PR, squash-merge.** Never commit to `main`. CI runs the full matrix
  plus rule-impact analysis.
- **Commit messages**: imperative subject; the body says *why*, includes test
  counts, and — for any rule or corpus change — the `impact` result.
- **PR descriptions** include the verification commands you actually ran.
- **New test files**: check for basename collisions first
  (`find . -name "test_*.py" | sed 's#.*/##' | sort | uniq -d`). Test directories
  have no `__init__.py`, so pytest imports by basename and identical names across
  suites break collection.
- **Never touch `SEMANTICS_VERSION`**, and read
  [docs/release-process.md](docs/release-process.md) before changing any version
  number. There are four independent version scopes and the instinct to make them
  agree is the most destructive edit available in this repository.

## What "done" means here

A feature is not shipped when the code merges. It is shipped when it is
**documented, discoverable, demoable, and reconciled** — all four in the PR that
introduces it, not in follow-ups:

- **Documented** — spec or README coverage, including the honest "deliberately does
  not do" boundaries.
- **Discoverable** — the newcomer entry points that should now lead there actually
  do: the README components table, [docs/concepts.md](docs/concepts.md), the FAQ if
  a skeptic would ask, and the component README a practitioner reads.
- **Demoable** — something runnable that shows the benefit, executed before you
  claim it works.
- **Reconciled** — [docs/neuro-symbolic-architecture.md](docs/neuro-symbolic-architecture.md)
  is the system mental model, and a mental model that describes a shipped capability
  as "a possible extension" is worse than one that omits it.

This is a high bar for a small change, and it is the reason the documentation is
worth reading: it has been kept true.

## Contributing a rule pack

The first of the two edges. duly's largest contribution surfaces sit at the
*edges* of the contract, where domain knowledge matters more than familiarity
with the kernel ([contribution model](README.md#contribution-model)): rule
packs here, extraction adapters in the section that follows. A first-week
outcome offered on either edge has to be walkable on either edge, so each has
a path of its own, with its own checks.

A pack is versioned, cited, effective-dated domain knowledge, and it is the
path with the most leverage and the most rules.
[examples/rulepacks/README.md](examples/rulepacks/README.md) walks it end to
end and is the mandated reading before you touch one: the authoring mechanics,
the three things that are *not* auto-wired, the constraints that will bite you,
and — under **"Contributing it back"** — the checks your PR triggers, the
ordered pre-PR checklist, what reviewers read for, and what nobody will wire
for you. It hands off to four component READMEs:
[ontologies](examples/ontologies/README.md) (new terms go in a new version
file; committed versions are immutable), [starters](examples/starters/README.md)
(synthetic documents, span-verified facts, the extractor pin),
[golden](examples/golden/README.md) (corpus coverage, and the arithmetic of
adding a generator template), and [dmn](dmn/README.md) if you would rather
author the rules as a decision table.

Three things catch people, and they are worth stating twice:

- **Every rule cites its authority.** A rule with no citation and no
  `TODO(verify)` naming what is unconfirmed will not be merged. A `TODO(verify)`
  is not a demerit; presenting an unverified requirement as verified is.
- **Rule ids are permanent** and appear in every receipt that cited them, so an id
  encoding a day count or a statute section is wrong forever once the law moves.
  The convention is `<PREFIX>-<TOPIC>[-QUALIFIER][-NN]` and the validator enforces it.
- **`expected.yaml` is not the corpus.** Declared outcomes catch a pack that
  *breaks*; only the golden corpus catches one whose *meaning moved*. A pack
  with no generator template gets a cheerful "0 of 351 decisions flip" on every
  edit it will ever receive. Both are required.

Your PR is read by four CI checks — the full suite including the example
content's own tests, a sticky impact comment on any change under
`examples/rulepacks/**`, the gate that deletes `examples/` and runs the toolkit
without it, and the optional-dependency suites — and by a human, for the
honest-labeling invariant that no check can see. All four are tabulated in the
pack README's "What your PR triggers", each with what it cannot see.

## Contributing an extraction adapter

The other edge. A vendor or user of a document AI service can maintain its adapter
independently, the way observability vendors maintain OpenTelemetry exporters —
[extraction/README.md](extraction/README.md) is the contract, the acceptance bar and the
honest boundaries, and [docs/adopters-guide.md §5](docs/adopters-guide.md#5-your-extraction-adapter)
writes one end to end. The path, in the order it is walkable:

1. **Satisfy the protocol.** A `name`, a `version`, and one
   `extract(document, targets) -> ExtractionResult` returning a rendition, facts and a
   run envelope. `isinstance(adapter, ExtractionAdapter)` is a shape check, not a
   conformance proof — it does not look at `extract`'s signature.
2. **Get stub parity first, on a recorded rendition.** Structure the adapter so the
   conversion call *and* the version it stamps are injectable, then drive it from a
   committed recording — which is exactly what `StubAdapter` is, and what lets the
   toolkit's own adapter suite run offline. Assert byte equality against committed
   facts: a fact is content-addressed, so a whitespace-level drift means the committed
   `contentHash` describes nothing the pipeline can still produce.
3. **Verify spans on every emission.** Call `verify_fact_span(fact, rendition.text)`
   inside `extract` before the fact is appended, not in a test, and emit the actual
   rendition slice rather than echoing the target's quote — a whitespace-normalized
   match is a different string. A target you cannot ground goes into
   `ExtractionResult.skipped` with a reason; it is never dropped.
4. **Round-trip the envelope.** produce → `verify_envelope` → `ingest_envelope` →
   `revoke_run`, against an in-memory store, plus the tamper cases
   (`extraction/tests/test_envelope.py` is the worked list). Nothing may reach the
   store when any check fails.
5. **Marker-gate the live path.** Tests that call the real service go in their own
   module behind `pytest.importorskip` (or a skip on a missing credential) and a marker
   registered in `pyproject.toml`, so a plain `uv sync` skips them and the offline suite
   still runs on every PR. duly's own `docling` lane is the model, and it is *not* on
   PRs — run it from the Actions tab before merging anything under `extraction/`.
6. **Document it.** The component README section, and the honest boundary: what your
   adapter refuses, what it costs, what it needs credentials for.

Three things catch people:

- **Confidence is measured or absent, never invented.** `method: "raw"` is the honest
  label for a heuristic proxy; a calibrated score is a different claim made downstream.
  A machine fact with no confidence **fails closed** under an active abstention policy —
  legal, and visible on the receipt.
- **Sensitivity is declared by the target, never inferred from the span.** An adapter
  that guessed at PII would be asserting a handling class it cannot ground.
- **A recording is a baseline.** Re-recording moves the rendition hash, and therefore
  every fact hash and the envelope hash. Treat it like a golden regeneration: deliberate,
  explained in the commit.

## Changes that need a conversation first

Open an issue before writing code if your change would:

- add a field to the fact, receipt, or run-envelope schema — the contracts are
  held stable at v1.0, the receipt has **no extension point**, and a schema
  change is therefore a major-version event with a written procedure rather
  than a PR ([spec/compatibility.md](spec/compatibility.md) C1, C2, C9);
- change what the kernel *means* by an existing pack (a semantics change, which
  rewrites every committed receipt);
- add a required dependency to the kernel path — `[project] dependencies` is
  `pyyaml` and nothing else, and a build check fails if a bare `pip install duly`
  brings a third package. A dependency only a *surface* needs goes in an extra
  (`demo`, `report`, `prove`, `extraction`); one only this repository needs goes
  in `[dependency-groups].dev`, which the wheel never sees; one only an *example*
  needs is declared inside the example, so it leaves when the example does;
- edit a committed ontology version file, which is immutable by design.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Licence

Contributions are accepted under the [Apache License 2.0](LICENSE), the licence
this project ships under.
