# DMN decision-table compiler

A second authoring surface for rule packs. A DMN 1.3+ decision table goes in; a
rule-IR `pack.yaml` comes out, validated by the kernel's own pack validator
before the compiler returns it. Nothing downstream can tell the difference:
same IR, same kernel, same receipts, same replay.

**Read [spec/dmn.md](../spec/dmn.md) first.** It is where the decisions are
argued — the S-FEEL subset, the hit-policy mapping, why an uncited row is a
compile error rather than an auto-`TODO(verify)`, and what this deliberately
does not do.

```bash
uv run python -m duly_dmn compile   dmn/examples/trid-fee-tolerance.dmn
uv run python -m duly_dmn compile   my-rules.dmn -o rulepacks/my-pack/pack.yaml
uv run python -m duly_dmn verify    my-rules.dmn rulepacks/my-pack/pack.yaml   # CI: no drift
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
| [`examples/trid-fee-tolerance.dmn`](examples/trid-fee-tolerance.dmn) | the acceptance example: the TRID pack's three rules as two decision tables |
| [`examples/trid-fee-tolerance.pack.yaml`](examples/trid-fee-tolerance.pack.yaml) | its committed compilation — a build artifact, not a seventh rule pack |
| [`examples/refusals/`](examples/refusals/) | one minimal broken document per refusal class |

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

## After compiling

A compiled `pack.yaml` is a rule pack like any other, which means
[rulepacks/README.md](../rulepacks/README.md) applies from step 2 onward and
none of it is automatic: `expected.yaml`, a starter, demo verdict phrasing, a
golden-corpus generator template, and ontology coverage are all still yours to
write. The compiler produces a pack; it does not produce a *shipped* pack.

Wire `python -m duly_dmn verify <src.dmn> <pack.yaml>` into your checks so the
committed pack and its decision table cannot drift apart.
