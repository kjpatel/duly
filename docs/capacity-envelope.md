# The reference capacity envelope

What one adjudication costs, and where a pure-Python reference interpreter
stops being the right thing to run.

This answers the last of the [PRD's open questions](guiding-prd.md#open-questions)
— *what capacity envelope should the reference interpreter publish?* — and it
is a v1.0 exit item rather than a nice-to-have, because an adopter sizing a
workload needs a number **before** a deployment exists to produce one.

**Measurement, not optimization.** The PRD's non-goals include "premature
performance optimization that weakens receipt fidelity or semantics", and this
document was written under that rule: every number below is published as
measured, and nothing in the kernel was changed to improve one. Two of the
findings here are unflattering — `adjudicate()` spends roughly half its time
re-validating the pack, and one of the validator's checks is quadratic in the
number of rules concluding a single attribute. Both are published rather than
tuned. A slow honest kernel is a fixable problem; a fast one whose numbers were
obtained by weakening a check is not.

**The timing lives outside the kernel.** No wall clock in library code is an
invariant ([CLAUDE.md](../CLAUDE.md)), so the harness times duly from a caller
the kernel cannot see. Nothing measured here is written to a receipt, a golden
file, or any other replayable artifact: timings are not deterministic and do
not belong in one. They belong here, with the machine and the date attached.

---

## The machine, and how to reproduce this

| | |
|---|---|
| Chip | Apple M1 Max |
| Memory | 32 GiB |
| OS | macOS 26.5.2 (arm64) |
| Python | 3.12.13, CPython |
| duly | 1.1.0 (kernel `duly_kernel` 0.0.1, semantics version `0.0.1`) |
| Corpus | the committed 351-case [golden corpus](../examples/golden/), six rule packs |
| Date | 2026-08-10 |

```bash
uv run python docs/capacity_bench.py                        # all four sections
uv run python docs/capacity_bench.py --only corpus          # one section
uv run python docs/capacity_bench.py --json /tmp/bench.json # raw numbers too
```

[`docs/capacity_bench.py`](capacity_bench.py) is the harness, and it is a
standalone script rather than a package module on purpose: it is the only code
in this repository that times anything (`perf_counter` appears nowhere else),
and it must not become importable from anything that adjudicates — a stopwatch
inside a package is one refactor away from being called by it. It lives beside the document it
substantiates, the way [`spec/validate.py`](../spec/validate.py) lives beside
the contract it checks.

Every timing is the **best of seven** runs of the same input. The minimum is
the estimator, not the mean: what is being measured is the cost of the work,
and everything the scheduler adds to a sample is one-directional noise. The
spread reported across the corpus is then a distribution over duly's own cases
rather than a distribution over machine luck — which matters, because the two
are not the same thing and only one of them is a property of duly.

---

## One adjudication, on the committed corpus

`duly_kernel.api.adjudicate` — validate the pack, evaluate it over the case's
facts, build and seal the receipt — with the pack already parsed and held in
memory, which is what a service does.

| Pack | Rules | Cases | Parse pack (ms) | Validate pack (ms) | Evaluate + seal, p50 | **`adjudicate()` p50** | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `county-recording-us` | 8 | 25 | 10.1 | 0.123 | 0.134 | **0.268** | 0.292 | 0.293 |
| `esign-closing-package` | 10 | 25 | 11.2 | 0.130 | 0.115 | **0.260** | 0.274 | 0.282 |
| `notarization-ron-us-states` | 8 | 25 | 9.0 | 0.086 | 0.093 | **0.191** | 0.207 | 0.212 |
| `termination-notice-us-states` | 9 | 226 | 9.7 | 0.176 | 0.145 | **0.337** | 0.374 | 0.398 |
| `tila-rescission-us-federal` | 8 | 25 | 11.3 | 0.115 | 0.195 | **0.321** | 0.364 | 0.400 |
| `trid-fee-tolerance-us-federal` | 3 | 25 | 3.6 | 0.043 | 0.081 | **0.146** | 0.162 | 0.163 |

All 351 cases together: **p50 0.32 ms, p95 0.37 ms, p99 0.40 ms**, maximum
0.42 ms. Evaluation and receipt-sealing alone, with validation hoisted out:
p50 0.13 ms, p95 0.19 ms.

**The headline an adopter can check against their own volume: about 3,100
adjudications per second per core**, on a pack of three to ten rules with the
pack held in memory. Single-threaded and CPU-bound — the kernel holds no
state between calls, opens no file and takes no lock, so this scales across
processes with nothing to coordinate.

Two readings of the table are worth more than the headline.

**Roughly half of every `adjudicate()` call is re-validating the pack.** The
`validate pack` and `evaluate + seal` columns sum to the `adjudicate()` column
in every row (0.123 + 0.134 = 0.257 against 0.268; 0.176 + 0.145 = 0.321
against 0.337; the remainder is `asOf` parsing). `adjudicate()` calls
`validate_pack` on every invocation by design — a receipt naming a pack is only
meaningful if that pack was valid when it was evaluated, and the API takes a
dict it did not load and cannot know the provenance of. So **"the pack is
loaded once" does not mean "the pack is validated once"**, and there is no
supported way through the public API to make it mean that. An adopter reading
0.32 ms should read it as 0.13 ms of adjudication plus ~0.18 ms of insisting the
rules are well-formed, and should not expect the second half to disappear
under caching.

**The spread across cases is narrow.** p95 is within 20% of p50 in every pack,
and the whole corpus's maximum is 1.3× its median. There is no tail here in the
sense a service operator means by the word: the kernel does no I/O, allocates
no unbounded structure, and takes the same path for every case. The pack a case
names moves its latency more than anything about the case does — the widest
gap in the table is between packs (0.146 to 0.337 ms), not within one.

---

## Load once, or load per call

The `parse pack` column is the whole story of the two deployment shapes, and
it dwarfs every other number in the corpus tables by a factor of thirty.

| | Per adjudication | Adjudications/second/core |
|---|---:|---:|
| Pack parsed once, held in memory (a service) | 0.32 ms | ~3,100 |
| Pack re-read and re-parsed per call (a CLI, a lambda, a worker that reloads) | ~10 ms | ~100 |

Parsing one of these packs out of YAML costs 3.6 ms for the 99-line
`trid-fee-tolerance-us-federal` and 9–11 ms for the other five (258–354 lines);
adjudicating against one costs 0.32 ms. **Reading the pack from disk on every request costs about
thirty times what the decision costs.** This is PyYAML's cost, not the
kernel's — the kernel never sees a file — and it is the single largest lever
an adopter has, without touching anything duly ships. A parsed pack is a plain
dict of 34 KiB (below); hold it.

The same holds one level up, for the facts. Reading a case's facts from disk
and parsing the JSON is 0.089 ms at p50 — around a quarter of the adjudication
itself. A deployment whose facts come from the [store](../store/) rather than
from files pays that cost differently, and this document does not measure it.

---

## The corpus, end to end

`duly-verify` re-adjudicates all 351 committed cases from their committed facts
and packs and byte-compares each recomputed receipt against the one on disk.
It is the closest thing here to a real batch workload, and unlike the numbers
above it includes everything: process start, imports, six pack parses, 351
fact-set reads, 351 receipt reads, and 351 byte comparisons.

```
verified 351 cases in 0.38 s
```

**1.1 ms per case end to end.** Nine timed runs across three sessions ranged
0.38–0.47 s, the whole spread being process start and page cache rather than
anything about the corpus. Of the best run's 0.38 s, roughly 0.11 s is
adjudication, 0.06 s is parsing the six packs, and the rest is process startup
and JSON I/O. Which is the useful way to read it: **on this corpus the
verifier spends about a third of its time deciding and two thirds of it moving
bytes.** A corpus ten times this size would take about ten times as long —
the verifier holds one case at a time and caches packs by path, so it is
linear in cases and flat in memory.

---

## Memory

Two different questions need two different instruments, and conflating them is
how performance documents end up meaningless.

**What does one adjudication cost?** `tracemalloc`, because it measures the
Python allocations made inside the block being traced and nothing else.
`ru_maxrss` cannot answer this: it is a process-wide high-water mark that
includes the interpreter, every imported module and the allocator's slack, so
it would attribute CPython's own footprint to a function call.

| | |
|---|---:|
| Peak traced allocation, one adjudication of the corpus's largest case (`rec-0009`, 6 facts, 8-rule pack) | **16.1 KiB** |
| Retained after it returns (the receipt) | 6.5 KiB |
| A parsed 8-rule pack, resident | 34 KiB |
| Transient peak while PyYAML parses that pack | 362 KiB |

**What must a deployment provision?** `ru_maxrss`, because that is what an
operator's container limit is denominated in.

| | |
|---|---:|
| Whole process: interpreter + `import duly_kernel` + one adjudication | **24 MB** |
| Whole process: `duly-verify` over all 351 cases | **26 MB** |

The gap between those two lines is the finding. Adjudicating 351 cases costs
2 MB more than adjudicating one, so **nothing accumulates across cases** — the
kernel retains nothing between adjudications, and a long-running worker's
memory is its interpreter plus its packs, not a function of how many decisions
it has made. The 24 MB floor is essentially CPython plus PyYAML; duly's own
contribution to it is small enough that it is not worth quoting separately.

---

## Where the curve goes

The corpus's six packs are 3–10 rules and its cases are 2–6 facts, so the
corpus alone cannot say what happens at ten or a hundred times that. The
harness synthesizes the rest: packs of growing rule count and cases of growing
fact count, built in memory from the [fixture pack's](../fixtures/pack.yaml)
shape and committed nowhere. The synthetic rules each bind two variables and
evaluate one comparison — what a real rule costs — with thresholds spread so
about half the guards pass and half fail, so both paths are exercised. They
conclude attributes no decision reads, so the receipt does not grow with the
pack and these curves are pack cost and nothing else.

**Pack shape matters as much as pack size**, which is why there are two rule
curves rather than one. duly's six committed packs run 3–10 rules over 2–3
concluded attributes; the *spread* curve keeps that ratio at eight rules per
attribute, and the *concentrated* curve puts every rule on one attribute.

### Rule count, spread (8 rules per concluded attribute)

| Rules | Validate (ms) | Evaluate (ms) | `adjudicate()` (ms) |
|---:|---:|---:|---:|
| 6 | 0.06 | 0.12 | 0.19 |
| 16 | 0.14 | 0.23 | 0.38 |
| 106 | 0.91 | 1.13 | 2.07 |
| 506 | 4.45 | 5.24 | 9.71 |
| 1,006 | 8.66 | 10.17 | 19.50 |
| 2,006 | 17.83 | 21.08 | 40.80 |

Linear, at about **0.020 ms per rule per adjudication** once the pack is large
enough for the fixed costs to disappear. A 10× rule count is a 10× adjudication
(106 → 1,006 rules moves 2.07 ms → 19.50 ms, a factor of 9.4).

### Rule count, concentrated (every rule concluding the same attribute)

| Rules | Validate (ms) | Evaluate (ms) | `adjudicate()` (ms) |
|---:|---:|---:|---:|
| 6 | 0.06 | 0.11 | 0.19 |
| 106 | 1.02 | 0.90 | 1.95 |
| 506 | 7.09 | 4.06 | 11.57 |
| 1,006 | 20.00 | 7.86 | 28.44 |
| 2,006 | 64.65 | 15.95 | 81.31 |

*Evaluation* stays linear and is in fact slightly cheaper than the spread shape
(0.008 ms/rule against 0.010). **Validation goes quadratic**: doubling 1,006
rules to 2,006 more than triples validation, 20.0 ms → 64.6 ms. The cause is
`_check_priority_ambiguity` in [`duly_kernel/ir.py`](../kernel/duly_kernel/ir.py),
which compares every pair of rules concluding the same attribute to establish
that same-priority pairs can never both apply — an O(n²) check *within an
attribute group*, and therefore free at 8 rules per group and two million
comparisons at 2,006. It is reported, not fixed: the check is what makes an
ambiguous pack a load-time error rather than a mid-adjudication surprise, and
trading it away for a benchmark is exactly the non-goal this document opens
with. The number an adopter needs is the shape rule: **a pack's validation cost
is driven by the largest number of rules concluding any one attribute, not by
its total rule count.**

### Fact count (pack fixed at 6 rules)

Facts the pack never binds — the shape a case has when it carries a whole
document's extraction and the pack reads two attributes out of it.

| Facts | Evaluate (ms) |
|---:|---:|
| 2 | 0.12 |
| 102 | 0.19 |
| 1,002 | 0.97 |
| 2,002 | 1.79 |

Linear, at about **0.001 ms per carried fact** — roughly ten times cheaper per
fact than per rule (0.001 ms against 0.010 ms of evaluation). Facts are filtered for liveness, run through the abstention
policy, grouped for conflict detection and indexed, all in one pass; a fact no
rule reads costs a microsecond and nothing else. A case carrying a thousand
unused facts is not a performance problem.

### Both together

| Rules | Facts | Evaluate (ms) |
|---:|---:|---:|
| 16 | 12 | 0.22 |
| 106 | 102 | 1.16 |
| 506 | 502 | 5.59 |
| 1,006 | 1,002 | 11.58 |

**Additive, with no product term.** 1,006 rules and 1,002 facts costs 11.58 ms,
against 10.17 ms for the rules alone and 0.97 ms for the facts alone. The
engine indexes facts by attribute once and each rule looks up what it binds, so
rules × facts never becomes the cost. This is the one place where a curve is
better news than the prose would have been, and it is worth stating plainly:
growth in the two dimensions an adopter controls does not compound.

---

## Run-to-run variance, and which numbers to trust

The harness was run twice end to end on an otherwise idle machine and the two
runs compared field by field: **10 of 124 measurements moved more than 10%**,
and all ten are in one family. Two further sessions — one of them in a detached
worktree with `examples/` deleted — corroborate everything below.

- **p50 and p95 are stable.** Every median and every 95th percentile in the
  corpus table moved less than 3% between runs, as did every memory figure. The
  one-time `parse pack` and `validate pack` columns are single best-of-seven
  measurements rather than distributions, and a fourth session moved one of
  them (`esign` validation, 0.130 → 0.188 ms) by 45%; read those two columns to
  one significant figure.
- **p99 and the maximum are not measuring duly.** The corpus's p99 was 0.40 ms
  in one run and 0.44 ms in the other; its maximum was 0.42 ms and 1.20 ms.
  Three cases in the second run took 0.66–1.20 ms and had taken 0.33–0.38 ms in
  the first. With best-of-seven per case, an outlier that size means all seven
  runs of that case lost the CPU, which is a fact about the machine. **Quote
  the p50 and the p95; treat the p99 as an upper bound of the form "under half
  a millisecond" and nothing finer.** Per-pack p99 is worse still — at 25 cases
  a pack, the 99th percentile *is* the maximum.
- **The synthetic curves are stable and their shapes reproduce.** One cell
  moved more than 10% between runs (`facts 52`, at 10.1%); every other moved
  less than 9%. A third run, in a detached worktree with `examples/` deleted,
  reproduced both rule curves within 4%. Read the shapes and the per-unit
  rates; do not read a third significant figure off any single cell.

---

## What this does not measure

Everything in this document is the **document → receipt** path with the facts
already in hand. A production adjudication is mostly other things, and most of
them are larger:

- **Extraction.** Running a document AI adapter over a real PDF is seconds, not
  microseconds — three to five orders of magnitude more than the adjudication
  it feeds. Any capacity model for a real workload is an extraction capacity
  model with a rounding error attached. [`extraction/`](../extraction/) is
  where that cost lives, and duly does not ship the model that dominates it.
- **The store.** [`duly_store`](../store/) is SQLite here and Postgres-portable;
  ingesting facts, projecting as-of, and walking supersession chains are all
  I/O and none of them appear above. The corpus reads facts from files.
- **Ontology conformance.** The [conformance gate](../spec/ontology-conformance.md)
  runs at the admission boundary, not inside `adjudicate()`, and is not timed
  here.
- **The demo, the report renderer, and the PDF.** HTTP, template rendering and
  `reportlab` are all outside the kernel and outside these numbers.
- **The solver-backed tools.** [`prove`](../spec/pack-verification.md) and
  [`whatif`](../spec/whatif.md) call z3 and are validation-time tools with
  entirely different cost profiles; nothing here describes them.
- **Concurrency.** Every number is single-threaded. The kernel keeps no state
  across calls and touches no shared resource, so processes scale linearly and
  the GIL is the only reason to prefer processes to threads — but that claim is
  reasoned, not measured, and this document does not measure it.

---

## Where the reference interpreter is the wrong tool

The honest half, and the point of publishing at all. duly's kernel is a
**reference interpreter**: written to be readable, checkable against the spec,
and byte-reproducible forever. It was never written to be fast, and the
following workload shapes are ones where an adopter should expect it not to be.
Each is stated so it can be checked against a real volume rather than felt.

1. **Sustained throughput above a few thousand decisions per second per core.**
   At ~3,100/s/core on a corpus-shaped pack, a workload needing 100,000
   decisions per second needs about 32 cores doing nothing else. That is a
   deployment decision, not a defect — but if the arithmetic is uncomfortable,
   the reference interpreter is the wrong instrument.
2. **Packs in the thousands of rules, and especially thousands of rules on one
   attribute.** 1,000 rules is ~20 ms and ~50 decisions/second/core; 2,000
   concentrated on a single attribute is ~81 ms and ~12/second/core, four
   fifths of it validation. A rulebase that has grown to that size on one
   decision point has outgrown this engine before it has outgrown the IR.
3. **Set-oriented and bulk work.** The kernel adjudicates one case at a time
   and shares nothing between cases: no join across a population, no
   incremental re-evaluation when one fact changes, no query that ranges over
   the corpus. Re-deciding a million cases means a million independent runs
   (~5 minutes of CPU at the corpus's median, which is fine) — but *asking a
   question about* a million cases is not something the kernel can express at
   all, and neither is it a performance problem. It is a missing capability.
4. **Latency budgets under about a millisecond end to end.** With pack parsing
   at ~10 ms, a service that reloads its pack per request cannot get under one;
   with the pack held, 0.32 ms leaves little room for the HTTP, the store read
   and the extraction that surround it.
5. **Repeating structure.** A pack that genuinely needs "for every fee on this
   loan…" cannot be written: quantified bindings are deferred past v1.0
   ([compatibility C5](../spec/compatibility.md)), and the v0 IR is one entity
   per `entityType` per case. This is the case where the reference interpreter
   is the wrong tool for a reason that has nothing to do with speed, and it is
   worth naming next to the ones that do, because "we need a faster engine" is
   how a missing modeling construct usually first presents.

Cases 1–4 are performance. Case 5 is expressiveness. A team should work out
which of the two they have before concluding anything about backends, because a
different execution engine addresses only the first.

## What the alternative would be

The [architecture guide](neuro-symbolic-architecture.md) holds a
**Datalog/Soufflé or ASP execution backend** as a roadmap option, explicitly
gated on "equivalence semantics and a real workload". Half of that gate is now
closed and half is not.

**Equivalence is defined.** Two evaluation backends cannot produce
byte-identical receipts by construction, because `engine.backend` is inside the
hashed body — so byte equality was never available as the test. Agreement is
**digest equality**: two receipts record the same adjudication when
`decision_digest()` matches over the determinant fields, which excludes
everything identifying the run rather than the decision
([compatibility C4](../spec/compatibility.md), with committed
[vectors](../spec/decision-digest-vectors.json)). A second backend would be
accepted by differential testing against the reference kernel over the golden
corpus, digest by digest, and the reference kernel would remain the definition
of what duly means by a decision.

**The demonstrated workload has not appeared, and this measurement is where it
would have.** On the evidence above, nothing duly currently does needs one: the
committed corpus replays in 0.4 seconds, a case decides in a third of a
millisecond, and the two dimensions that grow do not compound. Publishing that
is the outcome — the honest answer to "should duly build a second backend now?"
is *no, and here is the number that says so*, which is worth more than a second
backend built on an intuition. The gate stays where it is: a backend arrives
when an adopter's real volume makes the arithmetic in the list above fail, and
the first three sizing questions to ask them are which of the five shapes they
are in, whether their pack concentrates rules on one attribute, and whether
their problem is speed or expressiveness at all.

For cases 1, 2 and 4, an adopter has cheaper moves than a new engine and should
exhaust them first: hold the parsed pack, run more processes, and split a
rulebase that has concentrated a thousand rules on one attribute into the
several decisions it probably is. For case 3, the answer is not a faster kernel
but a different question shape — the receipts are the queryable artifact, and
[PROV-O export](../spec/prov-o.md) puts them in a graph store where set-oriented
questions belong. For case 5, the answer is [C5](../spec/compatibility.md) and a
future semantics version, not a backend at all.

---

## What this measurement decided

- The published envelope: **~3,100 adjudications/second/core, p50 0.32 ms,
  p95 0.37 ms**, on a 3–10 rule pack held in memory, 24 MB resident.
- **Hold the parsed pack.** Parsing costs 30× what deciding costs, and it is
  the only lever most adopters will need.
- **`adjudicate()` re-validates on every call**, which is about half of it.
  Documented as behaviour rather than removed, because a receipt naming an
  unvalidated pack is not worth the microseconds.
- **Validation is quadratic in rules-per-attribute**, so pack shape and not
  pack size predicts load cost.
- **Rules and facts do not compound**, and unused facts are nearly free.
- **No demonstrated need for a second execution backend**, measured rather than
  asserted — and the equivalence test one would have to pass is already
  defined, so the option stays open at no cost.
