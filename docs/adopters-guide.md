# The adopter's guide

**One end-to-end walkthrough on documents that are yours.** By the end you
will have an invented domain, a scripted extraction adapter, span-verified
facts in a bitemporal store, a receipt, an abstention that a human closed, a
golden corpus of your own, and a labeled calibration pair — none of it inside
duly's repository, none of it requiring a fork or a maintainer.

The bar this guide exists to clear is
[the PRD's](guiding-prd.md#success-measures): *an independent platform
engineer can go from document, adapter, ontology, and rule pack to a
replayable decision and review loop within one working day.* It was written by
doing exactly that, outside the repository, against the published v1.1.0
wheel. Every command and every line of output below is a transcript, not an
illustration.

The worked domain is **Millbrook Public Library**, which is invented, and
whose overdue-fine policy is invented with it. Deliberately: a domain nobody
has to already know keeps the attention on the seams. Yours will be a claims
file, a lab result, a shipping manifest. The shapes are identical.

## What you build

| Step | Artifact | Owner |
|---|---|---|
| 1 | a Python environment with `duly` in it | duly |
| 2–4 | an ontology and a rule pack | **you** |
| 5 | an extraction adapter | **you** |
| 6 | grounded facts, a run envelope, a fact store, a receipt | you produce, duly's contract shapes |
| 7 | a review queue, a human correction, a second receipt | **you** |
| 8 | a golden corpus, replayed and impact-analyzed | **you** |
| 9 | calibration labels | falls out of step 7 |

Nothing in steps 2–9 imports from a path inside duly, and nothing needs duly's
repository present. That is the property the whole thing turns on.

---

## 1. Install

Two ways, and after this section the guide is agnostic about which you chose.

**From the release wheel** — what an adopting team does:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "duly @ https://github.com/kjpatel/duly/releases/download/v1.1.0/duly-1.1.0-py3-none-any.whl"
```

**From a clone** — what you do if you also want the six example packs, the
351-case corpus, and the demo's teaching content on disk:

```bash
git clone https://github.com/kjpatel/duly && cd duly && uv sync
```

A bare install is **seven packages**:

```
attrs  duly  jsonschema  jsonschema-specifications  pyyaml  referencing  rpds-py
```

`pyyaml` because a rule pack is YAML; `jsonschema` because the review queue
validates a correction against the grounded-fact contract before it will
accept it, and enforcing a compatibility rule is not optional behaviour.
Everything else is an extra: `demo` (FastAPI + uvicorn, for the four demo
pages and the review API), `report` (reportlab, for the PDF audit report),
`prove` (z3, for the static verifier and what-if), `extraction` (Docling).

Every step in this guide runs on that seven-package install, and §§5–9 below
were executed against exactly it — checked, not assumed. Three blocks need
more, and say so where they appear: the two `prove` ones (§4's verifier, §8's
what-if) and the demo in §10. An extra *extends* the same venv —
`pip install 'duly[prove]'` adds z3 beside the seven and takes nothing away —
so you never need a second environment.

**The invocation surface.** Five console scripts exist; everything else is
`python -m`:

| Command | What it does |
|---|---|
| `duly-verify` | replay a golden corpus and byte-compare receipts |
| `duly-impact` | what your pack change moves against the corpus |
| `duly-conformance` | hold facts to the ontology version they pin |
| `duly-dmn` | compile a DMN decision table into a rule pack |
| `duly-whatif` | free one input and solve the pack for it (needs `prove`) |
| `python -m duly_kernel` | adjudicate one case from the command line |
| `python -m duly_store` | init / ingest / query / history against a fact store |
| `python -m duly_review` | init / items / pairs / golden against a queue |
| `python -m duly_assurance prove` | static pack verification (needs `prove`) |

---

## The five steps this guide starts after

[`examples/minimal-integration`](../examples/minimal-integration/) is about a
hundred lines doing the first half of this, and every integration follows the
same order:

1. **Load your ontology.** It lives in your directory; duly resolves it from
   the registry you hand it, never from a path of its own choosing (§3).
2. **Admit your facts.** The conformance gate holds each one to the ontology
   version it pins (§5).
3. **Load your rule pack.** `adjudicate` validates it, so a malformed pack is
   a load error rather than a surprise at decision time (§4).
4. **Decide.** You supply the as-of pair; duly never reads the wall clock (§6).
5. **Verify what you were handed.** Recompute the receipt's hash over its own
   canonical bytes (§6).

The rest of this document is **everything around them**: a real adapter
reading a real document, the store, the abstention arc, the corpus, the labels.

*If you cloned the repository* (§1's second install path above), read the code
before continuing — it is the shortest complete example there is:

```bash
cd examples/minimal-integration && python run.py
```

Wheel-only adopters have no checkout and need nothing from it; the five steps
above are the whole of what it teaches, and §§3–6 build them again on your own
documents.

---

## 2. The domain, and the shape of a project

Millbrook lends books. An item comes back with a return slip; the library
waives the overdue fine if the item came back inside a grace period, **unless**
it came back damaged, which is charged separately.

Four rules: a default, a policy constant, an exception that defeats the
default, and an exception that defeats *that*. Close to the smallest thing
that is still a defeasible rulebase — plus the one wrinkle that makes
abstention matter, which is that the condition of a returned item is the fact
a scanner is least sure about.

```
millbrook/
  ontologies/millbrook-lending/1.0.0.yaml        § 3    yours
  rulepacks/millbrook-overdue-waiver/pack.yaml   § 4    yours
  rulepacks/millbrook-overdue-waiver/expected.yaml § 4  yours
  documents/return-slip-8842.txt                 § 5    yours
  targets/return-slip-8842.json                  § 5    yours
  slip_adapter.py                                § 5    yours
  extract.py  decide.py  review.py               § 5–7  yours
  check_expected.py  make_corpus.py  calibrate.py § 4,8,9 yours
  runs/8842-1/{rendition.txt,envelope.json,facts/} § 5  produced
  golden/cases/  golden/receipts/                § 7–8  produced
  millbrook.db  review.db                        § 6–7  produced
```

One layout choice is load-bearing: **the content root is flat.**
`rulepacks/`, `golden/`, `ontologies/`, `starters/`, `dmn/` sit directly under
one root. duly's own copies live under `examples/` because an adopter is meant
to delete that directory; nobody adopting duly should mirror that nesting.

Within it, name things however you like. A receipt pins its pack by *name and
version* and never by location, and everything that resolves a receipt back to
a pack reads the declared name out of each `pack.yaml` rather than trusting a
path — so `rulepacks/overdue-waiver/` holding a pack named
`millbrook-overdue-waiver` is fine. Matching them anyway is a kindness to
whoever greps.

---

## 3. Your ontology

duly ships no domain vocabulary. Your ontology is a LinkML file in your
directory, loaded from a registry you hand the toolkit — bring-your-own is
enforced by the API shape, not by convention. The exact subset duly's gate
interprets is [spec/ontology-conformance.md](../spec/ontology-conformance.md);
everything else in the file is documentation the gate ignores.

`ontologies/millbrook-lending/1.0.0.yaml`, abridged to the two parts that do
work:

```yaml
id: https://millbrook.example/ontologies/millbrook-lending/1.0.0
name: millbrook-lending
version: 1.0.0

prefixes:
  linkml: https://w3id.org/linkml/
  duly: https://duly.dev/spec/v0/vocab#
  lib: https://millbrook.example/ontologies/millbrook-lending/lib#
  mbl: https://millbrook.example/ontologies/millbrook-lending/
default_prefix: mbl
imports: [linkml:types]

enums:
  ItemCondition:
    description: >-
      A CLOSED code set: the desk has three boxes to tick, so an unlisted
      value is a contract failure rather than a rule that silently never binds.
    annotations:
      codeSystem: millbrook-lending/conditions
    permissible_values:
      Good: { description: Returned in lendable condition. }
      WaterDamaged: { description: Water damage to cover or pages. }
      PagesMissing: { description: One or more pages torn out or missing. }

classes:
  Loan:
    class_uri: lib:Loan
    attributes:
      dueDate:      { slot_uri: lib:dueDate,      range: date }
      returnedDate: { slot_uri: lib:returnedDate, range: date }
      condition:    { slot_uri: lib:condition,    range: ItemCondition }
      graceDays:
        slot_uri: lib:graceDays
        range: decimal
        description: DERIVED — concluded by the pack, never extracted.
        annotations: { derived: true }
      fineWaived:
        slot_uri: lib:fineWaived
        range: boolean
        description: DERIVED — concluded by the pack, never extracted.
        annotations: { derived: true }
```

Ranges map onto duly value kinds: `string`, `decimal`, `date`, `datetime`,
`boolean` directly; an enum range means `code`; a schema-local type whose
`uri` is `duly:money` or `duly:entityRef` means those. Anything else is a load
error.

**A committed version is immutable.** A fact's `schemaRef` names an ontology
*and a version*, and that pair is inside the fact's content hash — so
re-pointing facts at a renamed or edited ontology changes every fact hash,
every receipt's `inputFacts`, and therefore every committed receipt. New terms
go in a new version file. Facts pin the new version; old facts keep validating
against the old one forever.

The registry is a directory of `<name>/<version>.yaml`, and you can look at
what duly read:

```console
$ duly-conformance --ontologies ontologies list
millbrook-lending@1.0.0  (prefixes: duly, lib, linkml, mbl)
  lib:Loan
    lib:condition: code  [millbrook-lending/conditions: 3 values]
    lib:dueDate: date
    lib:fineWaived: boolean
    lib:graceDays: decimal
    lib:returnedDate: date
```

`--ontologies` has no default, deliberately: your ontologies are yours and
duly does not know where you keep them. `DULY_ONTOLOGIES` works too.

---

## 4. Your rule pack

Read [examples/rulepacks/README.md](../examples/rulepacks/README.md) before
authoring in anger — it is the pack-authoring contract and this section does
not replace it. If your pack is one another duly user could use — a
jurisdiction, a program, a published standard — that README's **"Contributing
it back"** section is the upstreaming path: the checks your PR triggers, the
ordered pre-PR checklist, and the list of what maintainers will not wire for
you. What follows is the smallest pack that exercises the three
things you will actually need: a default, an exception that defeats it, an
exception that defeats *that*, and a policy constant.

`rulepacks/millbrook-overdue-waiver/pack.yaml`:

```yaml
pack:
  name: millbrook-overdue-waiver
  version: "2026.1.0"
  idPrefix: MPL
  ontology: millbrook-lending
  ontologyVersion: "1.0.0"
  description: Whether Millbrook waives the overdue fine on a returned loan.

# Machine-asserted facts scoring below the floor are excluded from binding and
# recorded as abstentions on the receipt. The floor is PACK data, so it is
# inside `rulePack.version` on every receipt and replays forever; it is not
# engine configuration.
abstentionPolicy:
  minConfidence: 0.75
  routeTo: circulation-review

decisions:
  - attribute: lib:fineWaived
    entityType: lib:Loan
    question: "Is the overdue fine on this loan waived?"
    phrasing:
      - when: { value: true, abstained: lowConfidence }
        verdict: "Waived"
        detail: "{caveat}"
        tone: warn
      - when: { value: true }
        verdict: "Waived"
        detail: "Returned inside the grace period, undamaged"
        tone: pos
      - when: { value: false }
        verdict: "Fine stands"
        detail: "See the rules fired"
        tone: neg

  - attribute: lib:graceDays
    entityType: lib:Loan
    question: "How many days past due does the library forgive?"
    phrasing:
      - verdict: "{value} days"
        detail: "Grace period in force on the evaluation date"

rules:
  # The presumption. Priority 0 means anything else concluding lib:fineWaived
  # beats it — which is how a default is written in this IR.
  - id: MPL-DEFAULT-00
    description: "An overdue fine stands unless a rule waives it."
    version: "1.0.0"
    priority: 0
    citation: { text: "Millbrook Circulation Policy §1 — fines are owed as assessed" }
    effectiveFrom: "2026-01-01"
    given:
      loan: { entityType: lib:Loan }
    then:
      entity: loan
      attribute: lib:fineWaived
      value: { kind: boolean, value: false }

  # The policy constant, as a rule rather than as a number inside a guard.
  - id: MPL-GRACEDAYS-00
    description: "Millbrook forgives returns up to seven days past due."
    version: "1.0.0"
    priority: 0
    citation: { text: "Millbrook Circulation Policy §4.1 — grace period" }
    effectiveFrom: "2026-01-01"
    given:
      loan: { entityType: lib:Loan }
    then:
      entity: loan
      attribute: lib:graceDays
      value: { kind: decimal, value: "7" }

  - id: MPL-WAIVE-01
    description: "A loan returned within the grace period has its fine waived."
    version: "1.0.0"
    priority: 100
    citation: { text: "Millbrook Circulation Policy §4.1 — grace period" }
    effectiveFrom: "2026-01-01"
    given:
      loan:  { entityType: lib:Loan }
      due:   { attribute: lib:dueDate }
      back:  { attribute: lib:returnedDate }
      grace: { derived: lib:graceDays }
    when:
      - days_between(due, back) <= grace
    then:
      entity: loan
      attribute: lib:fineWaived
      value: { kind: boolean, value: true }
    overrides: [MPL-DEFAULT-00]

  # The exception to the exception. Its `cond` binding is the one fact on a
  # return slip a scanner is least sure about — which is why §7 exists.
  - id: MPL-DAMAGE-01
    description: "A damaged item is not covered by the grace-period waiver."
    version: "1.0.0"
    priority: 200
    citation: { text: "Millbrook Circulation Policy §6.2 — damage is charged separately" }
    effectiveFrom: "2026-01-01"
    given:
      loan: { entityType: lib:Loan }
      cond: { attribute: lib:condition }
    when:
      - cond != "Good"
    then:
      entity: loan
      attribute: lib:fineWaived
      value: { kind: boolean, value: false }
    overrides: [MPL-WAIVE-01]
```

### A threshold is a rule, not a number in a guard

`MPL-GRACEDAYS-00` concludes the number seven, and `MPL-WAIVE-01` binds it
with `derived:` instead of writing `<= 7`. Nothing forces this for a
decimal — `days_between(due, back) <= 7` parses fine. Write it this way
anyway, and understand why before you write your own pack:

- The threshold **carries its own citation**, so a reader can check the number
  against its authority without reading the rule that uses it.
- It is **independently effective-dated**. When the grace period rises to ten
  days, you add one rule with a new `effectiveFrom` and `MPL-WAIVE-01` never
  changes. Written inline, you would clone the whole exception and close the
  old one's window.
- It **appears in the receipt's derivation**, so whoever reads the decision
  sees which grace period applied without opening the pack.

For money the idiom is not optional: there is no money literal in the
expression grammar, because money is an amount *and* a currency and a bare
number is only the first. Full argument:
[spec/rule-ir.md](../spec/rule-ir.md#a-threshold-is-a-rule-not-a-number-in-a-guard).

### What the pack validator will refuse

`adjudicate` validates the pack before using it, so a malformed pack is a
load error and not a surprise at decision time. Writing this one, the first
run produced:

```
duly_kernel.ir.PackValidationError: decisions[1] (lib:graceDays):
phrasing[0].verdict: placeholder {decimal} is not a known placeholder.
Known placeholders: {value}, {money}, {caveat}, {fact:<attribute>},
{derived:<attribute>}, {daysBetween:<from>,<to>}; formats: |day, |int
```

Three more it enforces, in rough order of how often they bite:

- **Same-priority rules concluding one attribute must be provably disjoint**,
  or the pack will not load. The proofs it accepts are narrow: disjoint
  effective windows, contradictory *quoted-string* equality guards, or an
  explicit `overrides`. Boolean guards do not count; guards on `derived`
  bindings do not count.
- **Rule ids are permanent and conventional.** `<PREFIX>-<TOPIC>[-NN]`, no
  digits outside the trailing two, no tail echoing a number in the rule's own
  body. The checks run only if you declare `pack.idPrefix` — declaring one is
  the opt-in, and a team porting a rulebase whose ids are already in their own
  receipts can leave it off.
- **Phrasing is pack data, and every renderer reads it.** Verdict wording
  belongs with the rules, never in a UI. `duly_kernel.phrasing` is the one
  implementation; the demo's answer line and the Markdown/PDF audit report are
  two callers of it, so `MPL-WAIVE-01` firing produces **Waived** in the demo
  and `**Verdict:** Waived` in the report, from the same block. Strip the
  block and the same report reads `**Verdict:** fineWaived: yes` — the
  fallback names the attribute back at you, per medium, which is honest and
  useless. Write the block. It never enters a hashed body: `mpl-0007`'s
  receipt is the same bytes either way.

  **Check your coverage by calling the renderer**, rather than by reading the
  pack and hoping. `determination` is the whole selection, and it returns
  `None` when no case applies — which is precisely the state that produces the
  flat fallback:

  ```pycon
  >>> from duly_kernel.phrasing import determination
  >>> determination(receipt, facts, pack)          # the §6 abstained receipt
  {'verdict': 'Waived',
   'detail': 'Presumption only — condition excluded at confidence 0.6, below the 0.75 floor',
   'tone': 'warn'}
  >>> determination(after, after_facts, pack)      # §7, post-correction
  {'verdict': 'Fine stands', 'detail': 'See the rules fired', 'tone': 'neg'}
  ```

  That first `detail` is Millbrook's `{caveat}` placeholder resolved against
  the receipt's own abstention entry — the `when: {value: true, abstained:
  lowConfidence}` case earning its keep. Run this over every decision value
  your pack can produce, abstained variants included; anything returning `None`
  is a sentence nobody wrote.

With the `prove` extra installed (`pip install 'duly[prove]'`, which adds z3 to
the same venv), the static verifier answers what the validator cannot —
whether two rules *genuinely* overlap, and which input regions your pack
leaves undecided:

```console
$ python -m duly_assurance prove --ontologies ontologies \
      rulepacks/millbrook-overdue-waiver/pack.yaml
pack millbrook-overdue-waiver 2026.1.0  (ontology millbrook-lending@1.0.0)
  source: rulepacks/millbrook-overdue-waiver/pack.yaml

  rules: 4
    every rule is reachable: some input makes it fire

  same-priority pairs concluding one attribute: none

  coverage of the pack's decision attributes:
    UNCOVERED    lib:fineWaived
      the only uncovered region is an evaluation point outside every concluding rule's effective window
      witness:
        asOf.effective             2025-12-31
        lib:condition              "Good"
        lib:dueDate                2025-12-31
        lib:returnedDate           2025-12-31
        lib:graceDays (concluded)  (no conclusion)
    UNCOVERED    lib:graceDays
      the only uncovered region is an evaluation point outside every concluding rule's effective window
      witness:
        asOf.effective  2025-12-31

1 pack(s): 0 pair(s) PROVED-DISJOINT, 0 NOT-PROVED, 0 OUT-OF-FRAGMENT; 2 uncovered decision attribute(s).
```

The only gap it found is "before 2026-01-01, this pack decides nothing",
which is correct. Read [spec/pack-verification.md](../spec/pack-verification.md)
for what a green run does and does not license.

### `expected.yaml`, and the harness you have to write

A pack declares its own outcomes beside it, covering every rule, every defeat
chain, and both sides of each boundary. `factsFrom` points at any fact
directory under your content root — a `fixtures/` directory beside the pack,
or, as here, §8's corpus cases.

**Order of work.** That choice makes this section depend on a later one:
Millbrook's four cases read `golden/cases/…`, so `check_expected.py` runs
*after* `make_corpus.py`. Write the expectations now, run them at the end of
§8. (Point `factsFrom` at a hand-built `rulepacks/<pack>/fixtures/<case>/facts`
directory instead and the dependency disappears — worth doing if you want the
harness green before a corpus exists.)

Two of Millbrook's four cases:

```yaml
cases:
  - name: inside-grace-undamaged-waived
    factsFrom: golden/cases/mpl-0007/facts     # 7 days late, the boundary itself
    asOfEffective: "2026-04-11"
    question: lib:fineWaived
    expectDecision: { kind: boolean, value: true }
    expectRulesFired: [MPL-GRACEDAYS-00, MPL-WAIVE-01]
    expectDefeated:
      MPL-WAIVE-01: [MPL-DEFAULT-00]

  - name: damaged-inside-grace-fine-stands
    factsFrom: golden/cases/mpl-0008/facts     # damage beats the waiver
    asOfEffective: "2026-04-11"
    question: lib:fineWaived
    expectDecision: { kind: boolean, value: false }
    expectRulesFired: [MPL-DAMAGE-01, MPL-GRACEDAYS-00]
    expectDefeated:
      MPL-DAMAGE-01: [MPL-WAIVE-01]

  # The other two, elided: `one-day-past-grace-fine-stands` (mpl-0009, the
  # far side of the boundary) and `grace-period-in-force` (the same facts
  # asked of lib:graceDays).
```

**Nothing in duly runs this file for you.** The rule studio's Verify rail
reads it, which is a browser and not CI; the only automated runner in the
repository lives under `examples/tests/` and is deleted along with the
examples. Yours is twenty lines and needs no test framework:

```python
for spec_path in sorted((HERE / "rulepacks").glob("*/expected.yaml")):
    pack = yaml.safe_load((spec_path.parent / "pack.yaml").read_text())
    spec = yaml.safe_load(spec_path.read_text())
    # Assert the glob is non-empty BEFORE using it. A loop whose body never
    # runs reports success, which is the loudest-looking way to test nothing.
    assert spec["cases"], f"{spec_path} declares no cases"
    for case in spec["cases"]:
        facts = [json.loads(p.read_text())
                 for p in sorted((HERE / case["factsFrom"]).glob("*.json"))]
        assert facts, f"no facts in {case['factsFrom']}"
        receipt = adjudicate(facts, pack, case["asOfEffective"],
                             case["asOfEffective"] + "T23:59:59Z", case["question"])
        # ... compare decision, sorted rulesFired, and the defeated map
```

```console
$ python check_expected.py
ok   inside-grace-undamaged-waived
ok   one-day-past-grace-fine-stands
ok   damaged-inside-grace-fine-stands
ok   grace-period-in-force

1 pack(s), 0 failure(s)
```

Cut the grace period to three days without touching the expectations and it
says so, which is the point:

```console
FAIL inside-grace-undamaged-waived: decision {'kind': 'boolean', 'value': False};
     fired ['MPL-DEFAULT-00', 'MPL-GRACEDAYS-00']; defeated {}
ok   one-day-past-grace-fine-stands
FAIL damaged-inside-grace-fine-stands: defeated {'MPL-DAMAGE-01': ['MPL-DEFAULT-00']}
FAIL grace-period-in-force: decision {'kind': 'decimal', 'value': '3'};
     fired ['MPL-DEFAULT-00', 'MPL-GRACEDAYS-00']; defeated {}
```

Two things that catch people writing their first expectations. `rulesFired` is
the **whole run**, not the rules concluding your question: evaluation runs the
pack to a fixpoint, so asking `lib:graceDays` of the same facts changes the
`decision` and not the firing set. And the harness cannot assert the
`abstentions` list or a no-decision outcome — pin those with golden cases
instead, which is what §7's `review-0001` is for.

---

## 5. Your extraction adapter

This is the edge where document-AI practitioners contribute, and the protocol
is three things wide. An adapter is a `name`, a `version`, and one
`extract(document, targets)` call returning:

1. a **rendition** — the immutable extracted text that spans index into,
   content-addressed by the SHA-256 of its UTF-8 bytes and tied to the SHA-256
   of the source bytes;
2. **facts** whose `charSpan` is a code-point range into *that* rendition and
   whose `quote` equals `rendition.text[start:end]` exactly;
3. an **envelope** — the manifest naming the run, the adapter, the document,
   the rendition, and every fact id the run proposed, so a whole run can be
   verified or revoked at once.

Spans point at a *rendition*, never at the PDF, because two converters produce
two different texts from identical bytes and old spans must keep resolving.

### The document

`documents/return-slip-8842.txt` — Millbrook's slips are plain text, which
keeps the guide legible. Note the word `water-damaged` appearing twice; that
is deliberate and §7 turns on it.

```
MILLBROOK PUBLIC LIBRARY
Item return slip — desk copy

Loan            L-8842
Item            barcode 31234005678901
Due date        2026-04-03
Returned        2026-04-07

Condition on return (circle one):  good  /  water-damaged  /  pages missing

Desk note       after-hours drop box; cover water-damaged, borrower has not
                asked about a replacement.

Clerk           j.okafor
```

### The targets

Both shipped adapters need to be told *which* attributes to look for:
document conversion gives you text, not an ontology. That fact-proposal seam
is the `targets` dict. A model-driven proposer — an LLM deciding what to
assert — replaces this file with generated proposals; the rendition, span
verification, fact shape and envelope stay exactly as they are.

`targets/return-slip-8842.json`:

```json
{
  "documentId": "millbrook:slip:8842",
  "caseId": "millbrook-loan-8842",
  "assertedAt": "2026-04-08T08:30:00Z",
  "runId": "millbrook:run:8842:1",
  "schemaRef": { "ontology": "millbrook-lending", "version": "1.0.0" },
  "facts": [
    { "entity": { "id": "loan:L-8842", "type": "lib:Loan" },
      "attribute": "lib:dueDate",
      "value": { "kind": "date", "value": "2026-04-03" },
      "quote": "2026-04-03" },
    { "entity": { "id": "loan:L-8842", "type": "lib:Loan" },
      "attribute": "lib:returnedDate",
      "value": { "kind": "date", "value": "2026-04-07" },
      "quote": "2026-04-07" },
    { "entity": { "id": "loan:L-8842", "type": "lib:Loan" },
      "attribute": "lib:condition",
      "value": { "kind": "code", "value": "WaterDamaged",
                 "codeSystem": "millbrook-lending/conditions" },
      "quote": "water-damaged" }
  ]
}
```

### The adapter

`slip_adapter.py`:

```python
"""Millbrook's extraction adapter: one return slip in, grounded facts out."""

from __future__ import annotations

from duly_extraction import (
    ExtractionResult, Rendition, SkippedTarget, SourceDocument,
    build_envelope, build_fact, locate_quote, match_confidence,
    verify_fact_span,
)

NAME = "millbrook-slip-reader"
VERSION = "1.0.0"


class SlipAdapter:
    """Quote-target extraction over a plain-text return slip."""

    name = NAME
    version = VERSION

    def extract(self, document: SourceDocument, targets: dict) -> ExtractionResult:
        if document.data is None:
            raise ValueError("SlipAdapter reads the document bytes; pass them in")

        # 1. The rendition. `id` is yours to choose but must be stable and
        #    unique per (converter, document) — spans mean nothing without it.
        #    Swap this one `decode` for Docling, Textract, an LLM or your own
        #    OCR and nothing downstream changes.
        rendition = Rendition(
            id=f"rend:{NAME}:{VERSION}:{document.sha256[:8]}",
            extractor=NAME,
            extractor_version=VERSION,
            document_sha256=document.sha256,
            text=document.data.decode("utf-8"),
        )

        asserted_at = targets["assertedAt"]
        run_id = targets["runId"]
        extractor = {"name": NAME, "version": VERSION, "runId": run_id}

        facts: list[dict] = []
        skipped: list[SkippedTarget] = []
        for target in targets["facts"]:
            match = locate_quote(rendition.text, target["quote"], allow_normalized=True)
            if match is None:
                # A target the adapter could not ground is REPORTED, never
                # dropped: a fact list shorter than the target list must say
                # which target went missing and why.
                skipped.append(
                    SkippedTarget(target["attribute"], target["quote"], "quote not in rendition")
                )
                continue

            # Confidence is MEASURED, not scripted. `match_confidence` is an
            # honest heuristic proxy for match quality — exact and unique 0.90,
            # exact but ambiguous 0.60, whitespace-normalized 0.70/0.50 — and
            # it says so by emitting `method: "raw"`. A calibrated probability
            # is a different claim, made downstream by duly_calibration.
            fact = build_fact(
                target,
                document=document,
                rendition=rendition,
                span=(match.start, match.end),
                # Re-read the slice rather than echoing the target's quote: a
                # whitespace-normalized match is a *different string*, and the
                # fact must carry what the rendition actually says.
                quote=rendition.text[match.start:match.end],
                confidence=match_confidence(match),
                case_id=targets["caseId"],
                schema_ref=targets["schemaRef"],
                asserted_at=asserted_at,
                extractor=extractor,
                page=targets.get("page", 1),
            )
            # 2. The acceptance test. Run it on every emission, not in a test
            #    suite: a fact whose span does not resolve is unfalsifiable
            #    evidence, which is worse than no evidence.
            verify_fact_span(fact, rendition.text)
            facts.append(fact)

        # 3. The manifest. `factIds` is ordered and complete — exactly what
        #    this run proposed, in emission order.
        envelope = build_envelope(
            run_id=run_id,
            adapter={"name": NAME, "version": VERSION},
            document_id=document.document_id,
            document_sha256=document.sha256,
            rendition_id=rendition.id,
            rendition_sha256=rendition.sha256,
            created_at=asserted_at,
            fact_ids=[f["id"] for f in facts],
        )
        return ExtractionResult(
            rendition=rendition, facts=facts, envelope=envelope, skipped=skipped
        )
```

### Running it

`extract.py` writes the run to disk and ingests nothing — extraction
*proposes*, and the store is a separate decision:

```python
from duly_extraction import SourceDocument
from slip_adapter import SlipAdapter

RUN_DIR = HERE / "runs" / "8842-1"        # one directory per extraction run

targets = json.loads((HERE / "targets/return-slip-8842.json").read_text())
document = SourceDocument.from_bytes(
    targets["documentId"], (HERE / "documents/return-slip-8842.txt").read_bytes()
)
result = SlipAdapter().extract(document, targets)
# ... write result.rendition.text and result.envelope into RUN_DIR, and one
#     file per fact into RUN_DIR / "facts"
```

**Filenames.** Inside a run directory they are yours — Millbrook uses the
attribute's local name (`condition.json`), and nothing reads them back by
name. The **corpus** layout in §8 is different and does have a convention:
one file per fact named for the attribute with `:` replaced by `-`
(`lib-condition.json`), because a CURIE is not a portable filename. Both the
review freezer and `make_corpus.py` follow it, and the freezer refuses a case
whose facts would collide on those names — which is the one-live-fact-per-
attribute rule showing up as a filesystem constraint.

```console
$ python extract.py
document   millbrook:slip:8842  sha256 0ad966b437af…
rendition  rend:millbrook-slip-reader:1.0.0:0ad966b4  sha256 0ad966b437af…
run        millbrook:run:8842:1  (3 facts proposed)
  lib:dueDate        conf 0.90 [133,143) '2026-04-03'
  lib:returnedDate   conf 0.90 [160,170) '2026-04-07'
  lib:condition      conf 0.60 [216,229) 'water-damaged'
```

Two things in that output are the whole section.

**The rendition hash equals the document hash**, because this converter is a
`decode`. With a PDF they differ, and they must: the rendition is one
extractor's reading of the bytes, versioned separately so a converter upgrade
mints a new rendition and leaves every old span resolving.

**The condition fact scored 0.60, and nothing scripted it.** `water-damaged`
appears twice on the slip, so `locate_quote` found the first occurrence and
reported that it was ambiguous, and `match_confidence` turned that into 0.60.
The adapter is telling you it cannot prove which occurrence the target meant.
Hold that thought until §7.

Here is what came out — one entity-attribute-value assertion carrying where it
came from, who asserted it, how confident they were, and when it was recorded,
sealed by the SHA-256 of its own canonical bytes:

```json
{
  "id": "urn:duly:fact:sha256:a094e5630c91b69f0f81aef898df2c13ae43d789251113c3aff0e21f566db0be",
  "contentHash": "a094e5630c91b69f0f81aef898df2c13ae43d789251113c3aff0e21f566db0be",
  "caseId": "millbrook-loan-8842",
  "entity": { "id": "loan:L-8842", "type": "lib:Loan" },
  "attribute": "lib:condition",
  "value": { "kind": "code", "value": "WaterDamaged",
             "codeSystem": "millbrook-lending/conditions" },
  "grounding": {
    "kind": "document",
    "documentId": "millbrook:slip:8842",
    "documentSha256": "0ad966b437af9243940faca47151255068db9372e6f595d273ee416364183f3c",
    "rendition": { "id": "rend:millbrook-slip-reader:1.0.0:0ad966b4",
                   "extractor": "millbrook-slip-reader", "extractorVersion": "1.0.0" },
    "page": 1,
    "charSpan": { "start": 216, "end": 229 },
    "quote": "water-damaged"
  },
  "assertion": { "kind": "machine", "at": "2026-04-08T08:30:00Z",
                 "extractor": { "name": "millbrook-slip-reader", "version": "1.0.0",
                                "runId": "millbrook:run:8842:1" } },
  "confidence": { "score": 0.6, "method": "raw" },
  "recordedAt": "2026-04-08T08:30:00Z",
  "status": "asserted",
  "schemaRef": { "ontology": "millbrook-lending", "version": "1.0.0" }
}
```

The hash covers everything except `id` and `contentHash` itself, over the
canonical form — sorted keys, minimal separators, non-ASCII unescaped. Use
duly's `seal_fact`/`content_hash` and never a private variant: a fact hashed
your own way is a fact nobody else can check.

Finally, hold the facts to your ontology before anything else sees them:

```console
$ duly-conformance --ontologies ontologies check runs/8842-1/facts
All 3 fact(s) conform (millbrook-lending@1.0.0).
```

It is worth seeing what a failure looks like, because it is the difference
between a loud contract error and a rule that silently never binds:

```console
$ duly-conformance --ontologies ontologies check /tmp/badfact
FAIL  /tmp/badfact/condition.json: [code_not_permitted] code 'Soggy' is not a
      permissible value of ItemCondition in millbrook-lending@1.0.0
      (permitted: Good, PagesMissing, WaterDamaged)
FAIL  /tmp/badfact/dueDate.json: [unknown_attribute] attribute 'lib:dueDte' is
      not declared anywhere in millbrook-lending@1.0.0 (did you mean 'lib:dueDate'?)

2 issue(s) across 2 fact(s)
```

---

## 6. Facts through the gate, into the store, into a decision

`decide.py` is the production path in twenty lines.

```python
from duly_conformance import load_repo_registry
from duly_extraction import ingest_envelope
from duly_kernel import adjudicate, content_hash
from duly_store import FactStore

CASE_ID = "millbrook-loan-8842"
QUESTION = "lib:fineWaived"
# The bitemporal point. Caller-supplied, never the wall clock — that is what
# makes this answer reproducible in five years.
AS_OF_EFFECTIVE = "2026-04-08"
AS_OF_KNOWLEDGE = "2026-04-08T09:00:00Z"

registry = load_repo_registry(HERE / "ontologies")
envelope = json.loads((RUN_DIR / "envelope.json").read_text())
rendition_text = (RUN_DIR / "rendition.txt").read_text(encoding="utf-8")

# The envelope names its facts in emission order and `verify_envelope` insists
# on exactly that list, so load by id rather than by glob.
by_id = {f["id"]: f for f in (json.loads(p.read_text())
                              for p in sorted((RUN_DIR / "facts").glob("*.json")))}
facts = [by_id[fact_id] for fact_id in envelope["factIds"]]

with FactStore(str(HERE / "millbrook.db")) as store:
    store.init_schema()
    # One call: manifest hash, rendition hash, fact list, every fact hash,
    # every span, and — because a registry was passed — ontology conformance.
    # Nothing is written unless all of it passes.
    inserted = ingest_envelope(store, envelope, facts, rendition_text, registry)
    # MIND THE ORDER — the two calls take the as-of pair the other way round.
    # `as_of` is (case, knowledge, effective): the store answers "what did we
    # know, and when was it true". `adjudicate` is (…, effective, knowledge):
    # the kernel answers "as of what date, given what was known". Swapping
    # either silently projects or adjudicates at the wrong point.
    live = store.as_of(CASE_ID, AS_OF_KNOWLEDGE, AS_OF_EFFECTIVE)

pack = yaml.safe_load((HERE / "rulepacks/millbrook-overdue-waiver/pack.yaml").read_text())
receipt = adjudicate(live, pack, AS_OF_EFFECTIVE, AS_OF_KNOWLEDGE, QUESTION)

assert content_hash(receipt, "receiptSha256") == receipt["receiptSha256"]
```

```console
$ python decide.py
ingested   3 new fact(s) from run millbrook:run:8842:1
projected  3 live fact(s) at 2026-04-08T09:00:00Z
decision   lib:fineWaived = True
fired      MPL-GRACEDAYS-00, MPL-WAIVE-01
defeated   MPL-DEFAULT-00
abstained  lib:condition — low_confidence (score 0.6, floor 0.75, routed to circulation-review)
receipt    903807f271e99162… (hash verified)
```

Four observations, each a thing you would otherwise learn by being bitten.

**`ingest_envelope` is all-or-nothing and idempotent.** Verification happens
first and nothing is written if any part of it fails; re-running `decide.py`
prints `ingested 0 new fact(s)`, because facts are content-addressed and the
store already holds those exact bytes.

**The answer is generous, and the receipt says why it might be.** The fine was
waived because `MPL-DAMAGE-01` could not bind: its `cond` binding was excluded
by the confidence floor, so the rule was silently inapplicable — which is the
normal state of most rules for most cases and therefore not an error. The
decision is defensible on the evidence admitted; what keeps it *honest* is the
`abstentions` entry, naming the attribute, the score, the floor, the pack
version that set the floor, and where it routed:

```json
{
  "attribute": "lib:condition",
  "confidence": { "method": "raw", "score": 0.6 },
  "entity": "loan:L-8842",
  "facts": ["urn:duly:fact:sha256:a094e5630c91b69f…"],
  "reason": "low_confidence",
  "routedTo": "circulation-review",
  "threshold": { "minConfidence": 0.75, "pack": "millbrook-overdue-waiver",
                 "packVersion": "2026.1.0", "source": "default" }
}
```

An unsupported confident answer would have been indistinguishable from a
supported one. This is not.

**Verifying the hash proves less than it looks like.** Recomputing
`receiptSha256` over the receipt's own canonical bytes proves the document is
unaltered since it was sealed. It does **not** prove the seal was honest — a
forged receipt that was re-sealed passes. Only re-running the rules over the
pinned facts does that, which is what §8's `duly-verify` and the demo's
receipt viewer are for.

**`inputFacts` pins what the decision actually consumed**, not what was in the
store. §7's post-correction receipt has one input fact, because once
`MPL-DAMAGE-01` defeats `MPL-WAIVE-01` the two dates stop being load-bearing.

---

## 7. Abstention, review, and the correction that supersedes

The receipt says the fine is waived *and* that it never saw the item's
condition. Closing that gap is the review loop.

```python
from duly_review import InvalidCorrectionError, ReviewQueue, resolved_item_to_golden_case

# `review.py` is a separate process from `decide.py`, so it re-reads what that
# step persisted rather than sharing objects: the receipt from receipt.json,
# the pack from its YAML, the store by reopening the same SQLite file. The
# queue is a second database beside it — the fact store stays the system of
# record and the queue never holds fact documents.
receipt = json.loads((HERE / "receipt.json").read_text())
pack = yaml.safe_load((HERE / "rulepacks/millbrook-overdue-waiver/pack.yaml").read_text())
store = FactStore(str(HERE / "millbrook.db")); store.init_schema()
queue = ReviewQueue(str(HERE / "review.db")); queue.init_schema()

# The queue verifies the receipt's hash before accepting it, and dedupes by
# (case, abstention entry) — re-running this is a no-op. It returns one row
# per abstention: [{"itemId": "urn:duly:review:sha256:914e…", "created": True}]
queue.enqueue_receipt(receipt, recorded_at="2026-04-08T09:05:00Z")
item = queue.items(status="open")[0]
queue.claim(item["itemId"], "millbrook:staff:r.iyer", "2026-04-09T10:00:00Z")
```

The correction is a **new fact**, not an edit — facts are immutable, and a
value's identity is its bytes. No document says "the desk meant the middle
box", so this fact is grounded by **attestation**: who says so, through what
channel, when. Absence and judgement are not spans, and provenance stays
honest exactly where it is most tempting to fake it.

```python
def correction(*, supersedes: str | None) -> dict:
    body = {
        "caseId": CASE_ID,
        "entity": {"id": "loan:L-8842", "type": "lib:Loan"},
        "attribute": "lib:condition",
        "value": {"kind": "code", "value": "WaterDamaged",
                  "codeSystem": "millbrook-lending/conditions"},
        "grounding": {
            "kind": "attestation",
            "actor": "millbrook:staff:r.iyer",
            "channel": "circulation desk review of slip 8842",
            "at": REVIEWED_AT,
            "note": "Desk note and the circled box agree: water damage to the cover.",
        },
        "assertion": {
            "kind": "human", "at": REVIEWED_AT,
            "actor": {"id": "millbrook:staff:r.iyer", "role": "circulation-supervisor"},
        },
        "recordedAt": REVIEWED_AT,
        "status": "asserted",
        "schemaRef": {"ontology": "millbrook-lending", "version": "1.0.0"},
    }
    if supersedes is not None:
        body["supersedes"] = supersedes
    return seal_fact(body)          # duly's own content hash — never reimplement it
```

### C6: a low-confidence resolution must supersede

Try it without `supersedes` and the queue refuses:

```console
resolving a low_confidence item is a ruling on the fact it abstained over, so
the correction must supersede it: set "supersedes": "urn:duly:fact:sha256:a094…"
and re-seal. Without it the fact stays live and every future receipt carries a
low_confidence entry for an attribute the decision used (spec/compatibility.md
C6). A human fact that is not a ruling on this extraction belongs in the store
directly, not through the queue.
```

This is [spec/compatibility.md](../spec/compatibility.md) C6, and it is worth
understanding rather than working around. Resolving a `low_confidence` item is
by construction a ruling on one specific fact. The coexisting form — a human
fact that merely outranks — leaves the below-floor fact live, so every future
receipt carries a `low_confidence` entry for an attribute the decision *did*
use, which contradicts what `abstentions` means.

**The queue refuses; it does not stamp.** The obvious fix — write `supersedes`
in from the entry's own fact id — is unavailable and instructive: a correction
arrives content-addressed, so writing a field into it changes its hash and
therefore its identity, and the queue would hand the store a document its
author never sealed.

The rule binds this boundary and no other. `FactStore.ingest` still takes an
independent human fact that supersedes nothing, because a value known from a
phone call is not a ruling on anybody's extraction.

```python
abstained_fact_id = item["entry"]["facts"][0]
queue.resolve(item["itemId"], correction(supersedes=abstained_fact_id), store, REVIEWED_AT)

# `resolve` returns the re-projected item. The correction's id is under
# "resolution", not at the top level:
resolved = queue.item(item["itemId"])
resolved["status"]                 # "resolved"
resolved["resolution"]["factId"]   # "urn:duly:fact:sha256:9b965a19bd32f…"
resolved["resolution"]["label"]    # the calibration label, or None — see §9

# Re-ask the same question at a later KNOWLEDGE time. The effective date does
# not move — the loan came back when it came back; what changed is what
# Millbrook knows.
live = store.as_of(CASE_ID, "2026-04-09T11:00:00Z", "2026-04-08")
after = adjudicate(live, pack, "2026-04-08", "2026-04-09T11:00:00Z", QUESTION)

# A method on the queue, taking nothing: the store was consulted at resolution
# time and the label is already recorded on the event.
queue.calibration_pairs()          # [(0.6, 1)]
```

```console
$ python review.py
enqueued   urn:duly:review:sha256:914e7ca86bb…  created=True
claimed    lib:condition — low_confidence
refused    resolving a low_confidence item is a ruling on the fact it abstained over…
resolved   status=resolved fact=urn:duly:fact:sha256:9b965a19bd32f…
projected  3 live fact(s) at 2026-04-09T11:00:00Z
decision   lib:fineWaived = False  (was True)
fired      MPL-GRACEDAYS-00, MPL-DAMAGE-01
defeated   MPL-WAIVE-01
abstained  0 entries
receipt    f18fe217596f3da5…
labels     [(0.6, 1)]
frozen     review-0001 -> review-0001/
```

Same effective date, later knowledge time, opposite answer, and both receipts
survive. That pair is the thing the store exists for: the first receipt is not
wrong and is not deleted — it is what Millbrook correctly concluded from what
Millbrook then knew.

One honest note on the defeat chain. The pre-correction receipt records
`MPL-WAIVE-01 defeated MPL-DEFAULT-00`; the post-correction one records
`MPL-DAMAGE-01 defeated MPL-WAIVE-01` and does not mention `MPL-DEFAULT-00` at
all. A defeated rule's own `defeated` list leaves with it, so a receipt shows
the defeat that survived rather than the whole cascade. Design your default
stacks knowing that.

### The resolution becomes a permanent regression case

```python
frozen = resolved_item_to_golden_case(
    queue, store, item["itemId"],
    pack_path="rulepacks/millbrook-overdue-waiver/pack.yaml",
    golden_dir=HERE / "golden",
    repo_root=HERE,          # what pack_path is relative to; defaults to cwd
)
frozen["caseId"]      # "review-0001" — the next free id in the review series
frozen["caseDir"]     # ".../golden/cases/review-0001"
frozen["receiptPath"] # ".../golden/receipts/review-0001.json"
frozen["receipt"]     # the freshly adjudicated receipt, in memory
```

writes `golden/cases/review-0001/` — the case's facts as of the resolution,
plus a freshly adjudicated receipt — in the corpus layout §8 defines and
`duly-verify` replays:

```yaml
id: review-0001
pack: rulepacks/millbrook-overdue-waiver/pack.yaml
question: lib:fineWaived
asOfEffective: "2026-04-08T00:00:00Z"     # the instant form; see §8
asOfKnowledge: "2026-04-09T10:15:00Z"
```

The freezer takes `asOfEffective` verbatim from the receipt it is freezing, and
a receipt normalizes the as-of pair to instants — so a review-born case carries
`2026-04-08T00:00:00Z` where §8's generator writes `2026-04-08`. Both are legal
(§8 has the field-by-field rules); do not copy this block as the template for a
generator you write yourself, because §8's is the one with a date in it.

A corrected case is the most valuable case a corpus can hold: no generator
seed can reinvent a judgement a person made. Which is why §8's generator has
to preserve the `review-*` series, and why nothing enforces that but you.

---

## 8. A golden corpus of your own

`expected.yaml` catches breakage. Only a corpus catches **drift** — a pack
whose meaning moved while every declared outcome still passed.

**There is no shipped corpus generator for your packs.** `duly_assurance
generate` builds duly's own example corpus from duly's own templates. Yours is
a file like `make_corpus.py`: a document template, a parameter table, and a
writer. That is a property of the design rather than a gap in it — the corpus
is what catches your pack's meaning moving, so its parameters have to be
argued by whoever knows the policy.

```python
DUE = dt.date(2026, 4, 3)

# Straddle the grace boundary in BOTH directions and cross the damage rule.
# grace = 7, so 7 must be waived and 8 must not: an off-by-one in the
# comparison changes exactly one of these cases, which is the point of
# choosing them. 0 is same-day return; 14 is comfortably late.
DAYS_LATE = (0, 1, 6, 7, 8, 14)
CONDITIONS = (("good", "Good"), ("water-damaged", "WaterDamaged"))
```

For each combination the generator builds a slip, runs it through **the same
adapter** as production, adjudicates with **the same kernel**, and writes three
things. Regenerating deletes only its own `mpl-*` series and leaves `review-*`
untouched.

### The corpus layout, and `case.yaml`

```
golden/
  cases/<case-id>/case.yaml
  cases/<case-id>/facts/<attribute-with-colons-as-dashes>.json
  receipts/<case-id>.json
```

`case.yaml` is the only file with a schema you have to know, because it is
what `duly-verify`, `duly-impact` and `duly-whatif` all read to reconstruct
the question:

```yaml
id: mpl-0009                                       # names receipts/<id>.json —
                                                   # keep it equal to the directory
pack: rulepacks/millbrook-overdue-waiver/pack.yaml # resolved against cwd, then
                                                   # against the corpus's parent
question: lib:fineWaived                           # the decision attribute
asOfEffective: "2026-04-12"                        # when the world was as it was
asOfKnowledge: "2026-04-12T09:00:00Z"              # what was known, and when
```

Write all five. `duly-impact` names the three it needs — `pack`,
`asOfEffective`, `asOfKnowledge` — and defaults `id` to the directory; it never
reads `question`. `duly-verify` needs all five and is blunter about it: omit
`question` and you get a bare `KeyError: 'question'` rather than a diagnostic.
And quote the two dates. Unquoted, YAML hands the tools `date`/`datetime`
objects instead of the text you wrote — replay survives it, but the file has
stopped saying what it says.

**Both date forms are legal, and they are not interchangeable in style.**
`asOfEffective` accepts a plain date (`"2026-04-12"`) or an RFC 3339 instant
(`"2026-04-12T00:00:00Z"`); `asOfKnowledge` is an instant. §7's freezer emits
the instant form for both, because it copies them off a receipt, which
normalizes. **Write the plain date in a generator you author.** It is what the
effective point actually means — a day, not a moment — it reads as a day to
whoever opens the file, and it is the form every tool over the corpus has
always been handed.

The facts directory holds the case's live facts one per file, named for the
attribute with `:` replaced by `-`. Nothing reads the names, but two facts
mapping to one name means two live facts on one attribute, which the rule IR
does not allow — so the collision is a real error surfacing as a filesystem
one.

The receipt is written verbatim as adjudicated. `duly-verify` re-derives it
from `case.yaml` plus `facts/` and byte-compares, so **a hand-edited receipt is
the one thing that cannot survive** — which is the property the corpus exists
to have.

One detail in the template pays for itself immediately. The corpus targets
quote the **label as well as the value** — `"Due date        2026-04-03"`, not
`"2026-04-03"` — because on a same-day return the bare date appears on two
lines and the adapter would honestly report 0.60 for both, abstaining facts
the rule needed. A quote is evidence: quote enough of the document that it
identifies itself.

```console
$ python make_corpus.py
mpl-0001   0d late  good          -> True   MPL-GRACEDAYS-00,MPL-WAIVE-01
mpl-0002   0d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
mpl-0003   1d late  good          -> True   MPL-GRACEDAYS-00,MPL-WAIVE-01
mpl-0004   1d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
mpl-0005   6d late  good          -> True   MPL-GRACEDAYS-00,MPL-WAIVE-01
mpl-0006   6d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
mpl-0007   7d late  good          -> True   MPL-GRACEDAYS-00,MPL-WAIVE-01
mpl-0008   7d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
mpl-0009   8d late  good          -> False  MPL-DEFAULT-00,MPL-GRACEDAYS-00
mpl-0010   8d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
mpl-0011  14d late  good          -> False  MPL-DEFAULT-00,MPL-GRACEDAYS-00
mpl-0012  14d late  water-damaged -> False  MPL-GRACEDAYS-00,MPL-DAMAGE-01
```

### Replay

```console
$ duly-verify --golden golden
verified 13 cases

$ duly-conformance --ontologies ontologies check golden/cases
All 39 fact(s) conform (millbrook-lending@1.0.0).
```

`duly-verify` re-adjudicates every case from its committed facts and pack and
**byte-compares** the result against the committed receipt. This is the check
that a receipt's holder can run without trusting or contacting its producer.

Two behaviours to know before you wire it into CI. `--golden` defaults to
`examples/golden`, which is duly's own layout — pass your own path. And a
corpus with no cases is treated as two different situations, deliberately.

A **missing** directory is an operational error, and fails:

```console
$ duly-verify --golden /tmp/nocorpus
no cases directory at /tmp/nocorpus/cases
                                                          # exit 1
$ duly-impact --golden /tmp/nocorpus
impact: error: missing golden corpus: /tmp/nocorpus/cases is not a directory
                                                          # exit 2
```

An **empty but present** corpus is a legitimate state — yours is empty on day
one — so both exit 0, with a line nobody can file as coverage:

```console
$ duly-verify --golden /tmp/emptycorpus
NO CASES IN CORPUS — nothing was replayed. This is not a pass: it means there
was nothing to check.
                                                          # exit 0
$ duly-impact --golden /tmp/emptycorpus
NO CASES IN CORPUS — impact analysis could not see anything. This is not a
result: it means nothing was measured.
                                                          # exit 0
```

### Impact

```console
$ duly-impact --golden golden
0 of 13 decisions flip; 0 reasoning-only changes
```

Now change one thing — the grace period from seven days to three — and ask
again:

```console
$ duly-impact --golden golden
2 of 13 decisions flip; 3 reasoning-only changes
  FLIP mpl-0005: true -> false
  FLIP mpl-0007: true -> false
  REASONING mpl-0006: decision unchanged, rules differ
  REASONING mpl-0008: decision unchanged, rules differ
  REASONING review-0001: decision unchanged, rules differ
```

`--markdown out.md` writes the same analysis as a PR comment, with before and
after rule sets per flipped case. **Impact reports; it does not gate.** A
change that flips decisions is not necessarily wrong — but the flip must be
intentional, explained, and visible, and a pack with no corpus coverage gets a
cheerful "0 of N flip" for every edit, forever.

The reasoning-only rows are the ones worth staring at: `mpl-0006` and
`mpl-0008` still refuse the waiver, but for a different reason than before,
which is exactly the class of change a decision-value assertion cannot see.

### Asking the corpus a backward question

With the `prove` extra installed, `duly-whatif` frees one input and solves the
pack for it — then re-runs the kernel on every answer, because the solver
proposes and the kernel disposes:

```console
$ duly-whatif --case golden/cases/mpl-0009 --free lib:returnedDate --flip \
      --ontologies ontologies
pack millbrook-overdue-waiver 2026.1.0
  decision   lib:fineWaived
  as of      2026-04-12
  today      false
  freed      lib:returnedDate  (date)
  target     true (today: false)

  SATISFIABLE
    nearest value reaching the target: 2026-04-10
      kernel confirms  2026-04-10 -> true
      kernel refutes   2026-04-11 -> false
```

Due 2026-04-03 plus seven days of grace: the last date that still earns the
waiver is the 10th, and the kernel agrees. See [spec/whatif.md](../spec/whatif.md)
for why UNSAT is the weaker verdict.

---

## 9. Calibration labels — and what they are not

A resolved review item yields a labeled `(score, correct)` pair when — and
only when — its abstention entry carried a machine confidence and the
abstained fact was retrievable from the store: `1` if the human confirmed the
machine's value, `0` if they contradicted it.

```console
$ python calibrate.py
pairs      [(0.6, 1)]
count      1
refused    degenerate calibration set: every example is labeled correct;
           temperature/Platt likelihoods have no interior optimum on a
           single-class set and would fabricate extreme confidence — collect
           labels of both kinds before fitting
```

The refusal is the feature. So are the items that yield **no** pair, all by
design: dismissals (a dismissal says the machine fact was unusable, which is
not a value judgement you can score), conflict entries (no single score),
and resolutions where the abstained fact was not in the store.

**The censored-sample constraint is the part to carry into your own
deployment.** Every pair here labels a fact your policy *already distrusted*.
The facts that cleared the floor were never reviewed, so this export says
nothing about the upper score range. Fitting on these pairs alone does not
calibrate your extractor; it characterizes the region below your floor —
useful for validating or tightening the floor, and not a basis for any
accuracy claim. Combine them with labels from audit sampling of *accepted*
facts before fitting anything that claims full-range calibration.
[calibration/README.md](../calibration/README.md) has the math and the rest of
the caveats.

Note also that a recalibrated fact is a **new fact** superseding the old one,
never an edit: the confidence is inside the content hash.

---

## 10. Looking at it: the demo against your own content

The four demo pages are toolkit, not teaching content — they read whatever
packs, cases and receipts exist. Point them at your root:

```bash
pip install "duly[demo] @ https://github.com/kjpatel/duly/releases/download/v1.1.0/duly-1.1.0-py3-none-any.whl"
DULY_DEMO_CONTENT=$PWD uvicorn duly_demo.app:app --port 8834
```

All four pages serve, and **two of the four have content at this point**. The
rule studio renders `millbrook-overdue-waiver` as a decision-table grid, and
the receipt viewer reads your 13 cases (`/api/receipts/corpus` → `count: 13`).

The other two are empty, and for the same reason: both are keyed on
*scenarios*, which come from `starters/` — the synthetic-documents directory
this guide does not build. The decision workspace returns `[]`, and so does the
evidence browser (`/api/evidence/cases` → `{"cases": [], …}`), even though your
facts and documents exist on disk: it presents them per scenario, and you have
declared none. Building one is `starters/<name>/scenario.json` plus its
documents and renditions ([examples/starters/README.md](../examples/starters/README.md)) —
worth doing when you want the evidence pane, unnecessary for everything above.
Two empty panes is the degrade-honestly discipline working: a demo that
refused to start until you built a starter would be answering a question
nobody asked.

**Set `DULY_DEMO_CONTENT` or the demo finds nothing quietly.** Installed from
a wheel, its default content root resolves inside `site-packages`, which has
no content — so a wheel-installed demo serves its built-in fixture scenario
and empty listings, and nothing raises.

The receipt viewer is the payoff, because it is three checks and not one
verdict:

```
verdict: pass - This receipt replays byte-for-byte.
  receiptHash  pass   SHA-256 of the canonical JSON body matches the hash the receipt carries.
  facts        pass   all 2 pinned facts are present and each one hashes to the content hash in its own id.
  replay       pass   re-running the kernel over the pinned facts, the named pack version and
                      the receipt's own asOf pair reproduced this receipt.
```

They are separate because a forged receipt that was *re-sealed* passes the
first two. Paste in a receipt and no facts and the verdict is `partial`, not
`fail` — inputs unavailable is a different answer from a check refuted.

---

## Ten things that are not automatic

Most wiring is. These are the ones where nothing fails loudly, which is
exactly why they get skipped. The model for this section is
[examples/rulepacks/README.md](../examples/rulepacks/README.md)'s
"three things are not".

1. **Golden-corpus coverage.** Impact analysis runs over your corpus, not over
   your declared outcomes. A pack with no cases in the corpus reports "0 of N
   decisions flip" for every edit, forever, and reads exactly like safety.
2. **Running your `expected.yaml`.** Nothing does. The rule studio reads it in
   a browser; the automated runner lives under `examples/tests/` and dies with
   the examples. Write the twenty-line harness in §4 and put it in CI.
3. **Preserving `review-*` cases.** Your generator resets its own series; if it
   also deletes the human-corrected cases, no seed will recreate them. Scope
   the deletion to your generated prefix.
4. **Ontology versions are immutable, and nothing stops you editing one.**
   `schemaRef` is inside every fact's hash, so an edit in place silently
   invalidates the relationship between your committed facts and the vocabulary
   they claim to speak. New terms go in a new version file.
5. **Ambiguous quotes abstain facts your rules needed.** A quote that appears
   twice is honestly scored 0.60 and, under a 0.75 floor, silently excluded.
   The failure is *safe* — the receipt says so — but the cause is invisible
   from the pack. Quote enough of the document to be unique.
6. **Adding an `abstentionPolicy` changes receipts.** The floor is inside
   `rulePack.version`, so introducing or moving one is corpus churn: bump the
   pack version and expect impact to report it.
7. **Scripted confidences need pinning.** If a scenario or fixture depends on
   an exact confidence, the adapter that produces it must be the one you
   scripted — a measuring adapter will silently overwrite a scripted 0.58 with
   a passing 0.90 and skip the arc the fixture exists to demonstrate.
8. **`duly-verify` and `duly-impact` default `--golden` to `examples/golden`.**
   That is duly's own layout. Pass your path; both fail loudly if you don't,
   but a wrapper script that swallows stderr will not.
9. **A decision with no `phrasing:` case names its attribute back at you.**
   Nothing fails: `**Verdict:** fineWaived: yes` is a legitimate report line,
   and it is what your auditors will read. Cover every value your decision can
   take, including the abstained variants.
10. **Rule-id checks only run if you declare `pack.idPrefix`.** Declaring one
    is the opt-in. Leaving it off is a legitimate choice for a ported rulebase
    whose ids are already in your own receipts — but then nothing catches an
    id that encodes a threshold, and ids are permanent.

---

## What this guide deliberately does not cover

- **A real extractor.** `SlipAdapter` reads plain text. The shipped Docling
  adapter (`pip install "duly[extraction]"`) does the same job over PDFs and
  is the second worked example of the same protocol.
- **Authoring rules as decision tables.** If your organization already reviews
  rules as DMN, `duly-dmn compile` produces an ordinary pack the kernel cannot
  distinguish from a hand-written one. It replaces §4 and nothing else. See
  [spec/dmn.md](../spec/dmn.md).
- **Multi-entity cases.** v0 assumes one entity per `entityType` per case and
  one live fact per attribute. Per-document decisions therefore need one case
  per document, or the document type modelled as an attribute.
- **Business-day arithmetic.** The IR has no date-plus-N and no holiday
  calendar in its expression grammar; a pack that needs them carries its
  calendar as pack data. See [spec/rule-ir.md](../spec/rule-ir.md), "Calendars".
- **Serving decisions.** duly adjudicates and provides evidence. Orchestration,
  actions, and your review UI are yours.
- **Real policy.** Millbrook is fictional and so is every citation above. A
  real pack cites the authority behind each rule or carries a `TODO(verify)`
  naming what was not confirmed.

---

## The whole day, as commands

```bash
# 1. install
python3 -m venv .venv && source .venv/bin/activate
pip install "duly @ https://github.com/kjpatel/duly/releases/download/v1.1.0/duly-1.1.0-py3-none-any.whl"

# 2. your vocabulary, your rules             (§3, §4)
duly-conformance --ontologies ontologies list
python -m duly_assurance prove --ontologies ontologies \
    rulepacks/millbrook-overdue-waiver/pack.yaml       # optional; needs [prove]

# 3. documents -> facts                       (§5)
python extract.py
duly-conformance --ontologies ontologies check runs/8842-1/facts

# 4. facts -> store -> receipt                (§6)
python decide.py

# 5. abstention -> review -> corrected receipt -> regression case   (§7)
python review.py

# 6. a corpus, replayed and impact-analyzed   (§8)
python make_corpus.py
python check_expected.py          # §4's harness; its factsFrom point here
duly-verify --golden golden
duly-impact --golden golden

# 7. labels, honestly                          (§9)
python calibrate.py

# 8. look at it                                (§10)
DULY_DEMO_CONTENT=$PWD uvicorn duly_demo.app:app --port 8834
```

## What you are depending on

The contracts you just built against — the grounded fact, the receipt, the
rule IR, the replay guarantee — are at v1.0 and held stable, which is a
narrower and more useful claim than *frozen*. A break is available and priced:
it is a major-version event with a written procedure behind it ([C9](../spec/compatibility.md#c9-how-a-break-happens)),
and every unintended one is a named failing check rather than something a
reader notices — the 351-receipt replay, the canonical-form vectors, the
digest determinant set, `check_replayable` refusing a foreign `engine.version`.
There are no external adopters yet, so today that stability is policy plus
checks rather than anyone's dependency, and a break stays a deliberate
major-version move until that changes. Which is the argument for keeping the
receipt rather than the toolkit version that made it: `mpl-0007` names the
semantics it was decided under, and it replays under those semantics whatever
later versions of duly go on to do. Read
[spec/compatibility.md](../spec/compatibility.md) before you depend on
anything not in its table.

## Where to go next

- [examples/rulepacks/README.md](../examples/rulepacks/README.md) — authoring
  a pack end to end, and what is *not* auto-wired
- [spec/grounded-facts.md](../spec/grounded-facts.md) /
  [spec/rule-ir.md](../spec/rule-ir.md) — the two contracts, with open
  questions at the bottom
- [spec/compatibility.md](../spec/compatibility.md) — what v1.0 holds stable
  per contract, how a break happens when one is right (C9), and why the
  receipt has no extension point
- [docs/follow-one-fact.md](follow-one-fact.md) — one committed fact traced
  byte by byte from PDF text to receipt to human correction
- [docs/concepts.md](concepts.md) — the vocabulary this repo uses precisely
- [docs/neuro-symbolic-architecture.md](neuro-symbolic-architecture.md) — the
  platform-engineer mental model: trust boundaries, guarantees, extension paths
- [docs/faq.md](faq.md) — the objections a skeptical reader raises first
- [review/README.md](../review/README.md) /
  [calibration/README.md](../calibration/README.md) — component contracts and
  their honest caveats
