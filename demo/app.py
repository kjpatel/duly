"""duly demo web UI — deterministic document adjudication.

Serves a three-pane demo (document / question+answer / reasoning) plus a small
JSON API. Scenarios come from starters/*/scenario.json when that directory
exists; otherwise a built-in "notice-ny (fixture)" scenario is synthesized from
the committed examples in spec/examples/.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run uvicorn demo.app:app --port 8788
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_EXAMPLES = REPO_ROOT / "spec" / "examples"
STARTERS_DIR = REPO_ROOT / "starters"
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
# Scenario loading
# ---------------------------------------------------------------------------


def _build_fixture_scenario() -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    for name in FIXTURE_FACT_FILES:
        fact = json.loads((SPEC_EXAMPLES / name).read_text())
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
        "caseId": "case:policy:HO-77401-NY",
        "documents": documents,
        "facts": facts,
        "pack": yaml.safe_load(FIXTURE_PACK_YAML),
        "questions": list(FIXTURE_QUESTIONS),
        "defaultAsOf": "2026-07-25",
        "source": "fixture",
    }


def _resolve_path(raw: str, scenario_dir: Path) -> Path | None:
    for base in (scenario_dir, REPO_ROOT):
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
        "caseId": manifest.get("caseId", ""),
        "documents": documents,
        "facts": facts,
        "pack": pack,
        "questions": questions,
        "defaultAsOf": default_as_of,
        "source": "starter",
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
    if not scenarios:
        fixture = _build_fixture_scenario()
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


def _find_derived_value(node: Any, attribute_suffix: str) -> dict[str, Any] | None:
    """Depth-first search of a derivation tree for a conclusion on an attribute."""
    if not isinstance(node, dict):
        return None
    conclusion = node.get("conclusion")
    if isinstance(conclusion, dict):
        attr = conclusion.get("attribute", "")
        if attr == attribute_suffix or attr.endswith(":" + attribute_suffix):
            return conclusion.get("value")
    for premise in node.get("premises", []) or []:
        found = _find_derived_value(premise, attribute_suffix)
        if found is not None:
            return found
    return None


def _fact_value(facts: list[dict[str, Any]], attribute_suffix: str) -> Any:
    for fact in facts:
        attr = fact.get("attribute", "")
        if attr == attribute_suffix or attr.endswith(":" + attribute_suffix):
            value = fact.get("value", {})
            return value.get("value")
    return None


def _format_value(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    kind = value.get("kind")
    if kind == "money":
        return f"{value.get('amount')} {value.get('currency')}"
    if kind == "boolean":
        return "true" if value.get("value") else "false"
    return str(value.get("value"))


def _render_answer(
    receipt: dict[str, Any], scenario: dict[str, Any], effective: str
) -> str:
    decision = receipt.get("decision", {})
    attribute = decision.get("attribute", "")
    value = decision.get("value", {})
    as_of_day = _date_prefix(receipt.get("asOf", {}).get("effective")) or _date_prefix(
        effective
    )

    if attribute.endswith("noticeCompliant") and value.get("kind") == "boolean":
        compliant = bool(value.get("value"))
        mailed = _fact_value(scenario["facts"], "noticeMailedDate")
        expiration = _fact_value(scenario["facts"], "policyExpirationDate")
        min_days_value = _find_derived_value(
            receipt.get("derivation"), "requiredMinimumNoticeDays"
        )
        days_given = None
        if mailed and expiration:
            try:
                days_given = (
                    date.fromisoformat(str(expiration)[:10])
                    - date.fromisoformat(str(mailed)[:10])
                ).days
            except ValueError:
                days_given = None
        min_days = None
        if isinstance(min_days_value, dict):
            raw = min_days_value.get("value")
            try:
                min_days = int(float(raw))
            except (TypeError, ValueError):
                min_days = None
        if days_given is not None and min_days is not None:
            if compliant:
                return f"Compliant: {days_given} days notice given, {min_days} required."
            return f"Not compliant: {days_given} days notice given, {min_days} required."
        if compliant:
            return (
                f"Compliant: no applicable rule found the notice deficient "
                f"as of {as_of_day}."
            )
        return f"Not compliant as of {as_of_day}."

    return f"{attribute} = {_format_value(value)} as of {as_of_day}."


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


def _fact_index_entry(fact: dict[str, Any]) -> dict[str, Any]:
    grounding = fact.get("grounding", {})
    is_doc = grounding.get("kind") == "document"
    return {
        "documentId": grounding.get("documentId") if is_doc else None,
        "charSpan": grounding.get("charSpan") if is_doc else None,
        "quote": grounding.get("quote") if is_doc else None,
        "attribute": fact.get("attribute"),
        "value": fact.get("value"),
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
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="duly demo", version="0.0.1")


class AdjudicateRequest(BaseModel):
    scenarioId: str
    attribute: str
    asOfEffective: str


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
                "caseId": scenario["caseId"],
                "documents": [
                    {"id": d["id"], "title": d["title"]}
                    for d in scenario["documents"].values()
                ],
                "questions": scenario["questions"],
                "defaultAsOf": scenario["defaultAsOf"],
                "source": scenario["source"],
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
    return fixture_receipt, "fixture"


@app.post("/api/adjudicate")
def api_adjudicate(body: AdjudicateRequest) -> dict[str, Any]:
    scenario = _get_scenario(body.scenarioId)
    effective = _normalize_effective(body.asOfEffective)
    knowledge = _now_knowledge()

    receipt, engine_mode = _adjudicate_scenario(
        scenario, body.attribute, effective, knowledge
    )

    return {
        "receipt": receipt,
        "answer": _render_answer(receipt, scenario, effective),
        "factIndex": _build_fact_index(receipt, scenario),
        "engineMode": engine_mode,
    }


@app.get("/api/report")
def api_report(
    scenarioId: str, attribute: str, asOfEffective: str, format: str = "md"
) -> Response:
    """Adjudicate (same path as /api/adjudicate) and return the rendered
    audit report as a downloadable Markdown or PDF file."""
    if format not in ("md", "pdf"):
        raise HTTPException(
            status_code=422, detail=f"format must be 'md' or 'pdf', got {format!r}"
        )
    scenario = _get_scenario(scenarioId)
    effective = _normalize_effective(asOfEffective)
    knowledge = _now_knowledge()

    receipt, _engine_mode = _adjudicate_scenario(
        scenario, attribute, effective, knowledge
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


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
