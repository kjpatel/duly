# duly review queue

Abstention routing and human corrections re-entering the store as first-class facts — the loop that turns the kernel's "I don't know" into labeled knowledge. Ships as a library over SQLite (Postgres-portable, the fact store's conventions) with a thin FastAPI surface; per the project's "not a UI product" stance, review *interfaces* belong to integrators.

## The loop

```
receipt.abstentions ──enqueue──▶ queue item (open)
                                    │
                     ┌──────────────┴──────────────┐
                 resolve                        dismiss
        (human GroundedFact ingested        (abstention was right;
         via FactStore.ingest; the           reason recorded, no
         conflict policy / supersedes        fact enters the store)
         make it win)                            │
                     │                           │
        golden case (review-NNNN,        calibration label: none —
        replayed byte-for-byte by        a dismissal is a judgment
        `duly_assurance verify`)         about the abstention, not
                     │                   a scoreable value
        calibration label (score, correct)
```

## Queue semantics (the defined part)

- **Item identity / dedup.** An item's id is `urn:duly:review:sha256:<hex>` over the canonical JSON of `{caseId, entry}` — the abstention entry verbatim. Re-adjudicating the same case under the same pack reproduces the identical entry, so enqueue is idempotent for the item's whole lifetime (no duplicate open item; no reopened item after resolution). The receipt hash is deliberately excluded (every re-adjudication mints a new receipt); the entry's `threshold.packVersion` is deliberately included (a floor change makes it a different abstention).
- **Lifecycle.** `open → resolved | dismissed`, terminal both ways. Claiming is a field, not a state. History is an append-only event log (`opened`/`claimed`/`resolved`/`dismissed`); item status is a projection, exactly like the fact store's supersession status.
- **Corrections.** `resolve` takes a human-asserted GroundedFact (assertion.kind `human` with actor id + role, spec D3/D9), validates it against the grounded-fact schema and the item (same case/entity/attribute; `supersedes`, when present, must target an abstained fact), then ingests it through `FactStore.ingest` — the queue never bypasses the store's public API and never stores fact documents itself. Supersession is the durable correction; even without it, a lone live human assertion outranks machine facts at evaluation time (spec resolved question 2). If you want to *see* what a resolution does to the store rather than infer it, the demo's [evidence browser](../docs/demo_tour.md#11-the-evidence-browser) projects the case at any point on its event log: the correction and the fact it superseded both stay visible, and dragging back past the resolution returns the below-floor fact to live. Whether resolve should *require* supersession for `low_confidence` items is deliberately undecided — see open question 2 in [spec/grounded-facts.md](../spec/grounded-facts.md#open-questions) before leaning on the non-superseding form.
- **Routing.** A pack's `abstentionPolicy.routeTo` stamps `routedTo` on every abstention entry at adjudication time (receipts are content-hashed and immutable, so routing cannot be added later). `enqueue_receipt(..., routed_to="notice-review")` filters to one route; unrouted entries are still enqueueable — routing is a label, not a gate. See spec/rule-ir.md, "Routing".

## Calibration label export

`calibration_pairs(queue)` yields `(raw_score, correct)` pairs compatible with `duly_calibration.base.Pair`: a resolved item whose abstention carried a machine `confidence` and whose abstained fact is retrievable from the store contributes `correct=1` when the human confirmed the machine value, `0` when the correction contradicted it (value-equality semantics documented on `values_equal`). Dismissals, no-confidence entries, and resolutions whose machine fact never reached the store yield **no pair — never a guessed one**.

**Censored sample — read before fitting.** These pairs label *abstained* (below-floor) facts only. Facts that cleared the floor were never reviewed, so the export says nothing about the upper score range, and fitting a calibrator on these pairs alone does **not** calibrate the full score distribution. Use them to validate or tighten floors, or combine with labels from audit sampling of accepted facts.

## Corrections become golden cases

`resolved_item_to_golden_case` (CLI: `python -m duly_review golden`) freezes a resolved item's arc as a golden regression case: the case's facts as-of post-correction (a store projection at the resolution's knowledge time) plus a freshly adjudicated receipt, written in the corpus layout. Ids use the distinct `review-NNNN` series; the synthetic generator preserves them across regenerations (golden/README.md). The committed `review-0001` exercises the full arc: a low-confidence mailed-date fact abstained, a human confirmed the date (superseding the machine fact), and the decision flipped from the compliance presumption to non-compliant.

## HTTP surface

`POST /api/enqueue`, `GET /api/items[?status=&caseId=]`, `GET /api/items/{id}`, `GET /api/items/{id}/events`, `POST /api/items/{id}/claim|resolve|dismiss`, `GET /api/calibration/pairs`. Every mutating request carries a caller-supplied `recordedAt` — the API never reads the wall clock, so a replayed request log reproduces the same queue.

```bash
DULY_REVIEW_DB=review.db DULY_FACTS_DB=facts.db \
  uv run uvicorn review.duly_review.api:app --port 8789
```
