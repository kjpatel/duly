# Starters

One directory per vertical: synthetic source documents, their extracted renditions, and span-verified grounded facts. A starter is what makes a rule pack *demonstrable* — the demo discovers `examples/starters/*/scenario.json` at startup and turns each one into a scenario.

```
examples/starters/<name>/
  make_documents.py     # generates the PDFs (imports the shared helpers below)
  documents/*.pdf       # committed, sha256-pinned in scenario.json
  renditions/*.txt      # the extracted text that fact spans index into
  facts/*.json          # span-verified GroundedFacts
  scenario.json         # manifest: id, title, domain, caseId, defaultAsOf, documents, facts, rulePack
```

`rulePack` in the manifest is **content-root relative** (`rulepacks/<name>/pack.yaml`), like a golden case's `pack`: the demo resolves it against its content root, which is `examples/` here and yours in a deployment.

Two of the six starters — `notice-ny` and `trid` — have no `make_documents.py` of their own. They predate the shared helpers and their documents come from `tools/make_documents.py`'s own `main()`. New starters do not copy them: write your own module and import the helpers.

Shared tooling in [tools/](tools/) — import from these, don't edit them:

- `make_documents.py` — `render_pdf`, `rendition_text`, `build_document`
- `extract.py` — targets file → contract-conformant facts with verified spans
- `check_facts.py` — validates every starter's facts (schema, content hashes, quote spans)
- `targets/<starter>-<document>.json` — one per document: which attributes to look for and the quote that grounds each

## Building one

```bash
uv run python examples/starters/<name>/make_documents.py        # PDFs + renditions
uv run python examples/starters/tools/extract.py \
    --rendition examples/starters/<name>/renditions/<doc>.txt \
    --pdf       examples/starters/<name>/documents/<doc>.pdf \
    --targets   examples/starters/tools/targets/<name>-<doc>.json \
    --out-dir   examples/starters/<name>/facts
uv run python3 examples/starters/tools/check_facts.py           # schema, hashes, spans
```

`--pdf` computes the document's SHA-256 so the facts and `scenario.json` pin the same bytes; `--document-sha256` takes it directly when the source is not on disk. Re-running `extract.py` over an unchanged rendition reproduces the committed facts byte-for-byte — content addressing means a fact that changes has changed. `check_facts.py` globs `starters/*/scenario.json`, so a new starter needs no registration, and neither does the demo, which discovers scenarios the same way at startup.

**A `make_documents.py` merges into `scenario.json`; it does not own it.** A key the generator emits (documents, renditions, hashes) is the generator's; a key it does not emit (`domain`, `demoExtractor`, `reviewArc`, anything you add) is yours and survives a re-run — enforced by `examples/tests/test_example_starter_generators.py`, which regenerates every starter against a tmp tree and fails on any manifest drift. The *why* is worth keeping: the generators once rewrote manifests from literals inside themselves, and every hand-maintained key had drifted into them one silent revert at a time.

## What gates a starter, and what does not

- **`check_facts.py` proves the provenance chain**: every content hash recomputes and every quote matches `rendition[start:end]` exactly. It runs in CI as part of the pack verification block. What it cannot check is whether a quote is *unique* in the rendition — a quote appearing twice is honestly scored low and may fall below a pack's abstention floor, which from the pack looks like a rule that never fired.
- **`defaultAsOf` is required, and it is a curation decision rather than a derived one.** It is the effective date the scenario's page opens on, and every adjudication made from that page carries it. The demo used to derive the date — latest `effectiveFrom` among the facts, falling back to `date.today()` — and since no committed fact carries that field, the fallback was the only branch that ever ran: every scenario's default answer drifted with the calendar, in a project whose claim is that a decision replays under the rules of a *named* date. It also hid teaching. `tila-rescission` answers `fundingPermitted = true` at any date past the rescission window, so the floating default showed the dull steady state instead of the rule doing work; pinned to consummation day it answers `false`, because the borrower can still rescind. Pick the moment the case turns on — the day the notice was mailed, the day the loan closed — and say why in the sibling `defaultAsOfWhy`, which is the only comment JSON allows you. `examples/tests/test_example_starter_generators.py` fails a starter that declares neither.
- **Nothing pins a scripted confidence.** If the scenario depends on an exact value — a below-floor fact that must abstain to demonstrate the review arc — set `"demoExtractor": "stub"` in `scenario.json`, or Docling measures its own and silently overwrites it. `county-recording` is the committed example. No test warns at authoring time; this one was found by looking at the running demo.
- **`domain` is a display contract.** An unknown slug gets a title-cased label and a missing field lands the scenario in "Other" — graceful, and unlabeled.

**Adding a starter is step 3 of authoring a rule pack.** The full path — the three things that are *not* auto-discovered, the constraints that will bite you, and what a pack PR's reviewers read for — is in [examples/rulepacks/README.md](../rulepacks/README.md).

Everything here is synthetic by construction, and the top-level README's honest-labels paragraph says so. Facts are span-verified against the actual generated PDF text, so the provenance chain is real even though the documents are not.
