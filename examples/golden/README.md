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

`pack` is a **content-root-relative** path to a `pack.yaml` — `rulepacks/<name>/pack.yaml`, not `examples/rulepacks/<name>/pack.yaml`. A receipt pins its pack's name and version, never its location, so something has to say what the path is relative to; [`corpus.resolve_pack_path`](../../assurance/duly_assurance/corpus.py) tries the working directory first (what the author of the path meant) and then the corpus root's parent, which is the content root. The second candidate is the one that makes a corpus portable: copy `golden/` and `rulepacks/` into your own tree and the cases still resolve, because neither path mentions this repository.

`asOfEffective` and `asOfKnowledge` are each **a plain date or an RFC 3339 instant**, and the corpus carries both: the generator writes dates from its templates, while a review-born case copies the receipt's `asOf.effective`, which the receipt schema types `date-time` (`review-0001` reads `"2026-07-25T00:00:00Z"`). A bare date means midnight UTC — the kernel's `normalize_point` decides that, and any tool reading a case must parse these fields the same way rather than with its own `date.fromisoformat`. What-if did the latter and crashed on `review-0001` while `verify` passed over the same file; both forms are legal and neither is being deprecated.

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

## Adding a template

A new rule pack gets corpus coverage — and therefore a meaningful impact answer, ever — only by registering a template in [`assurance/duly_assurance/generate.py`](../../assurance/duly_assurance/generate.py) and regenerating. `register_template` takes a name and a dict: the `kind` whose drawer and fact builder it reuses (or a new one via `register_kind`), the `pack` it loads from (working-directory relative; the content-root-relative form written into each `case.yaml` is derived from it — see `written_pack_ref`), the `question`, the ontology, an `as_of_effective`, a `weight`, and either a range draw or an explicit `strata` table. It refuses a duplicate name, so a corpus cannot depend on import order.

Then the arithmetic, which is the part that surprises people. `allocate` splits `--count` across templates **proportionally to their weights**, so adding a ninth template at the current `--count 350` does not add cases — it *redistributes* them, dropping the three notice states from 75 cases each to 70 and deleting the tail of every series. Each template draws from its own seeded stream (`f"{seed}:{name}"`), which is what makes case *i* of an existing template byte-identical across regenerations; it does not protect case *i* from ceasing to exist.

So the rule is: **keep `count / sum(weights)` constant.** Today that ratio is 25 (350 over weights `3+3+3+1+1+1+1+1 = 14`). A new template of weight 1 makes the denominator 15, so the count goes to 375:

```bash
uv run python -m duly_assurance generate --out examples/golden --count 375 --seed 7
```

Verified, not asserted: registering a ninth weight-1 template and generating at `--count 375` leaves all 350 existing receipts byte-identical and adds exactly 25 new ones. At `--count 350` the same registration rewrites the corpus.

After regenerating, read the diff before you commit it:

- **`git diff --stat -- examples/golden`** should show only your new cases and receipts. Any change to an existing receipt is a decision that moved, and belongs in the PR description or in a fix to the pack.
- **A diff on every `case.yaml`'s `pack:` line** is not a baseline change — it means the generator's pack constants and the committed corpus disagree about which root they are relative to. Fix the generator; a corpus whose `pack:` paths carry this repository's `examples/` prefix has stopped being portable, and nothing downstream will complain, because `resolve_pack_path` accepts both forms and the path is not inside any hash.
- **`review-*` must be byte-untouched.** The generator preserves the series when it resets the corpus, because no seed can recreate it.

Then `uv run python -m duly_assurance verify` (which now covers your new cases) and `uv run python -m duly_assurance impact`, which should report zero flips: a regeneration that adds coverage without changing a pack changes no decision.

## Rules for humans

- Never hand-edit a case or receipt; change the generator (or the packs) and regenerate. Review-born cases are never hand-edited either — re-run the arc through the queue if one must change.
- A rule-pack PR that flips golden decisions must either justify every flip in the PR description or fix the pack. Regenerating receipts to match a pack change is the *reviewed, deliberate* act of accepting the new baseline.
- **`git diff -- examples/golden/` is empty unless regenerating the corpus is the point of the change.** If it is not empty and you did not mean it, the change was not inert: fix the change, not the corpus. This is the check that has caught the most, because a corpus diff is the first visible symptom of an accidental semantics change and the easiest thing in the repository to accept by reflex.
