# Minimal integration — duly in about a hundred lines

The smallest thing that is still the whole argument: **three facts, three
rules, one adjudication, one receipt**, in code that belongs to somebody
other than duly.

```bash
python run.py          # needs `pip install duly` (or `uv run --project ../.. python run.py`)
./check_wheel.sh       # the honest version: builds a wheel, installs it clean, runs with no repo present
```

Expected output:

```
case            acme-claim-4471
decision        ex:reimbursable = False
rules fired     EXP-LIMIT-00, EXP-TRAVELCAP-01
rules defeated  EXP-DEFAULT-00
input facts     3 pinned by content hash
receipt         ad89689ce9472750… (hash verified)
```

## What is here

| File | What it is | Whose it is |
|---|---|---|
| [`ontology/acme-expense/1.0.0.yaml`](ontology/acme-expense/1.0.0.yaml) | four terms: what an expense claim has | **yours** — duly ships no domain vocabulary |
| [`expense-policy.pack.yaml`](expense-policy.pack.yaml) | a presumption, an exception, and the limit it measures against | **yours** — cited, versioned, effective-dated |
| [`run.py`](run.py) | the five steps of an integration | **yours** |
| [`check_wheel.sh`](check_wheel.sh) | proof that none of the above needs duly's repository | **yours** |
| `receipt.json` | what came out, written on each run | duly's |

Nothing in this directory imports from a path inside duly. That is the point:
if you can read these four files, you can write the equivalent four for your
own documents without cloning anything.

## The scenario

Acme reimburses employee expenses. The policy is one sentence — *travel
spending over $200 needs prior manager approval* — and claim 4471 is a
$312.40 travel expense with no approval on file, so it is refused.

The interesting part is not the answer. It is that the receipt says
**`EXP-TRAVELCAP-01` defeated `EXP-DEFAULT-00`**: the claim was presumed
reimbursable, and a more specific rule beat the presumption. A rulebase of
independent `if` statements can produce the same boolean and cannot produce
that sentence, which is the reason to reach for a defeasible IR at all.

## The five steps

`run.py` is in the order every integration follows.

1. **Load your ontology.** It lives in your directory and you hand duly a
   registry built from it. duly never looks for it in a location of its own
   choosing — bring-your-own is enforced by the API shape, not by convention.
2. **Admit your facts.** `assert_conformant` holds each fact to the ontology
   version it pins: entity type declared, attribute declared *on that class*,
   value kind matching the slot's range, code values inside the code system.
   A misspelled attribute fails loudly here instead of becoming a rule that
   silently never binds.
3. **Load your rule pack.** `adjudicate` validates it before using it, so a
   malformed pack is a load error rather than a surprise at decision time.
4. **Decide.** You supply the as-of pair; duly never reads the wall clock.
   That is what makes the answer reproducible in five years.
5. **Verify what you were handed.** Recompute the receipt's hash over its own
   canonical bytes. This proves the document is unaltered since sealing — it
   does **not** prove the seal was honest. Only re-running the rules does
   that; see [spec/pack-verification.md](../../spec/pack-verification.md) and
   `python -m duly_assurance verify`.

## Three things worth stealing

**A policy constant is a rule, not a number in a condition.** The $200 limit
is `EXP-LIMIT-00` — its own rule with a citation and an effective date, bound
by the exception through `derived:`. This is partly forced (the expression
grammar has number, string and boolean literals but no *money* literal) and
entirely correct: raising the limit becomes a versioned, cited change that
impact analysis can measure, rather than an edited constant inside a guard.

**Absence is not a span.** No document says "nobody approved this," so
`ex:preApproved` is grounded by *attestation* — naming the system of record
that was asked and when — rather than being forced into a fake document
offset. Provenance stays honest exactly where it is most tempting to fake it.

**Facts are sealed by their content.** `seal()` calls duly's own
`content_hash`; do not reimplement it. The canonical form — sorted keys,
minimal separators, `id` and the hash field excluded — is what every verifier
everywhere recomputes, so a private variant is a fact nobody else can check.

## What this example deliberately does not do

- **No extraction.** The facts are written literally so the file stays
  readable. A real integration builds them from an adapter
  ([extraction/](../../extraction/)); the fact shape is identical either way.
- **No fact store.** Facts go straight to `adjudicate`. A real deployment
  writes them through [`duly_store`](../../store/) and projects with
  `as_of`, which is what makes knowledge-time replay possible — this example
  shows one decision at one instant, so it would gain nothing but noise.
- **No review queue.** Every fact here clears the confidence bar, so nothing
  abstains. The abstain → correct → flip loop is [demo tour
  §9](../../docs/demo_tour.md).
- **No golden corpus.** One case cannot show drift. The corpus is what
  catches a pack whose *meaning* moved; see [golden/](../../golden/).
- **No real policy.** Acme is fictional and so is its expense policy. A real
  pack cites the authority behind each rule or carries `TODO(verify)` naming
  what was not confirmed — [rulepacks/README.md](../../rulepacks/README.md).

## Why `check_wheel.sh` exists

Tests that pass inside duly's repository prove nothing about whether duly can
be *adopted*, because inside the repository every assumption about where
files live happens to be true. `check_wheel.sh` builds a wheel, installs it
into a clean virtualenv, copies this directory somewhere else entirely, and
runs it with duly's source tree off `sys.path`. What survives that is a
toolkit; what does not is a repository with a library-shaped subdirectory.

It also produces the same `receiptSha256` as an in-repo run — determinism
across environments, not just across runs.
