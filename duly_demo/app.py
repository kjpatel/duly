"""duly demo web UI — deterministic document adjudication.

Serves a three-pane demo (document / question+answer / reasoning) plus a small
JSON API. Scenarios come from starters/*/scenario.json when that directory
exists; otherwise a built-in "notice-ny (fixture)" scenario is synthesized from
the committed examples in spec/examples/.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run uvicorn duly_demo.app:app --port 8788
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import tempfile
import threading
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .content import CONTENT

SPEC_EXAMPLES = CONTENT.spec_examples
STARTERS_DIR = CONTENT.starters
TARGETS_DIR = STARTERS_DIR / "tools" / "targets"
GOLDEN_DIR = CONTENT.golden
STATIC_DIR = Path(__file__).resolve().parent / "static"

FIXTURE_RECEIPT_PATH = SPEC_EXAMPLES / "receipt-ny-nonrenewal-notice.json"

FIXTURE_FACT_FILES = [
    "fact-decpage-expiration.json",
    "fact-decpage-state.json",
    "fact-notice-mailed.json",
    "fact-notice-type.json",
]

# The NY nonrenewal pack from spec/rule-ir.md — the pack the committed example
# receipt was produced from. Used so the fixture scenario can go live the moment
# duly_kernel.api.adjudicate exists.
FIXTURE_PACK_YAML = """
pack:
  name: termination-notice-us-states
  version: "2026.2.0"
  ontology: duly-starter-notice
  ontologyVersion: "0.1.0"
  description: State-by-state cancellation/nonrenewal notice compliance.

decisions:
  - attribute: nc:noticeCompliant
    entityType: nc:TerminationNotice
    question: "Was this termination notice compliant?"
    phrasing:
      - when: { value: true, abstained: lowConfidence }
        verdict: "Compliant"
        detail: "{caveat}"
        tone: warn
      - when: { value: true }
        verdict: "Compliant"
        detail:
          - "{daysBetween:noticeMailedDate,policyExpirationDate} days notice given, {derived:requiredMinimumNoticeDays|int} required"
          - "No applicable rule found the notice deficient"
        tone: pos
      - when: { value: false }
        verdict: "Not compliant"
        detail:
          - "{daysBetween:noticeMailedDate,policyExpirationDate} days notice given, {derived:requiredMinimumNoticeDays|int} required"
          - ""
        tone: neg

rules:
  - id: NC-DEF-00
    version: "1.0.0"
    priority: 0
    citation: { text: "Default presumption" }
    effectiveFrom: "1900-01-01"
    given:
      notice: { entityType: nc:TerminationNotice }
    then:
      entity: notice
      attribute: nc:noticeCompliant
      value: { kind: boolean, value: true }

  - id: NY-NR-45
    version: "1.1.0"
    priority: 100
    citation:
      text: "N.Y. Ins. Law § 3425(d)(1)"
      url: "https://www.nysenate.gov/legislation/laws/ISC/3425"
    effectiveFrom: "1986-01-01"
    given:
      notice:     { entityType: nc:TerminationNotice }
      noticeType: { attribute: nc:noticeType }
      state:      { attribute: nc:governingState }
    when:
      - noticeType == "Nonrenewal"
      - state == "US-NY"
    then:
      entity: notice
      attribute: nc:requiredMinimumNoticeDays
      value: { kind: decimal, expr: "45" }

  - id: NC-NR-01
    version: "1.0.2"
    priority: 200
    citation:
      text: "N.Y. Ins. Law § 3425(d)(1)"
      url: "https://www.nysenate.gov/legislation/laws/ISC/3425"
    effectiveFrom: "1986-01-01"
    given:
      notice:     { entityType: nc:TerminationNotice }
      expiration: { attribute: nc:policyExpirationDate }
      mailed:     { attribute: nc:noticeMailedDate }
      minDays:    { derived: nc:requiredMinimumNoticeDays }
    when:
      - days_between(mailed, expiration) < minDays
    then:
      entity: notice
      attribute: nc:noticeCompliant
      value: { kind: boolean, value: false }
    overrides: [NC-DEF-00]
"""

FIXTURE_QUESTIONS = [
    {"attribute": "nc:noticeCompliant", "question": "Was this termination notice compliant?"}
]

FIXTURE_DOC_TITLES = {
    "doc:dec-page:HO-77401-NY:2025-09-01": "Declarations Page — HO-77401-NY",
    "doc:nonrenewal-notice:HO-77401-NY:2026-07-25": "Notice of Nonrenewal — Jul 25, 2026",
}

# Synthesized rendition text per fixture document. Each fact's exact grounding
# quote appears verbatim (and exactly once); spans are recomputed against this
# text at load time so highlighting always lines up.
FIXTURE_RENDITIONS = {
    "doc:dec-page:HO-77401-NY:2025-09-01": "\n".join(
        [
            "ACME MUTUAL INSURANCE COMPANY",
            "HOMEOWNERS POLICY DECLARATIONS",
            "",
            "Policy Number: HO-77401-NY",
            "Named Insured: J. Example",
            "Insured Location: Albany, New York",
            "Agent: Example Agency, Inc., Albany NY",
            "",
            "POLICY PERIOD: 09/01/2025 to 09/01/2026",
            "12:01 A.M. standard time at the residence premises",
            "",
            "Coverage A — Dwelling ................ $ 400,000",
            "Coverage B — Other Structures ........ $  40,000",
            "Annual Premium ....................... $   1,842",
        ]
    ),
    "doc:nonrenewal-notice:HO-77401-NY:2026-07-25": "\n".join(
        [
            "ACME MUTUAL INSURANCE COMPANY",
            "123 Example Plaza, Albany, NY 12207",
            "",
            "NOTICE OF NONRENEWAL",
            "",
            "Re: Homeowners Policy No. HO-77401-NY",
            "Date of Mailing: July 25, 2026",
            "",
            "Dear Policyholder:",
            "",
            "You are hereby notified that the above-numbered policy will not be",
            "renewed beyond its expiration date. This notice is provided pursuant",
            "to the requirements of the New York Insurance Law. If you have any",
            "questions, contact your agent or this company at the address above.",
        ]
    ),
}


def _now_knowledge() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_effective(as_of: str) -> str:
    """Accept 'YYYY-MM-DD' or a full ISO datetime; return an ISO datetime."""
    s = (as_of or "").strip()
    if not s:
        raise HTTPException(status_code=422, detail="asOfEffective is required")
    if "T" in s:
        return s
    try:
        date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Bad asOfEffective date: {s!r}")
    return f"{s}T00:00:00Z"


def _date_prefix(iso: str | None) -> str | None:
    return iso[:10] if iso else None


# ---------------------------------------------------------------------------
# Store-backed runtime: extraction pipeline -> verified envelopes -> FactStore
# ---------------------------------------------------------------------------
#
# At startup (lazily, once per process) the demo runs the extraction pipeline
# over the committed starter documents — the Docling adapter when the optional
# `extraction` extra is installed, the honest scripted stub otherwise — then
# verifies each extraction-run envelope and ingests the facts into an
# in-memory FactStore. Scenario facts are then served from store projections
# (`as_of` at the request's knowledge time; effective-window filtering stays
# the kernel's job, exactly as it is for disk facts) instead of raw disk JSON.
# The stub reproduces the committed starter fact sets byte-identically, so the
# store-backed path changes nothing about existing receipts.
#
# Everything here is per-process and in-memory: review corrections live until
# the server restarts, and the fixture fallback path keeps working without a
# store at all.

# The review arc is **content, not code**. A scenario opts in by carrying a
# `reviewArc` block in its manifest — which attribute to script below the
# floor, at what confidence, and what to call the result — exactly as it opts
# into the stub extractor with `demoExtractor`.
#
# This used to be four constants naming `notice-ny`: a teaching scenario's id
# compiled into the toolkit. Pointing `DULY_DEMO_CONTENT` anywhere else made
# the arc silently not appear, because the ingest is wrapped in
# `except Exception: pass` — and "this deployment has no review scenario" and
# "it has one but we only look for notice-ny" are indistinguishable from
# outside. That is the failure mode that hid the hardcoding.
REVIEW_ID_SUFFIX = "-review"
REVIEW_RUN_ID_TEMPLATE = "run:{scenario}:review-demo"

# Scenario domains group the picker by regulated vertical. The slug comes from
# the starter manifest's optional `domain` field — presentation metadata only,
# deliberately NOT part of the fact contract (the ontology CURIE is the
# contract-level domain signal). Unknown slugs get a title-cased label, so a
# future vertical needs one manifest field and zero code.
DOMAIN_LABELS = {
    "mortgage": "Mortgage closing",
    "insurance": "Insurance",
}
DEFAULT_DOMAIN = "other"


def _domain_fields(slug: str | None) -> dict[str, str]:
    slug = (slug or DEFAULT_DOMAIN).strip().lower() or DEFAULT_DOMAIN
    label = DOMAIN_LABELS.get(slug, slug.replace("-", " ").title())
    return {"domain": slug, "domainLabel": label}


def _review_spec(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """A scenario's `reviewArc` block, validated enough to build from.

    `attribute` and `confidence` are required — without them there is nothing
    to script below the floor, and an arc that abstains over nothing is not a
    demonstration. Everything else has a defensible default.
    """
    block = manifest.get("reviewArc")
    if not isinstance(block, dict):
        return None
    attribute = block.get("attribute")
    confidence = block.get("confidence")
    if not isinstance(attribute, str) or not isinstance(confidence, dict):
        return None
    return {
        "attribute": attribute,
        "confidence": dict(confidence),
        "title": block.get("title") or f"{manifest.get('title', manifest['id'])} — review arc",
        "caseId": block.get("caseId") or f"{manifest['caseId']}:review-demo",
        "defaultAsOf": block.get("defaultAsOf"),
    }

SESSION_NOTE = (
    "Corrections live in this demo process only — the in-memory fact store "
    "resets on restart."
)


class _DemoRuntime:
    """Per-process store-backed demo state (fact store, review queue, and the
    per-scenario extraction records)."""

    def __init__(self, store: Any, queue: Any):
        self.store = store
        self.queue = queue
        # scenario id -> {"caseId", "packPath", "renditions": {docId: text},
        #                 "extraction": {...}}
        self.cases: dict[str, dict[str, Any]] = {}

    def case_meta_for_case_id(self, case_id: str) -> dict[str, Any] | None:
        for meta in self.cases.values():
            if meta["caseId"] == case_id:
                return meta
        return None


_RUNTIME_LOCK = threading.Lock()
_RUNTIME_UNSET = object()
_RUNTIME: Any = _RUNTIME_UNSET


def _reset_runtime() -> None:
    """Drop the cached runtime so the next request rebuilds it (tests use this
    to get a fresh store/queue and to pin the extractor via env)."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = _RUNTIME_UNSET


def _active_runtime() -> _DemoRuntime | None:
    """The per-process runtime, or None when fixture mode is forced or the
    store/extraction packages are unavailable (honest degradation: the demo
    then serves disk facts and disables review affordances with a note)."""
    if os.environ.get("DULY_DEMO_FORCE_FIXTURE") == "1":
        return None
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is _RUNTIME_UNSET:
            _RUNTIME = _build_runtime()
        return _RUNTIME


def _targets_by_document() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if TARGETS_DIR.is_dir():
        for path in sorted(TARGETS_DIR.glob("*.json")):
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(spec, dict) and spec.get("documentId"):
                index[spec["documentId"]] = spec
    return index


def _extraction_meta(result: Any, mode: str, note: str | None = None) -> dict[str, Any]:
    """The UI-facing extraction record: which extractor produced the rendition
    (name + version come off the rendition itself, spec D4), which adapter
    asserted the facts, and where the served facts come from."""
    rendition = result.rendition
    adapter = result.envelope.get("adapter", {})
    label = (
        f"Extracted by {rendition.extractor} {rendition.extractor_version} — "
        "run envelope verified, facts served from the session fact store"
    )
    meta = {
        "source": "store",
        "mode": mode,  # "stub" | "docling"
        "extractor": {"name": rendition.extractor, "version": rendition.extractor_version},
        "adapter": {"name": adapter.get("name"), "version": adapter.get("version")},
        "label": label,
    }
    if note:
        meta["note"] = note
    return meta


def _extract_document(
    document: Any, spec: dict[str, Any], rendition_text: str,
    docling_adapter: Any, stub_cls: Any,
) -> tuple[Any, str, str | None]:
    """Run one document through the preferred adapter.

    Docling when available; if its run fails or skips any target (a quote the
    converter's rendition doesn't contain), fall back to the stub with a note
    rather than silently serving an incomplete fact set — a missing fact would
    turn every dependent question into a no-decision error.
    """
    if docling_adapter is not None:
        try:
            result = docling_adapter.extract(document, spec)
            if not result.skipped:
                return result, "docling", None
            note = (
                f"Docling skipped {len(result.skipped)} target(s); "
                "fell back to the scripted stub"
            )
        except Exception as exc:  # honest fallback, never a broken scenario
            note = f"Docling extraction failed ({type(exc).__name__}); fell back to the scripted stub"
    else:
        note = None
    result = stub_cls(rendition_text).extract(document, spec)
    return result, "stub", note


def _build_runtime() -> _DemoRuntime | None:
    try:
        from duly_extraction.adapter import SourceDocument  # noqa: PLC0415
        from duly_extraction.envelope import ingest_envelope  # noqa: PLC0415
        from duly_extraction.stub import StubAdapter  # noqa: PLC0415
        from duly_review.queue import ReviewQueue  # noqa: PLC0415
        from duly_store.store import FactStore  # noqa: PLC0415
    except Exception:
        return None

    # check_same_thread=False: FastAPI runs sync handlers on a threadpool;
    # sqlite3 serializes access internally (see duly_store.store.FactStore).
    store = FactStore(":memory:", check_same_thread=False)
    store.init_schema()
    queue = ReviewQueue(":memory:", check_same_thread=False)
    queue.init_schema()
    runtime = _DemoRuntime(store, queue)

    targets_by_doc = _targets_by_document()

    docling_adapter = None
    extractor_pref = os.environ.get("DULY_DEMO_EXTRACTOR", "auto")
    if extractor_pref in ("auto", "docling"):
        try:
            import docling  # noqa: F401, PLC0415

            from duly_extraction.docling_adapter import DoclingAdapter  # noqa: PLC0415

            docling_adapter = DoclingAdapter()
        except Exception:
            docling_adapter = None

    if STARTERS_DIR.is_dir():
        for scenario_dir in sorted(STARTERS_DIR.iterdir()):
            manifest_path = scenario_dir / "scenario.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                meta = _ingest_starter_case(
                    runtime, manifest, scenario_dir, targets_by_doc,
                    docling_adapter, StubAdapter, SourceDocument, ingest_envelope,
                )
            except Exception:
                # This scenario stays disk-backed; others still get the store.
                continue
            if meta is not None:
                runtime.cases[manifest.get("id", scenario_dir.name)] = meta

    try:
        _ingest_review_case(
            runtime, targets_by_doc, StubAdapter, SourceDocument, ingest_envelope
        )
    except Exception:
        pass  # the review scenario simply doesn't appear

    return runtime


def _ingest_starter_case(
    runtime: _DemoRuntime, manifest: dict[str, Any], scenario_dir: Path,
    targets_by_doc: dict[str, dict[str, Any]],
    docling_adapter: Any, stub_cls: Any, source_document_cls: Any, ingest_envelope: Any,
) -> dict[str, Any] | None:
    """Extract + verify + ingest one starter scenario. Returns the case meta,
    or None when the manifest lacks what the pipeline needs (that scenario
    then serves its committed disk facts, labeled as such)."""
    case_id = manifest.get("caseId")
    pack_path = manifest.get("rulePack")
    if not case_id or not pack_path:
        return None
    # A manifest may pin the stub extractor ("demoExtractor": "stub") when its
    # targets carry scripted confidences the scenario depends on — Docling
    # measures its own confidence, which would silently overwrite a scripted
    # below-floor value and skip the abstention arc the scenario exists to
    # show. The UI's extraction label names whichever extractor actually ran,
    # so the pin stays visible rather than pretending Docling measured 0.58.
    if manifest.get("demoExtractor") == "stub":
        docling_adapter = None
    meta: dict[str, Any] = {
        "caseId": case_id,
        "packPath": pack_path,
        "renditions": {},
        "extraction": None,
    }
    for doc in manifest.get("documents", []):
        spec = targets_by_doc.get(doc.get("id"))
        pdf_path = _resolve_path(doc.get("pdf", ""), scenario_dir) if doc.get("pdf") else None
        rend_path = (
            _resolve_path(doc.get("rendition", ""), scenario_dir)
            if doc.get("rendition")
            else None
        )
        if spec is None or pdf_path is None or rend_path is None:
            return None
        document = source_document_cls.from_bytes(doc["id"], pdf_path.read_bytes())
        rendition_text = rend_path.read_text(encoding="utf-8")
        result, mode, note = _extract_document(
            document, spec, rendition_text, docling_adapter, stub_cls
        )
        ingest_envelope(runtime.store, result.envelope, result.facts, result.rendition.text)
        meta["renditions"][doc["id"]] = result.rendition.text
        meta["extraction"] = _extraction_meta(result, mode, note)
    if not meta["renditions"]:
        return None
    return meta


def _find_review_source() -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """The first scenario whose manifest opts into the review arc.

    Sorted, so a deployment with two of them gets a stable answer rather than
    a filesystem-order one — the same reason every other discovery here is
    sorted.
    """
    if not STARTERS_DIR.is_dir():
        return None
    for scenario_dir in sorted(STARTERS_DIR.iterdir()):
        manifest_path = scenario_dir / "scenario.json"
        if not scenario_dir.is_dir() or not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        spec = _review_spec(manifest)
        if spec is not None:
            return scenario_dir, manifest, spec
    return None


def _ingest_review_case(
    runtime: _DemoRuntime,
    targets_by_doc: dict[str, dict[str, Any]],
    stub_cls: Any, source_document_cls: Any, ingest_envelope: Any,
) -> None:
    """Ingest the review-arc case: the notice-ny documents re-extracted under a
    separate case id with the mailed date at a below-floor confidence,
    mirroring golden/cases/review-0001.

    Always the scripted stub, even when Docling is installed: the arc needs
    the committed 0.62 score, and the Docling adapter honestly measures its
    own match confidence rather than accepting scripted values — measured
    confidence would clear the floor and defeat the demonstration. The UI
    labels the extractor, so the scripting is visible, not hidden.
    """
    found = _find_review_source()
    if found is None:
        return
    source_dir, manifest, spec_block = found
    scenario_id = f'{manifest["id"]}{REVIEW_ID_SUFFIX}'
    review_case_id = spec_block["caseId"]
    meta: dict[str, Any] = {
        "caseId": review_case_id,
        "reviewSpec": spec_block,
        "sourceId": manifest["id"],
        "packPath": manifest["rulePack"],
        "renditions": {},
        "extraction": None,
        "reviewArc": True,
    }
    for doc in manifest.get("documents", []):
        spec = targets_by_doc.get(doc.get("id"))
        pdf_path = _resolve_path(doc.get("pdf", ""), source_dir) if doc.get("pdf") else None
        rend_path = (
            _resolve_path(doc.get("rendition", ""), source_dir)
            if doc.get("rendition")
            else None
        )
        if spec is None or pdf_path is None or rend_path is None:
            return
        spec = copy.deepcopy(spec)
        spec["caseId"] = review_case_id
        spec["runId"] = REVIEW_RUN_ID_TEMPLATE.format(scenario=manifest["id"])
        for target in spec.get("facts", []):
            if target.get("attribute") == spec_block["attribute"]:
                target["confidence"] = dict(spec_block["confidence"])
        document = source_document_cls.from_bytes(doc["id"], pdf_path.read_bytes())
        rendition_text = rend_path.read_text(encoding="utf-8")
        result = stub_cls(rendition_text).extract(document, spec)
        ingest_envelope(runtime.store, result.envelope, result.facts, result.rendition.text)
        meta["renditions"][doc["id"]] = result.rendition.text
        meta["extraction"] = _extraction_meta(result, "stub")
    if meta["renditions"]:
        runtime.cases[scenario_id] = meta


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


def _build_fixture_scenario() -> dict[str, Any] | None:
    """The built-in NY example, or None when its facts are not present.

    The fixture is content like any other — it reads the committed spec
    examples — so a deployment pointed at its own corpus, or a toolkit with
    `examples/` deleted, simply does not have it. Returning None lets the
    workspace report "no scenarios", which is the honest answer; raising here
    would have made a missing *demonstration* look like a broken server.
    """
    facts: list[dict[str, Any]] = []
    for name in FIXTURE_FACT_FILES:
        path = SPEC_EXAMPLES / name
        if not path.is_file():
            return None
        fact = json.loads(path.read_text())
        grounding = fact.get("grounding", {})
        doc_id = grounding.get("documentId")
        quote = grounding.get("quote")
        if doc_id in FIXTURE_RENDITIONS and quote:
            text = FIXTURE_RENDITIONS[doc_id]
            start = text.index(quote)  # quotes are guaranteed present exactly once
            grounding["charSpan"] = {"start": start, "end": start + len(quote)}
        facts.append(fact)

    documents = {
        doc_id: {
            "id": doc_id,
            "title": FIXTURE_DOC_TITLES.get(doc_id, doc_id),
            "renditionText": text,
        }
        for doc_id, text in FIXTURE_RENDITIONS.items()
    }
    return {
        "id": "notice-ny",
        "title": "notice-ny (fixture)",
        **_domain_fields("insurance"),
        "caseId": "case:policy:HO-77401-NY",
        "documents": documents,
        "facts": facts,
        "pack": yaml.safe_load(FIXTURE_PACK_YAML),
        "questions": list(FIXTURE_QUESTIONS),
        "defaultAsOf": "2026-07-25",
        "source": "fixture",
        "extraction": {
            "source": "fixture",
            "label": "Committed fixture facts from spec/examples — no extraction run",
        },
        "review": {
            "available": False,
            "note": (
                "Review corrections are disabled in fixture mode: there is no "
                "live kernel or session fact store to re-adjudicate against."
            ),
        },
    }


def _resolve_path(raw: str, scenario_dir: Path) -> Path | None:
    for base in (scenario_dir, CONTENT.root):
        candidate = (base / raw).resolve()
        if candidate.exists():
            return candidate
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p
    return None


def _load_starter_scenario(scenario_dir: Path) -> dict[str, Any] | None:
    manifest_path = scenario_dir / "scenario.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    documents: dict[str, dict[str, Any]] = {}
    for doc in manifest.get("documents", []):
        rendition_text = ""
        rend_raw = doc.get("rendition")
        if rend_raw:
            rend_path = _resolve_path(rend_raw, scenario_dir)
            if rend_path is not None:
                try:
                    rendition_text = rend_path.read_text()
                except OSError:
                    rendition_text = ""
        documents[doc["id"]] = {
            "id": doc["id"],
            "title": doc.get("title", doc["id"]),
            "renditionText": rendition_text,
        }

    facts: list[dict[str, Any]] = []
    for fact_raw in manifest.get("facts", []):
        fact_path = _resolve_path(fact_raw, scenario_dir)
        if fact_path is None:
            continue
        try:
            facts.append(json.loads(fact_path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue

    pack = None
    questions: list[dict[str, Any]] = []
    pack_raw = manifest.get("rulePack")
    if pack_raw:
        pack_path = _resolve_path(pack_raw, scenario_dir)
        if pack_path is not None:
            try:
                pack = yaml.safe_load(pack_path.read_text())
            except (OSError, yaml.YAMLError):
                pack = None
    if isinstance(pack, dict):
        for decision in pack.get("decisions", []) or []:
            if isinstance(decision, dict) and decision.get("attribute"):
                questions.append(
                    {
                        "attribute": decision["attribute"],
                        "question": decision.get("question", decision["attribute"]),
                    }
                )

    if not documents or not facts or not questions:
        return None

    effective_dates = sorted(
        d for d in (_date_prefix(f.get("effectiveFrom")) for f in facts) if d
    )
    default_as_of = effective_dates[-1] if effective_dates else date.today().isoformat()

    return {
        "id": manifest.get("id", scenario_dir.name),
        "title": manifest.get("title", scenario_dir.name),
        **_domain_fields(manifest.get("domain")),
        "caseId": manifest.get("caseId", ""),
        "documents": documents,
        "facts": facts,
        "pack": pack,
        "questions": questions,
        "defaultAsOf": default_as_of,
        "source": "starter",
        "extraction": {
            "source": "disk",
            "label": (
                "Committed starter facts loaded from disk — the extraction "
                "pipeline and session fact store are unavailable"
            ),
        },
        "review": {
            "available": False,
            "note": (
                "Review corrections are disabled: this scenario's facts were "
                "loaded from disk, not the session fact store."
            ),
        },
    }


def _questions_from_pack(pack: dict[str, Any] | None) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    if isinstance(pack, dict):
        for decision in pack.get("decisions", []) or []:
            if isinstance(decision, dict) and decision.get("attribute"):
                questions.append(
                    {
                        "attribute": decision["attribute"],
                        "question": decision.get("question", decision["attribute"]),
                    }
                )
    return questions


def _apply_runtime(scenario: dict[str, Any], runtime: _DemoRuntime) -> None:
    """Rewire one scenario onto the session store: facts become an `as_of`
    projection at the current knowledge time, rendition text comes from the
    extraction run that produced the spans (identical to disk for the stub,
    genuinely different for Docling), and the extraction/review labels say so.
    """
    meta = runtime.cases.get(scenario["id"])
    if meta is None or meta["caseId"] != scenario["caseId"]:
        return
    scenario["facts"] = runtime.store.as_of(scenario["caseId"], knowledge=_now_knowledge())
    for doc_id, text in meta["renditions"].items():
        if doc_id in scenario["documents"]:
            scenario["documents"][doc_id]["renditionText"] = text
    if meta.get("extraction"):
        scenario["extraction"] = meta["extraction"]
    scenario["review"] = {"available": True, "note": None}


def _build_review_scenario(runtime: _DemoRuntime) -> dict[str, Any] | None:
    """The review-arc scenario, synthesized from the runtime's ingested case
    (never from starters/ — the below-floor fact set exists only in the
    session store)."""
    scenario_id = next(
        (k for k, v in runtime.cases.items() if v.get("reviewArc")), None
    )
    if scenario_id is None:
        return None
    meta = runtime.cases[scenario_id]
    spec_block = meta["reviewSpec"]
    manifest_path = STARTERS_DIR / meta["sourceId"] / "scenario.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pack = yaml.safe_load((CONTENT.root / meta["packPath"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return None
    questions = _questions_from_pack(pack)
    if not questions:
        return None
    titles = {d["id"]: d.get("title", d["id"]) for d in manifest.get("documents", [])}
    documents = {
        doc_id: {"id": doc_id, "title": titles.get(doc_id, doc_id), "renditionText": text}
        for doc_id, text in meta["renditions"].items()
    }
    return {
        "id": scenario_id,
        "title": spec_block["title"],
        **_domain_fields(manifest.get("domain")),
        "caseId": meta["caseId"],
        "documents": documents,
        "facts": runtime.store.as_of(meta["caseId"], knowledge=_now_knowledge()),
        "pack": pack,
        "questions": questions,
        "defaultAsOf": spec_block.get("defaultAsOf") or manifest.get("defaultAsOf"),
        "source": "review-demo",
        "extraction": meta.get("extraction"),
        "review": {"available": True, "note": None},
    }


def load_scenarios() -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    force_fixture = os.environ.get("DULY_DEMO_FORCE_FIXTURE") == "1"
    if not force_fixture and STARTERS_DIR.is_dir():
        for scenario_dir in sorted(STARTERS_DIR.iterdir()):
            if not scenario_dir.is_dir():
                continue
            if not (scenario_dir / "scenario.json").exists():
                continue
            scenario = _load_starter_scenario(scenario_dir)
            if scenario is not None:
                scenarios[scenario["id"]] = scenario
    runtime = _active_runtime()
    if runtime is not None:
        for scenario in scenarios.values():
            _apply_runtime(scenario, runtime)
        review_scenario = _build_review_scenario(runtime)
        if review_scenario is not None:
            scenarios[review_scenario["id"]] = review_scenario
    if not scenarios:
        fixture = _build_fixture_scenario()
        if fixture is not None:
            scenarios[fixture["id"]] = fixture
    return scenarios


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------


def _run_kernel(
    scenario: dict[str, Any], attribute: str, effective: str, knowledge: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Try the live kernel.

    Returns (receipt, None) on success, (None, message) when the live engine
    ran but legitimately reached no decision at this as-of point, and
    (None, None) when the engine is unavailable or broken (fixture fallback).
    """
    if not isinstance(scenario.get("pack"), dict):
        return None, None
    try:
        import importlib

        importlib.invalidate_caches()  # kernel may appear while we're running
        from duly_kernel.api import adjudicate as kernel_adjudicate  # noqa: PLC0415
    except Exception:
        return None, None
    try:
        receipt = kernel_adjudicate(
            scenario["facts"], scenario["pack"], effective, knowledge, attribute
        )
    except Exception as exc:
        if type(exc).__name__ == "AdjudicationError":
            return None, str(exc)
        return None, None
    return (receipt, None) if isinstance(receipt, dict) else (None, None)


def _format_value(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    kind = value.get("kind")
    if kind == "money":
        return f"{value.get('amount')} {value.get('currency')}"
    if kind == "boolean":
        return "true" if value.get("value") else "false"
    return str(value.get("value"))


# --- Decision phrasing -----------------------------------------------------
#
# How a decision value is worded is *pack data*, not demo code, and the
# renderer of that data is *kernel* code: `duly_kernel.phrasing`. A decision in
# a pack.yaml may carry a `phrasing:` block (spec/rule-ir.md, "Decision
# phrasing"); the kernel validates it in `ir.py` and resolves it in
# `phrasing.py`, and every surface that words a decision for a human — this
# answer line, the audit report's headline verdict — calls that one function.
# It used to live here, which made the demo the only thing that could read a
# pack's own wording: the kernel's report renderer had a domain heuristic
# instead ("if 'compliant' is in the attribute name…"), so the same decision
# came out phrased two different ways depending on which surface you asked.
#
# Adding a rule pack still never means editing this file.
#
# Phrasing is presentation and stays presentation: it is read from the pack the
# demo already has in hand, never written to a receipt, a fact, or anything
# hashed.


def _kernel_determination(
    receipt: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any] | None:
    """The kernel's phrasing verdict, or None when the kernel cannot say.

    Reached lazily like every other kernel call in this module, so the four
    pages still come up when `duly_kernel` is not importable. The cost of that
    degrade is named rather than hidden: a demo with no kernel is already in
    fixture mode, and its answer line falls back to Yes/No below instead of the
    pack's own wording. Nothing is invented; only less is said.
    """
    try:
        from duly_kernel.phrasing import determination  # noqa: PLC0415
    except Exception:
        return None
    return determination(receipt, scenario.get("facts") or [], scenario.get("pack"))


def _determination(
    receipt: dict[str, Any], scenario: dict[str, Any], effective: str
) -> dict[str, Any]:
    """How a decision value is phrased, for the client to render verbatim.

    Returns ``verdict`` (the headline), ``detail`` (one supporting sentence, no
    terminal period) and ``tone`` ("pos" | "neg" | "warn" | ""), so no phrasing
    is duplicated in JavaScript.

    The wording itself comes from the pack, resolved by
    `duly_kernel.phrasing.determination`. What is left here is only this
    surface's fallback for when the pack declares no phrasing that applies: a
    boolean decision falls back to Yes/No, and anything else sets ``generic``
    so the caller renders a raw ``attribute = value`` string rather than
    inventing a verdict it cannot support. The fallback is per-surface on
    purpose — the audit report words the same gap as ``permitted: no``, because
    a report names the attribute it is reporting on.
    """
    phrased = _kernel_determination(receipt, scenario)
    if phrased is not None:
        return phrased

    value = receipt.get("decision", {}).get("value", {})
    if value.get("kind") == "boolean":
        affirmative = bool(value.get("value"))
        return {
            "verdict": "Yes" if affirmative else "No",
            "detail": "",
            "tone": "pos" if affirmative else "neg",
        }

    return {
        "verdict": _format_value(value),
        "detail": "",
        "tone": "",
        "generic": True,
    }


def _render_answer(
    receipt: dict[str, Any], scenario: dict[str, Any], effective: str
) -> str:
    """Flatten the determination into one as-of-dated sentence."""
    decision = receipt.get("decision", {})
    as_of_day = _date_prefix(receipt.get("asOf", {}).get("effective")) or _date_prefix(
        effective
    )
    found = _determination(receipt, scenario, effective)
    if found.get("generic"):
        attribute = decision.get("attribute", "")
        return f"{attribute} = {found['verdict']} as of {as_of_day}."
    if found["detail"]:
        return f"{found['verdict']}: {found['detail']} as of {as_of_day}."
    return f"{found['verdict']} as of {as_of_day}."


def _example_fact_attributes() -> dict[str, str]:
    """factId -> attribute for the committed spec/examples facts (cached)."""
    cache = getattr(_example_fact_attributes, "_cache", None)
    if cache is None:
        cache = {}
        for name in FIXTURE_FACT_FILES:
            try:
                fact = json.loads((SPEC_EXAMPLES / name).read_text())
                cache[fact["id"]] = fact["attribute"]
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        _example_fact_attributes._cache = cache  # type: ignore[attr-defined]
    return cache


def _fact_provenance(fact: dict[str, Any]) -> dict[str, Any] | None:
    """Who asserted the fact, phrased server-side so the client renders it
    verbatim: the extractor for machine facts, the named actor for human ones
    (the review arc's corrected fact shows its reviewer in the derivation)."""
    assertion = fact.get("assertion") or {}
    kind = assertion.get("kind")
    if kind == "human":
        actor = assertion.get("actor") or {}
        label = str(actor.get("id") or "human reviewer")
        if actor.get("role"):
            label += f" ({actor['role']})"
        return {"kind": "human", "label": label}
    if kind == "machine":
        extractor = assertion.get("extractor") or {}
        label = " ".join(
            str(part) for part in (extractor.get("name"), extractor.get("version")) if part
        )
        return {"kind": "machine", "label": label or "machine extractor"}
    return None


def _fact_index_entry(fact: dict[str, Any]) -> dict[str, Any]:
    grounding = fact.get("grounding", {})
    is_doc = grounding.get("kind") == "document"
    return {
        "documentId": grounding.get("documentId") if is_doc else None,
        "charSpan": grounding.get("charSpan") if is_doc else None,
        "quote": grounding.get("quote") if is_doc else None,
        "attribute": fact.get("attribute"),
        "value": fact.get("value"),
        "provenance": _fact_provenance(fact),
    }


def _build_fact_index(
    receipt: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    facts_by_id = {f["id"]: f for f in scenario["facts"] if "id" in f}
    facts_by_attr = {f.get("attribute"): f for f in scenario["facts"]}
    wanted_ids = [
        ref.get("id")
        for ref in receipt.get("inputFacts", []) or []
        if isinstance(ref, dict) and ref.get("id")
    ]
    # Abstained facts are cited by the receipt too (abstentions[].facts); the
    # audit pane links them to their document spans like any other fact.
    for entry in receipt.get("abstentions") or []:
        for fact_id in (entry.get("facts") or []) if isinstance(entry, dict) else []:
            if fact_id not in wanted_ids:
                wanted_ids.append(fact_id)

    index: dict[str, dict[str, Any]] = {}
    for fact_id in wanted_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            # Fixture receipt over regenerated facts: the committed receipt
            # pins spec/examples fact ids while the scenario's fact store was
            # rebuilt with new hashes. Alias by attribute so derivation
            # premises still resolve to a grounded, highlightable fact.
            attr = _example_fact_attributes().get(fact_id)
            fact = facts_by_attr.get(attr) if attr else None
        if fact is not None:
            index[fact_id] = _fact_index_entry(fact)

    if not index:
        index = {
            f["id"]: _fact_index_entry(f) for f in scenario["facts"] if "id" in f
        }
    return index


# ---------------------------------------------------------------------------
# Review state: queue projection, corrections, golden export
# ---------------------------------------------------------------------------
#
# The demo calls the duly_review LIBRARY directly instead of mounting its
# FastAPI surface. Deliberate: the browser sends only a corrected value and a
# reviewer identity, and the GroundedFact correction — content hash, actor
# record, supersession target — must be constructed server-side from the
# machine fact it rules on (the same principle as _determination: the client
# never assembles domain artifacts). Mounting the JSON API would push fact
# construction into JavaScript; the library call keeps the queue's validation
# and the store's custody exactly as duly_review defines them.


def _asserted_fact(store: Any, fact_id: str | None) -> dict[str, Any] | None:
    """The fact document as asserted into the store, via its public history
    API; None when the store never saw it."""
    if not fact_id:
        return None
    for event in store.history(fact_id):
        if event["event_kind"] == "asserted" and event["fact_id"] == fact_id:
            return event["payload"]
    return None


def _resolved_items(runtime: _DemoRuntime, case_id: str) -> list[dict[str, Any]]:
    """Resolved review items for one case, enriched with the correction fact's
    value and actor (looked up from the store — the queue stores no facts)."""
    out: list[dict[str, Any]] = []
    for item in runtime.queue.items(status="resolved", case_id=case_id):
        fact_id = (item.get("resolution") or {}).get("factId")
        correction = _asserted_fact(runtime.store, fact_id)
        out.append(
            {
                "itemId": item["itemId"],
                "attribute": item.get("attribute"),
                "entity": item.get("entity"),
                "resolvedAt": item.get("closedAt"),
                "factId": fact_id,
                "value": correction.get("value") if correction else None,
                "actor": (correction.get("assertion") or {}).get("actor")
                if correction
                else None,
                "supersededFactId": correction.get("supersedes") if correction else None,
            }
        )
    return out


def _calibration_note(pair_count: int) -> str | None:
    if pair_count < 1:
        return None
    pairs = f"{pair_count} labeled calibration pair" + ("s" if pair_count != 1 else "")
    return (
        f"{pairs} collected from resolutions this session. A durable review "
        "queue exports them with `python -m duly_review pairs`; the "
        "duly_calibration module fits calibrators from such pairs (censored "
        "sample: they label below-floor facts only)."
    )


def _review_state(
    scenario: dict[str, Any], receipt: dict[str, Any], engine_mode: str, knowledge: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Route this receipt's abstentions into the session review queue and
    project the case's review state for the UI.

    Returns (review payload, abstention view). The abstention view is the
    receipt's entries verbatim plus, when the queue is live, each entry's
    queue item id and status; the receipt itself is never mutated.
    """
    entries = [e for e in receipt.get("abstentions") or [] if isinstance(e, dict)]
    views = [dict(e) for e in entries]
    review_meta = scenario.get("review") or {}
    runtime = _active_runtime()
    available = bool(review_meta.get("available")) and runtime is not None
    if available and engine_mode != "live":
        available = False
        review_meta = {
            "note": (
                "Review corrections are disabled: the live kernel is "
                "unavailable, so this receipt is a committed fixture that "
                "cannot be re-adjudicated."
            )
        }
    if not available:
        return (
            {
                "available": False,
                "note": review_meta.get("note"),
                "sessionNote": SESSION_NOTE,
                "calibrationPairs": 0,
                "calibrationNote": None,
                "resolved": [],
            },
            views,
        )

    from duly_review.queue import UnknownItemError, item_natural_key  # noqa: PLC0415

    case_id = scenario["caseId"]
    if entries:
        # Idempotent: the item's natural key is (caseId, entry) and entries
        # carry no timestamps, so re-adjudication re-sights the same item.
        runtime.queue.enqueue_receipt(receipt, case_id, recorded_at=knowledge)
    for entry, view in zip(entries, views):
        item_id = item_natural_key(case_id, entry)
        view["itemId"] = item_id
        try:
            view["itemStatus"] = runtime.queue.item(item_id)["status"]
        except UnknownItemError:
            view["itemStatus"] = None
    pair_count = len(runtime.queue.calibration_pairs())
    return (
        {
            "available": True,
            "note": None,
            "sessionNote": SESSION_NOTE,
            "calibrationPairs": pair_count,
            "calibrationNote": _calibration_note(pair_count),
            "resolved": _resolved_items(runtime, case_id),
        },
        views,
    )


def _corrected_value(machine_value: dict[str, Any], raw: str) -> dict[str, Any]:
    """A GroundedFact value for the correction: the machine value's shape with
    the scalar replaced by the reviewer's input, validated per kind. The form
    is deliberately narrow — no free-form JSON."""
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Corrected value is required")
    kind = machine_value.get("kind")
    value = copy.deepcopy(machine_value)
    if kind == "date":
        try:
            date.fromisoformat(raw)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Not a valid ISO date (YYYY-MM-DD): {raw!r}"
            )
        value["value"] = raw
    elif kind == "decimal":
        try:
            Decimal(raw)
        except InvalidOperation:
            raise HTTPException(status_code=422, detail=f"Not a valid decimal: {raw!r}")
        value["value"] = raw
    elif kind == "boolean":
        if raw.lower() not in ("true", "false"):
            raise HTTPException(
                status_code=422, detail=f"Boolean values must be 'true' or 'false', got {raw!r}"
            )
        value["value"] = raw.lower() == "true"
    elif kind in ("string", "code"):
        value["value"] = raw
    else:
        raise HTTPException(
            status_code=422,
            detail=f"The demo correction form cannot edit values of kind {kind!r}",
        )
    return value


def _build_correction_fact(
    machine_fact: dict[str, Any],
    value: dict[str, Any],
    reviewer_id: str,
    reviewer_role: str,
    ts: str,
) -> dict[str, Any]:
    """A human-asserted correction shaped like golden/cases/review-0001's:
    attestation grounding through the review-queue channel, assertion actor
    with id and role (spec D3/D9).

    The correction SUPERSEDES the abstained machine fact. Spec open question 2
    deliberately leaves undecided whether resolve must REQUIRE supersession;
    this demo simply uses the superseding form because it is valid today and
    leaves the cleanest receipt (the below-floor fact drops out of the
    projection, so re-adjudication carries no abstention entry). Nothing here
    enforces a requirement either way.
    """
    from duly_store.store import content_hash  # noqa: PLC0415

    body: dict[str, Any] = {
        "caseId": machine_fact["caseId"],
        "entity": dict(machine_fact["entity"]),
        "attribute": machine_fact["attribute"],
        "value": value,
        "grounding": {
            "kind": "attestation",
            "actor": reviewer_id,
            "channel": "review-queue",
            "at": ts,
        },
        "assertion": {
            "kind": "human",
            "at": ts,
            "actor": {"id": reviewer_id, "role": reviewer_role},
        },
        "recordedAt": ts,
        "status": "asserted",
        "schemaRef": dict(machine_fact["schemaRef"]),
        "supersedes": machine_fact["id"],
    }
    # The human is ruling on the same assertion; its effective window carries.
    for key in ("effectiveFrom", "effectiveTo"):
        if key in machine_fact:
            body[key] = machine_fact[key]
    digest = content_hash(body)
    return {"id": f"urn:duly:fact:sha256:{digest}", "contentHash": digest, **body}


def _reviewer_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="Reviewer name is required")
    return f"reviewer:{slug}"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="duly demo", version="0.0.1")


class AdjudicateRequest(BaseModel):
    scenarioId: str
    attribute: str
    asOfEffective: str


class CorrectionRequest(BaseModel):
    scenarioId: str
    itemId: str
    attribute: str
    asOfEffective: str
    value: str
    reviewerName: str
    reviewerRole: str


def _get_scenario(scenario_id: str) -> dict[str, Any]:
    scenarios = load_scenarios()
    scenario = scenarios.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}")
    return scenario


@app.get("/api/scenarios")
def api_scenarios() -> list[dict[str, Any]]:
    result = []
    for scenario in load_scenarios().values():
        result.append(
            {
                "id": scenario["id"],
                "title": scenario["title"],
                "domain": scenario.get("domain", DEFAULT_DOMAIN),
                "domainLabel": scenario.get("domainLabel")
                or _domain_fields(scenario.get("domain"))["domainLabel"],
                "caseId": scenario["caseId"],
                "documents": [
                    {"id": d["id"], "title": d["title"]}
                    for d in scenario["documents"].values()
                ],
                "questions": scenario["questions"],
                "defaultAsOf": scenario["defaultAsOf"],
                "source": scenario["source"],
                "extraction": scenario.get("extraction"),
                "review": scenario.get("review"),
            }
        )
    return result


def _adjudicate_scenario(
    scenario: dict[str, Any], attribute: str, effective: str, knowledge: str
) -> tuple[dict[str, Any], str]:
    """Run the shared adjudication path (live kernel, fixture fallback).

    Returns (receipt, engineMode); raises HTTPException on no-decision or
    when neither the engine nor a fixture receipt is available.
    """
    receipt, no_decision = _run_kernel(scenario, attribute, effective, knowledge)
    if no_decision is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The engine reached no decision at effective "
                f"{_date_prefix(effective)}: {no_decision}"
            ),
        )
    if receipt is not None:
        return receipt, "live"
    fixture_receipt = json.loads(FIXTURE_RECEIPT_PATH.read_text())
    if scenario.get("caseId") != fixture_receipt.get("caseId"):
        raise HTTPException(
            status_code=503,
            detail=(
                "Engine unavailable (duly_kernel.api.adjudicate not importable) "
                "and no committed fixture receipt exists for this scenario."
            ),
        )
    # The fixture receipt answers exactly one attribute. Serving it for any other
    # question would present an unrelated determination as if it were the answer.
    fixture_attribute = fixture_receipt.get("decision", {}).get("attribute")
    if fixture_attribute != attribute:
        raise HTTPException(
            status_code=503,
            detail=(
                "Engine unavailable (duly_kernel.api.adjudicate not importable). "
                f"The committed fixture receipt only answers {fixture_attribute}, "
                f"so {attribute} cannot be evaluated in fixture mode."
            ),
        )
    return fixture_receipt, "fixture"


def _adjudication_payload(
    scenario: dict[str, Any], receipt: dict[str, Any], engine_mode: str,
    effective: str, knowledge: str,
) -> dict[str, Any]:
    review, abstentions = _review_state(scenario, receipt, engine_mode, knowledge)
    return {
        "receipt": receipt,
        "answer": _render_answer(receipt, scenario, effective),
        "determination": _determination(receipt, scenario, effective),
        "factIndex": _build_fact_index(receipt, scenario),
        "engineMode": engine_mode,
        "abstentions": abstentions,
        "review": review,
        "extraction": scenario.get("extraction"),
    }


@app.post("/api/adjudicate")
def api_adjudicate(body: AdjudicateRequest) -> dict[str, Any]:
    scenario = _get_scenario(body.scenarioId)
    effective = _normalize_effective(body.asOfEffective)
    knowledge = _now_knowledge()

    receipt, engine_mode = _adjudicate_scenario(
        scenario, body.attribute, effective, knowledge
    )

    return _adjudication_payload(scenario, receipt, engine_mode, effective, knowledge)


@app.post("/api/review/correct")
def api_review_correct(body: CorrectionRequest) -> dict[str, Any]:
    """Resolve a low-confidence queue item with a human correction, then
    re-adjudicate and return the flipped decision (same shape as
    /api/adjudicate, plus `resolution`)."""
    runtime = _active_runtime()
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Review corrections are unavailable: the session fact store "
                "is not running (fixture mode serves a committed receipt only)."
            ),
        )
    scenario = _get_scenario(body.scenarioId)
    if not (scenario.get("review") or {}).get("available"):
        raise HTTPException(
            status_code=503,
            detail=(scenario.get("review") or {}).get("note")
            or "Review corrections are disabled for this scenario.",
        )

    from duly_review.queue import (  # noqa: PLC0415
        InvalidCorrectionError,
        InvalidTransitionError,
        ReviewQueueError,
        UnknownItemError,
    )
    from duly_store.store import FactStoreError  # noqa: PLC0415

    try:
        item = runtime.queue.item(body.itemId)
    except UnknownItemError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if item["caseId"] != scenario["caseId"]:
        raise HTTPException(
            status_code=409,
            detail=f"Review item belongs to case {item['caseId']!r}, "
            f"not this scenario's {scenario['caseId']!r}",
        )
    if item["status"] != "open":
        raise HTTPException(
            status_code=409, detail=f"Review item is already {item['status']}"
        )
    fact_ids = item["entry"].get("facts") or []
    if len(fact_ids) != 1:
        raise HTTPException(
            status_code=422,
            detail="Only single-fact (low-confidence) items are correctable "
            "through the demo form",
        )
    machine_fact = _asserted_fact(runtime.store, fact_ids[0])
    if machine_fact is None:
        raise HTTPException(
            status_code=409,
            detail="The abstained fact is not in the session store, so there "
            "is nothing to supersede",
        )

    reviewer_id = _reviewer_id(body.reviewerName)
    reviewer_role = (body.reviewerRole or "").strip()
    if not reviewer_role:
        raise HTTPException(status_code=422, detail="Reviewer role is required")
    value = _corrected_value(machine_fact.get("value") or {}, body.value)
    ts = _now_knowledge()
    correction = _build_correction_fact(machine_fact, value, reviewer_id, reviewer_role, ts)

    try:
        runtime.queue.resolve(body.itemId, correction, runtime.store, ts)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (InvalidCorrectionError, FactStoreError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ReviewQueueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Re-adjudicate from the post-correction projection: reload the scenario
    # so its facts are the store's as-of at a knowledge point that includes
    # the correction (and excludes the superseded machine fact).
    scenario = _get_scenario(body.scenarioId)
    effective = _normalize_effective(body.asOfEffective)
    knowledge = _now_knowledge()
    receipt, engine_mode = _adjudicate_scenario(
        scenario, body.attribute, effective, knowledge
    )
    payload = _adjudication_payload(scenario, receipt, engine_mode, effective, knowledge)
    payload["resolution"] = {
        "itemId": body.itemId,
        "factId": correction["id"],
        "supersededFactId": machine_fact["id"],
        "actor": correction["assertion"]["actor"],
        "recordedAt": ts,
    }
    return payload


@app.get("/api/review/golden-case")
def api_review_golden_case(itemId: str) -> Response:
    """Download a resolved item's golden-case bundle (corpus layout, zipped).

    The server never writes into the repository's golden/ directory —
    committing the bundle is a human act. The case id is the next free
    review-NNNN slot, computed by a read-only scan of the committed corpus.
    """
    runtime = _active_runtime()
    if runtime is None:
        raise HTTPException(
            status_code=503,
            detail="Golden export is unavailable: the session fact store is not running.",
        )
    try:
        from duly_review.golden import (  # noqa: PLC0415
            GoldenCaseError,
            next_review_case_id,
            resolved_item_to_golden_case,
        )
        from duly_review.queue import UnknownItemError  # noqa: PLC0415
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Golden export is unavailable (duly_review.golden not importable).",
        )

    try:
        item = runtime.queue.item(itemId)
    except UnknownItemError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if item["status"] != "resolved":
        raise HTTPException(
            status_code=409,
            detail=f"Only resolved items export as golden cases; this item is "
            f"{item['status']}",
        )
    meta = runtime.case_meta_for_case_id(item["caseId"])
    if meta is None:
        raise HTTPException(
            status_code=409,
            detail=f"No demo scenario is backed by case {item['caseId']!r}",
        )

    case_id = next_review_case_id(GOLDEN_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            resolved_item_to_golden_case(
                runtime.queue,
                runtime.store,
                itemId,
                pack_path=meta["packPath"],
                golden_dir=tmp,
                repo_root=CONTENT.root,
                case_id=case_id,
            )
        except GoldenCaseError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(Path(tmp).rglob("*")):
                if path.is_file():
                    # ZipInfo without a date_time pins the DOS epoch — the
                    # bundle bytes depend only on the case content.
                    info = zipfile.ZipInfo(str(path.relative_to(tmp)))
                    bundle.writestr(info, path.read_bytes())
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="golden-case-{case_id}.zip"'
        },
    )


@app.get("/api/report")
def api_report(
    scenarioId: str, attribute: str, asOfEffective: str, format: str = "md"
) -> Response:
    """Adjudicate (same path as /api/adjudicate) and return a downloadable
    export: the audit report as Markdown or PDF, the receipt and the facts it
    was adjudicated over as one self-contained bundle (format=bundle), or the
    receipt as PROV-O JSON-LD (format=jsonld — machine consumers only,
    deliberately no UI button; see spec/prov-o.md)."""
    if format not in ("md", "pdf", "jsonld", "bundle", "receipt"):
        raise HTTPException(
            status_code=422,
            detail=(
                "format must be 'md', 'pdf', 'jsonld', 'bundle', or 'receipt', "
                f"got {format!r}"
            ),
        )
    scenario = _get_scenario(scenarioId)
    effective = _normalize_effective(asOfEffective)
    knowledge = _now_knowledge()

    receipt, _engine_mode = _adjudicate_scenario(
        scenario, attribute, effective, knowledge
    )

    if format == "receipt":
        # Served from here rather than assembled in the browser, and the
        # reason is not tidiness. `abstentions[].confidence.score` and
        # `abstentions[].threshold.minConfidence` are JSON numbers in the
        # receipt schema, and JavaScript has one number type: a receipt
        # carrying a score of 1.0 came back out of `JSON.stringify` as 1,
        # a different canonical body, and the download failed its own hash
        # check in the receipt viewer. Nothing warned, because the scenarios
        # whose floors and scores are not integral round-trip fine.
        filename = f"duly-receipt-{scenarioId}-{_date_prefix(effective)}.json"
        return Response(
            content=json.dumps(receipt, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "bundle":
        # The receipt and the exact fact set it was adjudicated over, in one
        # file. Three things about the shape, each load-bearing:
        #
        # A JSON *array*, and the documents go in verbatim. A receipt's hash
        # is over its own bytes, so a bundle that put facts *inside* the
        # receipt would produce a document whose receiptSha256 no longer
        # matches its body — an export wraps, it never edits.
        #
        # Every fact adjudicate() saw, not just the ones in `inputFacts`.
        # Abstention entries are computed over the whole live fact set, so a
        # below-floor fact shapes the receipt without ever binding: replay it
        # from `inputFacts` alone and the abstention disappears, taking byte
        # equality with it.
        #
        # Serialized *here*. JavaScript has one number type, so a bundle
        # assembled in the browser would rewrite a fact's `"score": 1.0` as
        # `1` and break every hash it carries (duly_demo/CLAUDE.md).
        filename = f"duly-bundle-{scenarioId}-{_date_prefix(effective)}.json"
        return Response(
            content=json.dumps(
                [receipt, *scenario["facts"]], indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "jsonld":
        try:
            from duly_kernel.provo import as_jsonld  # noqa: PLC0415
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="PROV-O exporter unavailable (duly_kernel.provo not importable).",
            )
        filename = f"duly-receipt-{scenarioId}-{_date_prefix(effective)}.jsonld"
        return Response(
            content=json.dumps(as_jsonld(receipt, "receipt"), indent=2),
            media_type="application/ld+json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    try:
        from duly_kernel.report import (  # noqa: PLC0415
            render_report_markdown,
            render_report_pdf,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Report renderer unavailable (duly_kernel.report not importable).",
        )

    facts = scenario["facts"]
    pack = scenario.get("pack") if isinstance(scenario.get("pack"), dict) else None
    if format == "md":
        content: bytes = render_report_markdown(receipt, facts, pack).encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
    else:
        content = render_report_pdf(receipt, facts, pack)
        media_type = "application/pdf"

    filename = f"duly-audit-{scenarioId}-{_date_prefix(effective)}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/document/{scenario_id}/{document_id}")
def api_document(scenario_id: str, document_id: str) -> dict[str, Any]:
    scenario = _get_scenario(scenario_id)
    doc = scenario["documents"].get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Unknown document: {document_id}")
    return {"title": doc["title"], "renditionText": doc["renditionText"]}


# The Rule Studio: browse, edit and test the rule packs themselves. It ships
# as its own module because it shares nothing with adjudication but the kernel
# — different artifacts (packs, not cases), different verbs (draft and prove,
# not answer). Mounted here rather than run standalone so one `uvicorn
# duly_demo.app:app` still starts the whole demonstration.
from . import rules_api  # noqa: E402, PLC0415

app.include_router(rules_api.router)


@app.get("/rules")
def rules_studio() -> Response:
    return Response(
        content=(STATIC_DIR / "rules.html").read_bytes(), media_type="text/html"
    )


# The Evidence Browser: the case's documents and grounded facts as objects in
# their own right, at a knowledge time you choose. Separate module for the same
# reason as the studio — the workspace is scoped to one question's receipt, and
# this is scoped to everything the store holds, which is a different projection
# of the same case rather than a bigger version of the same pane.
from . import evidence_api  # noqa: E402, PLC0415

app.include_router(evidence_api.router)


@app.get("/evidence")
def evidence_browser() -> Response:
    return Response(
        content=(STATIC_DIR / "evidence.html").read_bytes(), media_type="text/html"
    )


# The Receipt viewer: open a receipt that already exists and check whether it
# holds. Mounted alongside the workspace for the same reason as the studio —
# it shares only the kernel with adjudication, and reaches it from the other
# end: the workspace produces a receipt, this reads one back.
from . import receipts_api  # noqa: E402, PLC0415

app.include_router(receipts_api.router)


@app.get("/receipt")
def receipt_viewer() -> Response:
    return Response(
        content=(STATIC_DIR / "receipt.html").read_bytes(), media_type="text/html"
    )


class _RevalidatingStatics(StaticFiles):
    """StaticFiles that always revalidates instead of letting the browser guess.

    Starlette sends `etag` and `last-modified` but no `cache-control`. With no
    directive a browser falls back to *heuristic freshness* — it invents an
    expiry (commonly a fraction of the age since `last-modified`) and serves
    from cache without asking. That is how a stale stylesheet renders against
    new markup, and it is invisible to whoever deployed it, because their own
    browser holds the fresh copy.

    `no-cache` does not disable caching; it requires revalidation. The etag
    still does the real work — a matching request comes back 304 with no body —
    so this costs one conditional request per asset and removes the class of
    bug entirely. Correctness over a saved round trip: this is a demo whose
    whole claim is that what you see is what the kernel did.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("cache-control", "no-cache")
        return response


app.mount("/", _RevalidatingStatics(directory=str(STATIC_DIR), html=True), name="static")
