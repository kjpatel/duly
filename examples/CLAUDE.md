# Working on examples/

Loaded alongside the root CLAUDE.md when work touches the example content.

**This file is deleted by `git rm -r examples/`, and that is correct.** Both
gotchas below are about content that leaves with it. It is also a trap: a
gotcha placed here for tidiness disappears silently when the deletion gate
runs, and the gate reports success. Route to this file only what dies with
`examples/`; anything an adopter still needs after deleting the examples
belongs in the root file or a package's own CLAUDE.md.

- **CP-SAT is nondeterministic by default and lies about why.** It parallelises and randomises, so an optimum can differ between machines: set `num_workers = 1` and `random_seed = 0`, and make the objective's optimum *unique* (a tie lets search order pick the answer). Set `num_workers` **only** — it and the legacy `num_search_workers` are mutually exclusive, and setting both returns `MODEL_INVALID`, which reads exactly like an infeasible problem until you print the status. Treat `MODEL_INVALID`/`UNKNOWN` as a raise, never as "no solution".

- **`examples/tests/` runs in main CI, but the marker-gated example suites do not.** The unmarked example tests (`uv run pytest examples/tests -q`) are in the main lane and die with this directory; suites needing optional solvers live behind markers and run in [.github/workflows/optional-deps.yml](../.github/workflows/optional-deps.yml).

- **The move put the packs *inside* that workflow's paths filter, and the comments describing the old arrangement outlived it.** While the packs sat at the repository root, `rulepacks/**` was genuinely absent from the filter: a pack change that moved the closing scheduler's committed plan surfaced on the merge to `main` rather than on the PR, and both this file and the workflow said so. Under `examples/` they are matched by `examples/**`, which was added for the scheduler example itself — so a pack PR now runs the LinkML, z3 and ortools jobs, and the scheduler test fails on *your* PR, where [rulepacks/README.md](rulepacks/README.md) already said the one-line date fix belongs. Worth keeping as a shape: the path sweep that moved these comments rewrote `rulepacks/**` to `examples/rulepacks/**` inside a sentence claiming it was *absent* from a filter whose line above it reads `examples/**`. A mechanical rename leaves a claim that is now false and still reads correct, and only re-deriving the claim catches it.
