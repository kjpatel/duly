# Refusal examples

One minimal DMN document per refusal class. Each is *deliberately* broken in
exactly one way, and each is compiled by [`dmn/tests/test_refusals.py`](../../tests/test_refusals.py),
which asserts the error names the real problem — not just that compilation
failed.

They exist because a compiler's refusals are part of its contract. A test that
only proves the happy path passes leaves the whole failure surface — the half
that decides whether an author can fix their table without reading the
compiler's source — unverified.

| File | Refusal class | What is wrong |
|---|---|---|
| [`non-sfeel-cell.dmn`](non-sfeel-cell.dmn) | `unsupported-expression` | An input cell invokes a FEEL builtin (`sum(...)`). |
| [`unsupported-hit-policy.dmn`](unsupported-hit-policy.dmn) | `unsupported-hit-policy` | `hitPolicy="COLLECT"`. |
| [`uncited-row.dmn`](uncited-row.dmn) | `missing-citation` | A row carries no `duly:citation`. |
| [`undated-row.dmn`](undated-row.dmn) | `missing-effective-date` | A row carries no `duly:effectiveFrom`. |
| [`unprovable-unique.dmn`](unprovable-unique.dmn) | `unprovable-unique` | `UNIQUE` rows separated only by numeric ranges. |
| [`multiple-outputs.dmn`](multiple-outputs.dmn) | `unsupported-table-shape` | Two output columns in one table. |

Run any of them by hand to see the message an author would get:

```bash
uv run python -m duly_dmn compile dmn/examples/refusals/uncited-row.dmn
```

Every refusal class and its rationale is in [spec/dmn.md](../../../spec/dmn.md).
