# Closing scheduler — duly as a decision component inside an optimizer

Plan a mortgage closing — **sign → fund → record** — to the earliest feasible dates,
with CP-SAT ([OR-Tools](https://developers.google.com/optimization)) doing the
optimizing and duly doing the deciding.

```bash
uv run examples/closing-scheduler/schedule.py
uv run examples/closing-scheduler/schedule.py --json
uv run examples/closing-scheduler/schedule.py \
    --closing-file examples/closing-scheduler/closing-file-ron.json   # the refusal case
uv run examples/closing-scheduler/schedule.py --no-solve              # duly half only; no solver
```

No `--with` and no extra: `schedule.py` declares `ortools` in its own
[PEP 723](https://peps.python.org/pep-0723/) script metadata, so `uv run` reads
the requirement out of the file it is about to run.

## The principle, which is the entire point

> **duly decides what is *allowed*. The solver decides what is *best*.
> A compliance rule is never re-encoded in the scheduler.**

An optimizer that reimplements "wait three business days after consummation"
alongside the TILA pack has created two sources of truth for one legal
requirement, and they will diverge — not if, when. The first time somebody
learns that 12 CFR § 1026.2(a)(6)'s rescission calendar counts *Saturdays*, one
of the two copies gets fixed.

So the scheduler here is not allowed to know any law. It knows two things:

1. **Tables of days and pairs that `duly_kernel.api.adjudicate` actually
   permitted.** These are the hard constraints, and `probe_windows` is the only
   thing in the file that produces them.
2. **Who is available on which day**, from the `operational` block of the
   closing file. These are the soft, local, synthetic preferences — a notary's
   calendar, a wire desk's hours, a recorder's e-filing window.

There is no third category, and no path from a rule to the model that does not
go through a receipt.

### How a reviewer checks that claim without trusting this README

- **Read `solve()`.** Every `AddAllowedAssignments` takes a table built by
  `probe_windows` out of kernel verdicts. Every other constraint comes from
  `operational_days`, which reads weekday names and a list of unavailable
  dates and nothing else. It is eleven lines.
- **Grep for the law.** There is no business-day walk, no three-day count, no
  per-state RON table, no top-margin threshold, no `§`. Legal concepts appear
  only in comments and in citation strings *copied out of receipts*.
- **Move the rule and watch the plan move.**
  `test_scheduler.py::test_moving_the_rule_moves_the_plan` perturbs the TILA
  pack's `add_business_days(..., 3, ...)` to `5` — touching no line of
  `schedule.py` — and requires the funding date to move. A scheduler carrying
  its own copy of the wait would sail through that test unchanged.
- **Move the staffing and watch only that move.**
  `test_moving_an_operational_input_moves_the_plan_the_other_way` opens the wire
  desk on Saturdays; the compliance floor is untouched and the plan snaps down
  onto it.

## The plan it produces

This is real output, not a sketch (`uv run
examples/closing-scheduler/schedule.py`), trimmed to the shape:

```
closing plan — ESC-7714 — California refinance, in-person notarization, LA County recording
  case             case:closing:ESC-7714-CA
  planning date    2026-02-10  (an input; nothing here reads the clock)
  horizon          2026-02-10 .. 2026-03-11
  status           PLANNED

  sign   2026-02-17  (Tue)   bound by: OPERATIONAL
      ron:ronPermitted = false  @ 2026-02-17
        notarization-ron-us-states@2026.1.0
        receipt urn:duly:receipt:sha256:76c21b06…
      ron:notarizationCompliant = true  @ 2026-02-17
        notarization-ron-us-states@2026.1.0
        receipt urn:duly:receipt:sha256:2bc61c8c…
      earliest allowed 2026-02-10 (compliance)
      pushed later by availability, not by law:
        2026-02-10 … 2026-02-13 marked unavailable; 2026-02-14 Sat, 2026-02-15 Sun, 2026-02-16 unavailable

  fund   2026-02-23  (Mon)   bound by: OPERATIONAL
      resc:fundingPermitted = true  @ 2026-02-23 given signing 2026-02-17
        tila-rescission-us-federal@2026.2.0
        receipt urn:duly:receipt:sha256:4ad11c34…
        rules   RESC-APP-01, RESC-DL-01, RESC-FUND-EXP
      the boundary, kernel-checked from both sides (opens 2026-02-21):
        resc:fundingPermitted = true   @ 2026-02-21   receipt …7c04f010…  RESC-FUND-EXP
        resc:fundingPermitted = false  @ 2026-02-20   receipt …45c21779…  RESC-FUND-STAY
      earliest allowed 2026-02-21 (compliance) — the day the TILA rescission period expires
      pushed later by availability, not by law:
        2026-02-21 is a Sat; funding runs Mon/Tue/Wed/Thu/Fri
        2026-02-22 is a Sun; funding runs Mon/Tue/Wed/Thu/Fri

  record 2026-02-24  (Tue)   bound by: OPERATIONAL
      rec:recordable = true  @ 2026-02-24
        county-recording-us@2026.1.0
        receipt urn:duly:receipt:sha256:62eef3d8…
        rules   REC-DEF-CA, CA-TOPSPACE-25, CA-SB2-75
      earliest allowed 2026-02-23 (sequencing) — the funding date, under the closing file's
        own record-on-or-after-funding policy — an operational choice, not law
      pushed later by availability, not by law:
        2026-02-23 (Mon) is marked unavailable for recording in the closing file

555 kernel runs, 555 distinct receipts, packs: county-recording-us@2026.1.0,
notarization-ron-us-states@2026.1.0, tila-rescission-us-federal@2026.2.0
```

**The funding date is the example in miniature.** The rescission period expires
at midnight on Friday 2026-02-20, so the earliest day money may move is
Saturday 2026-02-21 — Saturdays are business days under the precise
§ 1026.2(a)(6) calendar the pack embeds, which is the rule most schedulers get
wrong. duly says 2026-02-21. The wire desk does not work Saturdays, so the
scheduler says 2026-02-23. Two constraints, two owners, and the plan reports
which one bound the date (`boundBy`). Collapse them into one number and you
still get a date — you just can no longer tell an auditor why.

## The differentiator: the plan cites its receipts

Every date carries the **receipt ids that constrained it** — content-addressed,
replayable, and naming the rules that fired and the authority each rule cites.
That is what no scheduler gives you today: a plan is normally a list of dates
whose justification lives in somebody's head or in a comment.

The funding date goes further and carries a **boundary**: the receipt that
permits 2026-02-21 *and* the receipt that refuses 2026-02-20. An edge is worth
what its refutation is worth — the same posture, and deliberately the same
shape, as a what-if boundary verification ([spec/whatif.md](../../spec/whatif.md), W3).

`--receipts-out DIR` writes every receipt the run produced, so the cited ids
resolve to files an auditor can hash and replay.

## How the permissibility windows are derived, and why that way

Two routes were available. This example **probes by adjudication**: it calls
`duly_kernel.api.adjudicate` across every candidate date (and, for funding,
every `(signing, funding)` pair, because the rescission deadline is computed
*from* the consummation date, so the constraint is a relation and not two
intervals) and reads off where each decision flips. 555 kernel runs, well under
a second.

The alternative was to ask [`whatif`](../../whatif) directly — one backward
query per boundary instead of a sweep, and the TILA earliest-funding question
is exactly the shape it was built for. It was not chosen as the primary path
for one reason: **an example of embedding duly in production should not require
an optional solver to run.** `whatif` is a validation-time analysis tool behind
`z3-solver`; a scheduler in a loan-origination system is not, and an example
that quietly made z3 a production dependency would be teaching the wrong
lesson. The probe route uses only the kernel, which is what an adopter actually
has.

What `whatif` *is* used for is better: **a cross-check.**
`test_the_funding_boundary_agrees_with_what_if` solves the same boundary
backwards through the SMT encoding and asserts it lands on 2026-02-21, the same
date the forward sweep found. Two independent routes — a sweep of kernel runs
and a solve whose every answer is kernel-verified — agreeing on one date, for
the cost of one test and no dependency. It skips cleanly when z3 is absent.

## What the closing file holds, and how honest each part is

[`closing-file.json`](closing-file.json) is entirely **DEMO-SYNTHETIC**: no loan,
notary, recorder office or county calendar named in it exists. Within that, two
different kinds of input, labelled differently on purpose:

| Block | What it is | Who owns the truth |
|---|---|---|
| `known` | Loan and package attributes — transaction type, principal-dwelling status, notarization method, recording state, instrument type, measured first-page top space | The ontology and the packs. Real slots from `duly-mortgage-closing/0.1.0`, real code values; every minted fact passes the conformance gate (there is a test) |
| `signingDateAttributes` | The three § 1026.23(a)(3)(i) triggers, which take the candidate signing date | The example's own modelling assumption, stated in the file: all three happen at the signing table |
| `operational` | Notary availability, wire-desk hours, recorder office days, record-after-funding policy | **The scheduler, and nothing else.** Invented, labelled synthetic in the file, and the only constraints this example writes itself |

The facts are **attestations**, not extractions, and that is load-bearing rather
than convenient: a closing that has not happened yet has no documents to extract
from. "We intend to consummate on the 17th" is a statement a human coordinator
owns, so it is grounded as one (`grounding.kind: "attestation"`,
`assertion.kind: "human"`). Point the same code at extractor-produced facts —
[`examples/starters/`](../starters) has span-grounded facts on exactly these
attributes — and nothing else in `schedule.py` changes.

## The refusal case

[`closing-file-ron.json`](closing-file-ron.json) is the same closing with one
attribute changed: the borrower asks to sign remotely.

```
  status           NO-FEASIBLE-PLAN

  [sign] no candidate date in the horizon has a compliant notarization
      ron:notarizationCompliant = false  @ 2026-02-10
        notarization-ron-us-states@2026.1.0
        receipt urn:duly:receipt:sha256:1bde4d4c…
        rules   RON-DEF-00, RON-COMP-01
```

California's Online Notarization Act is signed law that is not yet operative;
the pack encodes its statutory outside date of 2030-01-01 and fails closed until
then. `schedule.py` knows none of that. It asked the same question it always
asks, got `false` for every candidate day, and reported the receipt.

A scheduler with a hard-coded state RON table would either be wrong about
California or would need maintaining in step with fifty legislatures. This one
is neither, because it does not have the table.

## Determinism

A repo invariant ([CLAUDE.md](../../CLAUDE.md)), and CP-SAT violates it by
default — it parallelises and randomises, so the same model can yield different
optimal solutions on different machines.

- `num_workers = 1`, `random_seed = 0`. (Set `num_workers` **only**: it and the
  legacy alias `num_search_workers` are mutually exclusive, and setting both
  makes CP-SAT return `MODEL_INVALID` — which looks exactly like an infeasible
  closing until you read the status.)
- The objective is a single linear expression, `n²·record + n·fund + sign`,
  whose weights make it a strict lexicographic order. The optimum is therefore
  **unique**, not merely optimal: a tie would let the solver's search order pick
  the answer.
- Every set that reaches the model is `sorted()` first.
- The planning date is an input. Nothing here reads the clock.
- `MODEL_INVALID` / `UNKNOWN` raise rather than being reported as "no feasible
  plan" — a defect must not be able to impersonate an answer.

`test_the_plan_is_byte_identical_across_runs_and_hash_seeds` runs the CLI in
separate subprocesses under `PYTHONHASHSEED` 0, 1 and 42 and compares bytes.

## What this deliberately does not do

- **It does not produce a compliance decision.** It consumes them. Every verdict
  in the output came from a pack; the scheduler's own contribution is arithmetic
  over availability.
- **A plan is a forecast, not a finding.** It is adjudicated over *intended*
  facts — a signing date nobody has signed on yet. When the documents exist, the
  extracted facts are the real inputs and the decision must be **re-adjudicated
  against them**. A plan that said funding is permitted on the 23rd is not
  authority to disburse on the 23rd; the receipt produced on the 23rd, over the
  executed documents, is.
- **It does not execute anything.** No wire is sent, no package is submitted. It
  emits dates and receipt ids for a human or a downstream system to act on.
- **It plans one closing.** No resource contention across a pipeline of loans,
  no notary or wire-desk capacity, no cost model. Those are ordinary CP-SAT
  extensions and none of them touch the compliance boundary — which is the
  point: the interesting scheduling can grow arbitrarily without any of it
  learning a rule.
- **Two of the three gates are go/no-go, not date windows, and this is worth
  saying plainly.** TILA gives a genuine date window that moves with the signing
  date. The RON and recording packs, over a 2026 horizon, answer the same way on
  every day in it — their effective dates (2030 for California RON; 1990/2015/2018
  for the recording rules) fall outside the horizon. So they gate *whether* a
  step may happen, not *when*. That is an honest property of the committed packs
  rather than a limitation of the wiring, and the refusal case above is what it
  looks like when a go/no-go gate binds.
- **It is not a rule pack, a kernel feature, or a supported API.** It is an
  example: copy the directory, replace the closing file, keep the shape.

## Files

| File | What it is |
|---|---|
| [`schedule.py`](schedule.py) | The whole thing. Probe → tables → CP-SAT → audit-linked plan |
| [`closing-file.json`](closing-file.json) | The inputs: known attributes, planned-date attributes, synthetic operational preferences |
| [`closing-file-ron.json`](closing-file-ron.json) | The same closing, notarized remotely — the refusal case (`extends` the first) |
| [`test_scheduler.py`](test_scheduler.py) | The claims above, checked: the plan, the separation, determinism, honest degradation, and the what-if cross-check |

## Dependencies

`ortools` is optional, like `z3-solver` and `docling` — but unlike them it is
declared **here**, not in duly's `pyproject.toml`. There is no
`--extra scheduling`. CP-SAT is a dependency of an *example of embedding duly*,
not of duly, so the declaration lives in the file that needs it and leaves with
`git rm -r examples/`: `schedule.py` opens with a PEP 723 `# /// script` block
naming `ortools>=9.8` (and duly itself, by relative path, because a script with
inline metadata runs in its own environment).

```bash
uv run examples/closing-scheduler/schedule.py                          # metadata resolves ortools
uv run --with ortools pytest examples/closing-scheduler -q -m ortools  # the suite
```

The two lines differ because pytest is not the script: `uv run pytest` runs
*pytest*, which cannot read another file's script metadata, so the suite asks
for ortools explicitly. Its tests carry `@pytest.mark.ortools` and skip without
it, which is what keeps the plain `uv run pytest` lane green.

Without ortools, `schedule.py` prints the install command and exits 2 — never a
traceback — and `--no-solve` still prints the adjudicated windows, because the
duly half of this example has no optional dependency at all.
