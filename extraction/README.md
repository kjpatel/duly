# duly extraction adapters

The seam where a probabilistic reader hands facts to a deterministic one. An adapter turns one source document into three artifacts — a **rendition**, a list of **grounded facts** whose spans index into it, and a **run envelope** that lets the whole run be verified or revoked at once — and duly's contract begins at that line, not inside your model. Two adapters ship: the scripted [`StubAdapter`](duly_extraction/stub.py) and the [Docling adapter](duly_extraction/docling_adapter.py). They exist to prove the protocol is wide enough for both a fixed script and a real converter, and they are the two worked examples a third adapter is written against.

This is the other contribution edge, the one that is not rule packs ([README, contribution model](../README.md#contribution-model)). [docs/adopters-guide.md §5](../docs/adopters-guide.md#5-your-extraction-adapter) writes an adapter for an invented domain end to end; this file is the contract, the acceptance bar, and the honest boundaries.

| Module | What it provides |
|---|---|
| `adapter.py` | The `ExtractionAdapter` protocol, `SourceDocument`/`Rendition`/`ExtractionResult`/`SkippedTarget`, quote location (`locate_quote`, `match_confidence`), and the two functions that matter most: `build_fact` (seals a fact) and `verify_fact_span` (the acceptance check) |
| `envelope.py` | Run manifests: `build_envelope` on the producer side; `verify_envelope`, `ingest_envelope`, `revoke_run` on the consumer side, with the ontology conformance gate as an optional argument |
| `stub.py` | Adapter #1 — scripted, reads no document bytes, rendition supplied at construction. The reference implementation and the offline replay path |
| `docling_adapter.py` | Adapter #2 — [Docling](https://github.com/docling-project/docling) converts the bytes and the exported Markdown *is* the rendition. Behind the `extraction` extra; the module imports without it |

## The protocol

The first import needs no knowledge of this package's file layout — everything an adapter author touches is re-exported from the package root:

```python
from duly_extraction import (
    ExtractionAdapter, ExtractionResult, Rendition, SkippedTarget, SourceDocument,
    build_envelope, build_fact, derive_run_id, locate_quote, match_confidence,
    verify_envelope, verify_fact_span,
)
```

An adapter is a `name`, a `version`, and one call:

```python
class ExtractionAdapter(Protocol):
    name: str
    version: str
    def extract(self, document: SourceDocument, targets: dict) -> ExtractionResult: ...
```

`isinstance(adapter, ExtractionAdapter)` works — the protocol is `runtime_checkable` — but it is a *shape* check: it confirms the three attributes exist and nothing about `extract`'s signature or its output. A class whose `extract` takes four arguments passes it. Conformance is the acceptance bar below, not the `isinstance`.

**The rendition** is the immutable extracted text that spans are defined against ([D4](../spec/grounded-facts.md#d4-spans-reference-a-hashed-document-rendition)), content-addressed by the SHA-256 of its UTF-8 bytes and tied to the SHA-256 of the source bytes. Spans point at a rendition, never at the PDF, because two converters produce two different texts from identical bytes and old spans must keep resolving. `Rendition.extractor`/`extractor_version` name **the thing that produced the text**, not the adapter that asserts the facts — the Docling adapter stamps `docling` and the installed docling release, while the adapter identity `duly-docling-adapter 0.1.0` goes on the facts. The text changes when the converter changes, so that is what the rendition is versioned by.

**The facts** come from `build_fact`, which is the only supported way to make one. It assembles the contract-conformant body, computes `contentHash` as SHA-256 over the RFC 8785 canonical JSON excluding `id` and `contentHash`, and sets `id` to `urn:duly:fact:sha256:<hash>`. What it *passes through* from the target and never invents: `effectiveFrom`, `effectiveTo`, `page`, and `sensitivity`. What it *fixes*: `assertion.kind` is always `machine` — an adapter cannot emit a human assertion, and a human correction enters through the [review queue](../review/README.md) instead. Hash your facts this way and no other: a fact hashed a private way is a fact nobody else can check.

**`verify_fact_span(fact, rendition_text)`** is the acceptance check, and both shipped adapters call it on **every emission** rather than in a test — the line is `verify_fact_span(fact, rendition.text)  # adapter acceptance test` in each. It refuses three things: a fact whose grounding is not `kind: "document"`, a fact with no `charSpan`, and — the one it exists for — a fact whose `quote` is not exactly `rendition_text[start:end]`, code point offsets, end-exclusive. It deliberately checks nothing else: not the content hash (that is `verify_envelope`), not the ontology (that is the conformance gate). A fact whose span does not resolve is unfalsifiable evidence, which is worse than no evidence.

**The envelope** is the manifest of one run: `runId`, adapter identity, document id + hash, rendition id + hash, `createdAt`, and `factIds` — ordered, complete, exactly what the run proposed in emission order. It is content-addressed the same way facts are (`urn:duly:run:sha256:<hash>`), which makes it an *integrity* claim and not an authenticity one; asymmetric signatures are a documented future hook in a separate sidecar ([compatibility C7](../spec/compatibility.md)), not a field this schema will grow.

The **targets** dict is the fact-proposal seam: `{documentId, caseId, schemaRef, assertedAt, runId?, page?, facts: [...]}`. Both shipped adapters need to be told which attributes to look for, because document conversion gives you text, not an ontology. A model-driven proposer — an LLM deciding what to assert, schema-constrained decoding over the rendition — replaces this argument with generated proposals, and the rendition, span verification, fact shape and envelope stay exactly as they are. That is the seam, and it is the only one.

## The acceptance bar for a contributed adapter

Five properties. They are what the shipped adapters' suites assert about themselves, and a contributed adapter that holds all five is one the toolkit can carry facts from.

1. **Span-faithful on every emission.** Call `verify_fact_span` inside `extract`, before appending the fact — not in a test. And re-read the slice rather than echoing the target's quote: `locate_quote(..., allow_normalized=True)` can match across different whitespace, which is a *different string*, and the fact must carry what the rendition actually says.
2. **Confidence measured or honestly absent.** A machine fact's `confidence.method` is `raw` unless a fitted calibrator produced it — `match_confidence` is an honest heuristic proxy (exact and unique 0.90, exact but ambiguous 0.60, normalized 0.70/0.50) and says so by emitting `raw`. Calibration is [downstream](../calibration/README.md) and a different claim (spec D5). Omitting confidence is legal and **fails closed**: under an active `abstentionPolicy` the kernel excludes a machine fact carrying none and writes `machine assertion carries no confidence; policy fails closed` onto the receipt's abstention entry. Scripted confidences are for demos and must say so where they are written.
3. **Sensitivity declared, never inferred.** `sensitivity` passes through from the target because whether a quote carries PII is knowable when the target is authored and unknowable from the span. An adapter that guessed would be asserting a handling class it cannot ground; absent already means `internal`.
4. **Deterministic ids, no wall clock.** `assertedAt` comes from the targets. `runId` comes from the targets or from `derive_run_id(document, asserted_at)`; a rendition id must be stable and unique per (converter, document). Same document and same targets in, byte-identical facts and envelope out, forever — the same invariant the rest of the toolkit holds.
5. **Nothing silently dropped, and the whole run round-trips.** A target the adapter could not ground goes into `ExtractionResult.skipped` as a `SkippedTarget` with a reason; `len(facts) + len(skipped) == len(targets["facts"])` is a real assertion in the Docling suite. And the run must survive produce → verify → ingest → revoke: `verify_envelope` re-checks the manifest hash, the rendition hash, the fact list against `factIds` (order and membership), every fact's hash, every fact's document/rendition/run linkage, and every span. `ingest_envelope` is all-or-nothing — nothing reaches the store if any check fails — and `revoke_run` retracts every live fact carrying the run id. Pass `registry=` to either and the [ontology conformance gate](../spec/ontology-conformance.md) rejects a misspelled attribute the integrity checks cannot see.

## Testing an adapter that calls a live service

**Start with what duly's own Docling suite actually does**, because it is not the recording pattern and reading it as one would mislead you: [`tests/test_docling.py`](tests/test_docling.py) calls the real converter, every time it runs. It is `pytest.importorskip("docling")` at module scope plus `pytestmark = pytest.mark.docling`, so it skips entirely on a plain `uv sync`; the input is the committed fixture PDF (`fixtures/scenario/documents/widget-report.pdf`) and the targets beside it; a module-scoped fixture builds one `DoclingAdapter` because model load is expensive; and the assertions are the acceptance bar — protocol shape, a rendition derived from the bytes and versioned by the installed docling release, every fact span-verified with `method: "raw"`, the envelope round trip through an in-memory store, and a hash-only `SourceDocument` refused. Docling is an in-process library, so nothing is recorded: the "live service" is a wheel.

**A vendor HTTP service is the case that needs recording**, and duly's shape makes it small, because conversion and fact proposal are already separable. The rendition *is* the recording. Structure the adapter so both the conversion call and the version it stamps are constructor arguments:

```python
class AcmeAdapter:
    name, version = "acme-ocr-adapter", "1.0.0"

    def __init__(self, *, render=None, service_version="acme-ocr-2026.03"):
        self._render = render or self._call_service       # bytes -> text
        self._service_version = service_version           # what the rendition is versioned by

    def _call_service(self, document: SourceDocument) -> str:
        ...  # the live path: POST document.data, return the extracted text
```

`extract` itself is unchanged from the walked example — build the `Rendition` from
`self._render(document)`, loop the targets, `build_fact` + `verify_fact_span`, close with
`build_envelope`. Then the contributed test suite is:

- **Record once.** Run the live path against one document you may commit, and write the returned text to `tests/recordings/<document>.txt`. Commit the recording, the source document, the targets file, and the facts the run emitted.
- **The offline suite injects the recording** — `AcmeAdapter(render=lambda doc: RECORDING.read_text(encoding="utf-8"))` — and asserts the five properties above plus byte equality against the committed facts. It needs no credentials, no network and no vendor SDK, so it runs in the main lane on every PR. This is exactly what `StubAdapter` is: a rendition supplied at construction, which is why the toolkit's own adapter and envelope suites run offline against `fixtures/scenario/renditions/widget-report.txt`.
- **Marker-gate the live path.** A second module with `pytest.importorskip("<sdk>")` (or a skip on a missing credential) and a marker registered in `pyproject.toml`'s `[tool.pytest.ini_options] markers`, asserting the same properties against the real service. Its job is to catch the recording going stale, which is the only thing the offline suite cannot see.
- **Re-record deliberately.** A new recording is a baseline change like a golden regeneration: the rendition hash moves, so every fact hash and the envelope hash move with it. Say so in the commit.

**Two traps, both found here.** Injecting only the converter is not enough: `DoclingAdapter(converter=fake)` still raises `PackageNotFoundError` without docling installed, because `extract` reads the installed distribution's metadata to version the rendition. Make the version stamp injectable too, or the offline path is not offline. And a recording committed without the source document proves nothing — the fact's `documentSha256` is over the *bytes*, so the bytes have to be there for the round trip to be checkable.

## What this deliberately does not provide

**No recording harness.** There is no `duly record` command, no cassette format, no HTTP interception. The pattern above is a shape, not a library, and a contributor brings their own mechanism (`vcrpy`, a checked-in JSON dump, a plain text file). This is honest rather than lazy: duly has one shipped adapter and no adopters, so a recording abstraction would be designed against zero real vendor APIs. [M6](../README.md#m6--durable-deployment-and-extraction-evaluation) names recorded-response fixtures as part of a *second production adapter chosen by a real workload* — that is when the shape of the harness becomes knowable.

**No adapter registry and no plugin discovery.** An adapter is a class you import and instantiate. There is no entry point group, no `DULY_ADAPTER` setting, no name-to-class table anywhere in the toolkit — the demo chooses between the two shipped adapters with an explicit branch on a `DULY_DEMO_EXTRACTOR` preference and an import that may fail, and an integrator's code names the adapter it wants. Auto-discovery is the project's preference for *data* (packs, scenarios, ontologies); it is not on offer for executable code that proposes facts.

**No commercial adapters.** Textract, Azure Document Intelligence, Google Document AI: none are here, and their absence is [M6](../README.md#m6--durable-deployment-and-extraction-evaluation)'s item, deliberately gated on a real workload rather than guessed at. Credential handling in particular is unbuilt — the protocol has no place for secrets and an adapter that needs them handles them itself.

**No fact proposal.** The `targets` dict is the boundary: duly does not decide what to assert, and it will not, because that decision belongs to your model and your ontology. What duly holds you to is that whatever you assert is span-faithful, typed, versioned, and revocable as a run.

## CI

The offline suites (`extraction/tests`, 35 passing and 1 skipped module on a plain `uv sync`) run on every push and PR in the main `tests` job, and again in the **deletion gate** with `examples/` removed — which is why they run on `fixtures/`, the corpus the toolkit owns, and never on example content that an adopter deletes. `examples/tests/test_example_extraction.py` is the other half: it asserts the committed *starter* facts are still byte-for-byte what the stub emits, and it is deleted with the starters.

The `docling` marker lane lives in [optional-deps.yml](../.github/workflows/optional-deps.yml) and is the only job in that workflow gated to `schedule` and `workflow_dispatch` — no PR, no push to `main` — because the `extraction` extra pulls torch and costs minutes where the other lanes cost seconds. It runs weekly (Mondays 06:17 UTC). **Run it from the Actions tab before merging anything under `extraction/`**, or locally:

```bash
uv run pytest extraction/tests -q                            # offline: adapters, envelopes, the gate
uv sync --extra extraction && uv run pytest extraction/tests -q -m docling   # live Docling (heavy)
uv run python -m duly_conformance --ontologies <dir> check <facts-dir>       # facts against your ontology
```
