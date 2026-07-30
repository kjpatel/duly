# Starters

One directory per vertical: synthetic source documents, their extracted renditions, and span-verified grounded facts. A starter is what makes a rule pack *demonstrable* — the demo discovers `starters/*/scenario.json` at startup and turns each one into a scenario.

```
starters/<name>/
  make_documents.py     # generates the PDFs (imports the shared helpers below)
  documents/*.pdf       # committed, sha256-pinned in scenario.json
  renditions/*.txt      # the extracted text that fact spans index into
  facts/*.json          # span-verified GroundedFacts
  scenario.json         # manifest: id, title, domain, caseId, documents, facts, rulePack
```

Shared tooling in [tools/](tools/) — import from these, don't edit them:

- `make_documents.py` — `render_pdf`, `rendition_text`, `build_document`
- `extract.py` — targets file → contract-conformant facts with verified spans
- `check_facts.py` — validates every starter's facts (schema, content hashes, quote spans)
- `targets/<starter>-<document>.json` — one per document: which attributes to look for and the quote that grounds each

**Adding a starter is step 3 of authoring a rule pack.** The full path, including the three things that are *not* auto-discovered and the constraints that will bite you, is in [rulepacks/README.md](../rulepacks/README.md).

Everything here is synthetic by construction, and the top-level README's honest-labels paragraph says so. Facts are span-verified against the actual generated PDF text, so the provenance chain is real even though the documents are not.
