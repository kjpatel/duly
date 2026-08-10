# Working on examples/

Loaded alongside the root CLAUDE.md when work touches the example content.

**This file is deleted by `git rm -r examples/`, and that is correct.** Both
gotchas below are about content that leaves with it. It is also a trap: a
gotcha placed here for tidiness disappears silently when the deletion gate
runs, and the gate reports success. Route to this file only what dies with
`examples/`; anything an adopter still needs after deleting the examples
belongs in the root file or a package's own CLAUDE.md.

- **CP-SAT is nondeterministic by default and lies about why.** It parallelises and randomises, so an optimum can differ between machines: set `num_workers = 1` and `random_seed = 0`, and make the objective's optimum *unique* (a tie lets search order pick the answer). Set `num_workers` **only** — it and the legacy `num_search_workers` are mutually exclusive, and setting both returns `MODEL_INVALID`, which reads exactly like an infeasible problem until you print the status. Treat `MODEL_INVALID`/`UNKNOWN` as a raise, never as "no solution".

- **`examples/tests/` runs in main CI, but the marker-gated example suites do not.** The unmarked example tests (`uv run pytest examples/tests -q`) are in the main lane and die with this directory; suites needing optional solvers live behind markers and run in [.github/workflows/optional-deps.yml](../.github/workflows/optional-deps.yml). Consequence before you edit a pack: `examples/rulepacks/**` is deliberately absent from that workflow's paths filter, so a pack change that moves the scheduler's committed plan surfaces on the merge to main rather than on your PR. The fix is a date update in `test_the_plan_is_the_committed_demo_output`, in the same spirit as a golden regeneration.
