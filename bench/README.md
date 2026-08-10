# bench/

Measurement harnesses. Code, not documentation — the numbers they produce are
published in `docs/` with machine, Python version and date, never committed to
any replayable artifact.

The standing rule: **this directory holds the only stopwatches in the
repository.** No wall clock reaches library code (a repo invariant), so
anything that times duly does it from here, outside every package and outside
the wheel.

| Harness | Publishes to |
|---|---|
| `capacity_bench.py` | [docs/capacity-envelope.md](../docs/capacity-envelope.md) |
