# Golden corpus

Committed synthetic adjudication cases with their golden receipts. This corpus is the baseline for two assurance tools:

- **Replay verification** (`python -m duly_assurance verify`): re-adjudicate every case against its committed receipt and assert `receiptSha256` is byte-identical. Proves determinism continuously.
- **Impact analysis** (`python -m duly_assurance impact`): re-adjudicate every case under the *current working-tree rule packs* and report every case whose decision differs from its golden receipt — "this change flips N of M historical decisions" — with before/after receipts for review. The committed receipts ARE the baseline; no git archaeology needed.

## Layout

```
golden/
  README.md
  cases/<case-id>/case.yaml        # {id, pack, question, asOfEffective, asOfKnowledge}
  cases/<case-id>/facts/*.json     # schema-valid GroundedFacts for the case
  receipts/<case-id>.json          # the golden DecisionReceipt
```

`pack` is a repo-relative path to a `pack.yaml`. Case ids are stable, sorted, and derived from the generator seed — regeneration with the same seed and templates is byte-identical.

## Tool contracts

```
python -m duly_assurance generate --out golden --count 250 --seed 7
python -m duly_assurance verify  [--golden golden]           # exit 1 on any mismatch
python -m duly_assurance impact  [--golden golden] [--json out.json] [--markdown out.md]
```

- `generate` synthesizes cases from per-scenario templates (state notice cases varying state, dates, margins, grounds; TRID cases varying disclosed/actual amounts), adjudicates each with the kernel, and writes cases + receipts. Seeded and deterministic: no wall clock, `random.Random(seed)` only.
- `verify` exits non-zero on the first hash mismatch and prints the case id and the differing fields.
- `impact` never fails the build by itself; it reports. `--markdown` writes the PR-comment body: a summary line, a table of flipped cases (id, question, before → after), and up to five before/after receipt excerpts.

## Rules for humans

- Never hand-edit a case or receipt; change the generator (or the packs) and regenerate.
- A rule-pack PR that flips golden decisions must either justify every flip in the PR description or fix the pack. Regenerating receipts to match a pack change is the *reviewed, deliberate* act of accepting the new baseline.
