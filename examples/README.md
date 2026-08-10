# examples/

Everything an adopter **deletes**: the content duly's examples are made of, and
the reference wiring that consumes it. `git rm -r examples/` must leave a
working, empty toolkit — that claim is the reason this directory exists, and
[`fixtures/`](../fixtures/README.md) is the corpus the toolkit's own suites run
on so deleting this one does not quietly stop testing anything.

## Example content — what a *user* of the toolkit authors

Ours exist to be read, copied, and deleted; an adopting organization replaces
them with its own rules, documents, ontologies and regression corpus.

| Directory | What it holds |
|---|---|
| [`rulepacks/`](rulepacks/README.md) | six rule packs across two domains, each `pack.yaml` + `expected.yaml` — start here to author one |
| [`starters/`](starters/README.md) | synthetic documents, renditions and span-verified facts, one demo scenario per vertical |
| [`golden/`](golden/README.md) | 351 committed cases + receipts: the replay and impact baseline |
| [`ontologies/`](ontologies/README.md) | versioned, immutable LinkML artifacts the facts' `schemaRef`s pin |
| [`dmn/`](../dmn/README.md) | the DMN compiler's teaching inputs: the TRID acceptance table, its committed compilation, and one minimal document per [refusal class](dmn/refusals/README.md) |
| [`tests/`](tests) | the suites whose *subject* is the content above — they move and die with it |

## Reference wiring — duly used from the outside

The rest of the repo shows what duly does. These show what it is like to depend
on it — where the seam between "the kernel decided" and "our software acted"
actually falls, and what an adopter has to write on their side of it.

Every example below holds to the same three rules, and they are the reason
these live separately from `duly_demo/`:

- **It consumes decisions; it never restates them.** If an example needs to know
  a rule, it asks a pack and reads the receipt. A copy of a rule outside
  `examples/rulepacks/` is the defect these examples exist to argue against.
- **Its own inputs are labelled synthetic.** Business calendars, staffing,
  costs and thresholds that are the *adopter's* concern are invented, and say so
  in the file that holds them.
- **It runs, and its output is checked.** Each example has a suite; an example
  that no longer runs teaches an adopter the opposite of what it claims.

Nothing here is imported by the kernel, the packs or the demo, and nothing here
is a supported API. An example is a directory you copy.

| Example | What it demonstrates |
|---|---|
| [`minimal-integration/`](minimal-integration) | the whole contract at its smallest: three facts, three rules, one adjudication, one verified receipt, in about a hundred lines of author-owned code with its own ontology and its own pack. Start here — it is also the only thing in the repository proved to work with duly's source tree *absent*, from an installed wheel in a clean venv |
| [`closing-scheduler/`](closing-scheduler) | duly as a decision component inside an OR-Tools CP-SAT optimizer: the solver picks the earliest feasible sign/fund/record dates, every hard constraint comes from an adjudication, and every chosen date cites the receipt ids that constrained it |

Optional third-party dependencies belong in a `pyproject.toml` extra and a
pytest marker (`scheduling` / `ortools` for the scheduler), with the suite wired
into [`.github/workflows/optional-deps.yml`](../.github/workflows/optional-deps.yml).
The kernel must never grow a dependency because an example wanted one. An
example needing *no* optional dependency gets a plain workflow instead —
[`minimal-integration.yml`](../.github/workflows/minimal-integration.yml) is
the pattern.
