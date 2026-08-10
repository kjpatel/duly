# DMN decision-table compiler

A second authoring surface for rule packs. A DMN 1.3+ decision table goes in; a
rule-IR `pack.yaml` comes out, validated by the kernel's own pack validator
before the compiler returns it. Nothing downstream can tell the difference:
same IR, same kernel, same receipts, same replay.

## What DMN is, and why duly compiles it

DMN — [Decision Model and Notation](https://www.omg.org/dmn/) — is the OMG
standard (the body behind BPMN) for expressing business decisions as tables:
one row per rule, input columns holding conditions, an output column holding
the conclusion, and a **hit policy** declaring how overlapping rows resolve.
Its adoption is not broad across software generally; it is concentrated
exactly where duly is aimed — credit decisioning, insurance underwriting,
claims, benefits eligibility — regulated verticals where the people who *own*
the rules are analysts and compliance officers, not engineers. A decision
table is the one rules format such a reader can review and correct without
learning a programming language, and organizations in these verticals often
already hold their rulebases in it.

The full DMN standard is much bigger than tables — decision-requirements
diagrams, boxed expressions, the complete FEEL expression language. duly takes
the decision-table heart and compiles it rather than executing it, for three
reasons:

- **One thing runs.** [spec/rule-ir.md](../spec/rule-ir.md) calls the rule IR
  "the neutral middle format for rules"; this compiler is what makes that
  claim true rather than aspirational. A compiled table is a pack like any
  other, and `examples/tests/test_equivalence.py` proves it: the same facts
  adjudicated under a DMN-authored TRID pack and the hand-written one reach
  the same decision, fire the same rules, and build the same defeat chains.
- **Existing rulebases get an import path.** Rules already living in DMN — or
  in the spreadsheets that are one transcription away from it — come into
  duly without being rewritten in YAML (see [Authoring the
  table](#authoring-the-table) below).
- **duly's guarantees don't bend to the format.** DMN has no vocabulary for
  legal citations or effective dates, and duly does not adjudicate without
  them — so the compiler demands them as annotations and refuses, loudly and
  at compile time, any construct the IR cannot execute honestly. What a
  translation layer must never do is approximate.

**Read [spec/dmn.md](../spec/dmn.md) first.** It is where the decisions are
argued — the S-FEEL subset, the hit-policy mapping, why an uncited row is a
compile error rather than an auto-`TODO(verify)`, and what this deliberately
does not do.

```bash
uv run python -m duly_dmn compile   examples/dmn/trid-fee-tolerance.dmn
uv run python -m duly_dmn compile   my-rules.dmn -o my-pack/pack.yaml
uv run python -m duly_dmn verify    my-rules.dmn my-pack/pack.yaml             # CI: no drift
uv run python -m duly_dmn describe  my-rules.dmn                               # what did it read?
uv run python spec/dmn_demo.py                                                 # see it adjudicate
uv run pytest dmn/tests -q
```

## What is here

| Path | What it is |
|---|---|
| [`duly_dmn/reader.py`](duly_dmn/reader.py) | DMN XML → an ordered in-memory model (stdlib `xml.etree`, nothing else) |
| [`duly_dmn/sfeel.py`](duly_dmn/sfeel.py) | cell compiler: S-FEEL unary tests and output expressions → duly expression source |
| [`duly_dmn/compiler.py`](duly_dmn/compiler.py) | hit-policy mapping, the annotation convention, binding resolution, the UNIQUE disjointness check |
| [`duly_dmn/emit.py`](duly_dmn/emit.py) | pack dict → `pack.yaml` text, byte-deterministically |
| [`examples/dmn/trid-fee-tolerance.dmn`](../examples/dmn/trid-fee-tolerance.dmn) | the acceptance example: the TRID pack's three rules as two decision tables |
| [`examples/dmn/trid-fee-tolerance.pack.yaml`](../examples/dmn/trid-fee-tolerance.pack.yaml) | its committed compilation — a build artifact, not a seventh rule pack |
| [`examples/dmn/refusals/`](../examples/dmn/refusals/) | one minimal broken document per refusal class |

## The three-minute version

A table needs three `duly:` annotation columns on every row — `duly:ruleId`,
`duly:citation`, `duly:effectiveFrom` — and one `<duly:decision>` extension
element per decision saying which entity it is about, which attribute it
concludes, and that attribute's duly value kind. DMN has no vocabulary for
those last three: it decides over a flat context, and duly decides *about an
entity*.

Three hit policies compile: `UNIQUE` (all rows at one priority, disjointness
proven or refused), `FIRST` and `PRIORITY` (descending priorities in row
order). The other four are refused by name, because each asks for a
list-valued or order-free conclusion the rule IR does not have.

A `-` cell removes the column's **binding**, not just its condition — otherwise
a catch-all default row would quietly become conditional on every fact in the
table having been extracted. That is [spec/dmn.md M4](../spec/dmn.md), and it
is the thing most likely to surprise you.

## Authoring the table

You do not have to write DMN XML by hand. Decision tables are what DMN
modeling tools edit: [Camunda Modeler](https://camunda.com/download/modeler/)
(free desktop app, built on the open-source
[dmn-js](https://bpmn.io/toolkit/dmn-js/)), the KIE/Drools editors (including
a free online sandbox), Trisotech Decision Modeler, and other DMN
1.3-conformant tools. Two caveats specific to duly's convention:

- The three required `duly:` columns are standard DMN 1.3 rule-annotation
  columns (`annotation` / `annotationEntry` in the XML) — but not every
  editor's UI exposes *multiple named* annotation columns. Check yours before
  committing to it; a tool that shows only a single free-text annotation cell
  cannot author the convention.
- No general-purpose tool will emit the `<duly:pack>` and `<duly:decision>`
  extension elements (`urn:duly:dmn:0.1`). Extension elements are the
  standard's escape hatch, so a conformant tool must *preserve* them — you add
  them once in a text editor, copying the blocks from
  [examples/dmn/trid-fee-tolerance.dmn](../examples/dmn/trid-fee-tolerance.dmn).

So the realistic workflow: author and edit the tables in a modeler, paste in
the extension blocks, then `python -m duly_dmn describe my-rules.dmn` to see
exactly what the compiler read — pack identity, decisions, bindings,
annotations — before you `compile`. If a round trip through your editor ever
drops the extension elements or the annotation columns, `describe` is where
that shows up.

## After compiling

A compiled `pack.yaml` is a rule pack like any other, which means
[examples/rulepacks/README.md](../examples/rulepacks/README.md) applies from step 2 onward and
none of it is automatic: `expected.yaml`, a starter, demo verdict phrasing, a
golden-corpus generator template, and ontology coverage are all still yours to
write. The compiler produces a pack; it does not produce a *shipped* pack.

Wire `python -m duly_dmn verify <src.dmn> <pack.yaml>` into your checks so the
committed pack and its decision table cannot drift apart.
