# Contributing to duly

The most useful contribution right now is not a patch. It is **trying duly against
a real document workflow and telling us where it does not fit** — the vocabulary it
cannot express, the rule shape it cannot state, the seam that assumes something your
organization does differently. duly is pre-1.0 with one author and no adopters; the
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
[rulepacks/](rulepacks/README.md) before any rule pack,
[ontologies/](ontologies/README.md) before any ontology,
[golden/](golden/README.md) before anything that regenerates the corpus.

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
uv run pytest core/tests kernel/tests demo/tests assurance/tests store/tests \
  calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
uv run python -m duly_assurance verify    # all 351 golden receipts, byte-for-byte
uv run python -m duly_assurance impact    # what your change flips vs the baseline
uv run spec/validate.py                   # spec examples: schemas + hashes
```

Run all four before every commit. Tests behind the four optional-dependency markers
(`linkml`, `z3`, `ortools`, `docling`) are skipped by that pytest line and run in
their own workflow; [CLAUDE.md](CLAUDE.md) lists how to run them locally.

**`git diff -- golden/` should be empty** unless regenerating the corpus is the
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

Rule packs are the contribution path with the most leverage and the most rules.
[rulepacks/README.md](rulepacks/README.md) walks it end to end, including what is
*not* auto-wired. Three things catch people:

- **Every rule cites its authority.** A rule with no citation and no
  `TODO(verify)` naming what is unconfirmed will not be merged.
- **Rule ids are permanent** and appear in every receipt that cited them, so an id
  encoding a day count or a statute section is wrong forever once the law moves.
  The convention is `<PREFIX>-<TOPIC>[-QUALIFIER][-NN]` and the validator enforces it.
- **`expected.yaml` is not the corpus.** Declared outcomes catch a pack that
  *breaks*; only the golden corpus catches one whose *meaning moved*. Both are
  required.

## Changes that need a conversation first

Open an issue before writing code if your change would:

- add a field to the fact, receipt, or run-envelope schema — the contracts are
  frozen and the receipt has **no extension point**
  ([spec/compatibility.md](spec/compatibility.md));
- change what the kernel *means* by an existing pack (a semantics change, which
  rewrites every committed receipt);
- add a required dependency to the kernel path;
- edit a committed ontology version file, which is immutable by design.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Licence

Contributions are accepted under the [Apache License 2.0](LICENSE), the licence
this project ships under.
