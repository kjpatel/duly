# Golden corpus

Committed adjudication cases with their golden receipts. This corpus is the baseline for two assurance tools:

- **Replay verification** (`python -m duly_assurance verify`): re-adjudicate every case against its committed receipt and assert `receiptSha256` is byte-identical. Proves determinism continuously.
- **Impact analysis** (`python -m duly_assurance impact`): re-adjudicate every case under the *current working-tree rule packs* and report every case whose decision differs from its golden receipt — "this change flips N of M historical decisions" — with before/after receipts for review. The committed receipts ARE the baseline; no git archaeology needed.

## Layout

```
examples/golden/
  README.md
  cases/<case-id>/case.yaml        # {id, pack, question, asOfEffective, asOfKnowledge}
  cases/<case-id>/facts/*.json     # schema-valid GroundedFacts for the case
  receipts/<case-id>.json          # the golden DecisionReceipt
```

`pack` is a repo-relative path to a `pack.yaml`.

## Case id series

- **Synthetic** (`notice-*`, `trid-*`, `ron-*`, `esign-*`, `resc-*`, `rec-*`): produced by the generator. Ids are stable, sorted, and derived from the generator seed — regeneration with the same seed and templates is byte-identical. Each template is an independent seeded draw stream (`f"{seed}:{name}"`), so adding a template never disturbs another template's cases.
- **Review-born** (`review-NNNN`): frozen from resolved review-queue items by `python -m duly_review golden` (duly_review.golden) — a real correction arc (machine fact abstained → human corrected → decision resolved), not a seeded draw. The generator **preserves** `review-*` entries when it resets the corpus, because no seed can regenerate them; their provenance lives in the review queue's event log (and, for the committed `review-0001`, in `review/tests/test_golden.py`, which replays the exact arc and asserts byte-identical output). `verify` and `impact` treat both series identically.

## Tool contracts

```
python -m duly_assurance generate --out examples/golden --count 350 --seed 7
python -m duly_assurance verify  [--golden examples/golden]   # exit 1 on any mismatch
python -m duly_assurance impact  [--golden examples/golden] [--json out.json] [--markdown out.md]
```

- `generate` synthesizes cases from per-scenario templates, adjudicates each with the kernel, and writes cases + receipts. Seeded and deterministic: no wall clock, `random.Random(seed)` only. Two draw styles: *range* templates (notice, trid) draw parameters over ranges that cross the pack's thresholds both ways; *boundary-stratified* templates (ron, esign, resc, rec) cycle an explicit table of the boundary cells their pack encodes (statutory commencement dates, routing-matrix cells, business-day window shapes, confidence floors), so every boundary is covered by construction. At `--count 350` the template weights (3/3/3/1/1/1/1/1) allocate 75 cases per notice state and 25 to each of trid, ron, esign, resc, and rec. Recording cases include committed receipts whose `abstentions` carry `low_confidence` entries routed to `recording-review`.
- `verify` exits non-zero on the first hash mismatch and prints the case id and the differing fields.
- `impact` never fails the build by itself; it reports. `--markdown` writes the PR-comment body: a summary line, a table of flipped cases (id, question, before → after), and up to five before/after receipt excerpts.

## Rules for humans

- Never hand-edit a case or receipt; change the generator (or the packs) and regenerate. Review-born cases are never hand-edited either — re-run the arc through the queue if one must change.
- A rule-pack PR that flips golden decisions must either justify every flip in the PR description or fix the pack. Regenerating receipts to match a pack change is the *reviewed, deliberate* act of accepting the new baseline.
