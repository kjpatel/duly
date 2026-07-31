"""Evidence Browser — the demo's document and grounded-fact API.

The decision workspace shows the facts a *receipt* cited: the evidence for one
question, at one moment, filtered by what the rules happened to need. That is
the right frame for reading a decision and the wrong one for reading a case.
This module serves the other frame — every document the case holds, every fact
ever asserted about it, and the knowledge time you are looking from.

Three stances hold it together, and each of them is a refusal:

**The document has two faces and the browser never blurs them.** A fact's
grounding cites a `documentSha256` — the bytes — and a `charSpan` into a
*rendition*, which is one extractor's reading of those bytes. Both are served,
side by side, and spans are drawn only on the rendition. An overlay on the PDF
would need coordinates no fact carries; drawing one from character offsets
would be a guess wearing the costume of provenance.

**Liveness is recomputed, so that it can be compared.** `FactStore.as_of`
already projects a case at a knowledge horizon, and this module could simply
call it. Instead it replays the event log itself and classifies every fact as
live, superseded, retracted or not-yet-known — because a browser that only
shows survivors cannot show supersession, which is the thing worth seeing. The
two projections must agree; `test_evidence_api.py` walks every case at every
point on its timeline and asserts they do. A divergence is a bug in the store
or a bug here, and both matter.

**Documents resolve by id, never by path.** The client names a document id; the
server looks it up in an index built from the committed starter manifests. No
path from a request ever reaches the filesystem.

Everything degrades honestly. Without the session fact store there is no event
log, so the timeline is empty and says why rather than inventing a single point
that implies knowledge never changed. Without `duly_conformance` the ontology
panel says the checker is unavailable instead of implying a fact conforms.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

REPO_ROOT = Path(__file__).resolve().parent.parent
STARTERS_DIR = REPO_ROOT / "starters"
ONTOLOGIES_DIR = REPO_ROOT / "ontologies"

router = APIRouter(prefix="/api/evidence")

# A fixed far-future horizon, used to ask the store for "everything ever
# recorded". A wall-clock read would work today and drift into a
# nondeterministic test tomorrow; the whole repo forbids one in library code
# and the demo keeps the habit.
MAX_KNOWLEDGE = "9999-12-31T23:59:59Z"

NO_STORE_NOTE = (
    "These facts were loaded from disk, not from the session fact store, so "
    "this case has no event log: no knowledge timeline, no supersession, no "
    "history. Start the demo with the extraction pipeline available to see "
    "facts arrive and be superseded."
)

FACT_STATES = ("live", "superseded", "retracted", "future")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
#
# demo/app.py includes this router at the bottom of its own module body, so a
# top-level `from demo.app import ...` here would import a half-built module.
# The accessor keeps the cycle honest and local.


def _demo() -> Any:
    from demo import app as demo_app  # noqa: PLC0415

    return demo_app


def _get_scenario(scenario_id: str) -> dict[str, Any]:
    scenario = _demo().load_scenarios().get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown case: {scenario_id}")
    return scenario


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------


def _point(s: str) -> _dt.datetime:
    """Parse an ISO-8601 point to UTC. Mirrors ``duly_store.store._parse_point``
    (a bare date is midnight UTC, a naive datetime is UTC) — deliberately a
    second implementation, since comparing this module's projection with the
    store's is only a check if the store's own comparator is not the thing
    being reused."""
    try:
        d = _dt.date.fromisoformat(s)
    except ValueError:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc)
    return _dt.datetime.combine(d, _dt.time(0, 0, 0), tzinfo=_dt.timezone.utc)


def _valid_point(raw: str | None, field: str) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        _point(raw.strip())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Bad {field}: {raw!r}")
    return raw.strip()


# ---------------------------------------------------------------------------
# Document index: id -> committed source bytes
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_DOC_INDEX: dict[str, dict[str, Any]] | None = None
_REGISTRY: Any = None
_REGISTRY_LOADED = False


def reset_caches() -> None:
    """Drop the document index and ontology registry (tests call this)."""
    global _DOC_INDEX, _REGISTRY, _REGISTRY_LOADED
    with _CACHE_LOCK:
        _DOC_INDEX = None
        _REGISTRY = None
        _REGISTRY_LOADED = False


def _build_document_index() -> dict[str, dict[str, Any]]:
    """Every document any starter manifest declares, keyed by document id.

    The manifest's `sha256` is what the facts' groundings cite; the file on
    disk is hashed on read and the two are compared, so a document whose bytes
    drifted from the manifest is reported as unverified rather than served as
    if it were the thing the fact points at.
    """
    index: dict[str, dict[str, Any]] = {}
    if not STARTERS_DIR.is_dir():
        return index
    for manifest_path in sorted(STARTERS_DIR.glob("*/scenario.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for doc in manifest.get("documents", []) or []:
            doc_id = doc.get("id")
            raw = doc.get("pdf")
            if not doc_id or not raw:
                continue
            path = (manifest_path.parent / raw).resolve()
            if not path.is_file():
                continue
            index[doc_id] = {
                "path": path,
                "title": doc.get("title", doc_id),
                "declaredSha256": doc.get("sha256"),
                "bytes": path.stat().st_size,
            }
    return index


def _document_index() -> dict[str, dict[str, Any]]:
    global _DOC_INDEX
    with _CACHE_LOCK:
        if _DOC_INDEX is None:
            _DOC_INDEX = _build_document_index()
        return _DOC_INDEX


def _source_meta(document_id: str) -> dict[str, Any]:
    """The source-bytes record for a document id: whether committed bytes exist
    and whether they still hash to what the manifest declared."""
    entry = _document_index().get(document_id)
    if entry is None:
        return {"available": False, "sha256": None, "verified": None, "bytes": None}
    try:
        actual = hashlib.sha256(entry["path"].read_bytes()).hexdigest()
    except OSError:
        return {"available": False, "sha256": None, "verified": None, "bytes": None}
    declared = entry.get("declaredSha256")
    return {
        "available": True,
        "sha256": actual,
        "declaredSha256": declared,
        "verified": None if not declared else declared == actual,
        "bytes": entry["bytes"],
    }


# ---------------------------------------------------------------------------
# The event log, replayed
# ---------------------------------------------------------------------------


def _case_events(store: Any, case_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Every event touching this case, and every fact it ever asserted.

    ``FactStore`` exposes no "all facts in this case" projection on purpose —
    it answers questions about a horizon, not about the whole log. So the walk
    seeds from the facts live at the far-future horizon and follows each one's
    supersession chain, which ``history`` walks in both directions. A fact
    retracted without replacement is therefore unreachable from any live fact
    and does not appear; nothing in the demo retracts, and the alternative is
    reaching past the store's public API to get it.
    """
    events: dict[int, dict[str, Any]] = {}
    for fact in store.as_of(case_id, knowledge=MAX_KNOWLEDGE):
        for event in store.history(fact["id"]):
            if event.get("case_id") != case_id:
                continue  # a chain that leaves the case is not this case's log
            events[event["event_id"]] = event
    ordered = [events[key] for key in sorted(events)]
    asserted = {
        event["fact_id"]: event["payload"]
        for event in ordered
        if event["event_kind"] == "asserted"
    }
    return ordered, asserted


def _timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per distinct recorded-at, labelled with what happened then.

    These are the only moments the case's knowledge changed, which is why the
    UI offers them as discrete stops rather than a free date field: every date
    in between is the same answer, and the dates that matter are exactly these.
    """
    by_point: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_point.setdefault(event["recorded_at"], []).append(event)

    timeline = []
    for at in sorted(by_point, key=_point):
        group = by_point[at]
        kinds = {kind: 0 for kind in ("asserted", "superseded", "retracted")}
        for event in group:
            kinds[event["event_kind"]] = kinds.get(event["event_kind"], 0) + 1
        parts = []
        if kinds["asserted"]:
            parts.append(_plural(kinds["asserted"], "fact") + " asserted")
        if kinds["superseded"]:
            parts.append(_plural(kinds["superseded"], "fact") + " superseded")
        if kinds["retracted"]:
            parts.append(_plural(kinds["retracted"], "fact") + " retracted")
        timeline.append(
            {
                "at": at,
                "label": ", ".join(parts) or "no change",
                "asserted": kinds["asserted"],
                "superseded": kinds["superseded"],
                "retracted": kinds["retracted"],
            }
        )
    return timeline


def _plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural_form or singular + 's')}"


def _states_at(
    events: list[dict[str, Any]], asserted: dict[str, dict[str, Any]], knowledge: str
) -> dict[str, dict[str, Any]]:
    """Classify every fact of the case as of ``knowledge``.

    Deliberately *not* delegated to ``FactStore.as_of``: see the module
    docstring. as_of answers "which facts survive", this answers "what became
    of each fact", and the second question is the one a browser is for.
    """
    horizon = _point(knowledge)
    states: dict[str, dict[str, Any]] = {}
    for fact_id, payload in asserted.items():
        states[fact_id] = {
            "state": "live",
            "recordedAt": payload.get("recordedAt"),
            "supersedes": payload.get("supersedes"),
            "supersededBy": None,
            "retractedAt": None,
        }

    for event in events:
        fact_id = event["fact_id"]
        entry = states.get(fact_id)
        if entry is None:
            continue
        recorded = event["recorded_at"]
        if event["event_kind"] == "asserted":
            if _point(recorded) > horizon:
                entry["state"] = "future"
            continue
        if _point(recorded) > horizon:
            # The supersession has not happened yet at this horizon; the fact
            # is still live, and the UI shows the supersession as pending.
            if event["event_kind"] == "superseded" and entry["supersededBy"] is None:
                entry["pendingSupersededBy"] = event.get("supersedes")
            continue
        if entry["state"] == "future":
            continue
        if event["event_kind"] == "superseded":
            entry["state"] = "superseded"
            entry["supersededBy"] = event.get("supersedes")
        elif event["event_kind"] == "retracted":
            entry["state"] = "retracted"
            entry["retractedAt"] = recorded
    return states


# ---------------------------------------------------------------------------
# Fact records
# ---------------------------------------------------------------------------


def _fact_record(
    fact: dict[str, Any],
    state: dict[str, Any] | None,
    documents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """A fact, wrapped for the browser — never edited.

    The fact document goes out verbatim under `fact`; everything the UI needs
    that is not in the fact (its state at this horizon, the document's title)
    sits beside it. Adding a key in place would change the bytes the content
    hash is over, which is the one thing a fact browser must not do.
    """
    grounding = fact.get("grounding") or {}
    document_id = grounding.get("documentId") if grounding.get("kind") == "document" else None
    document = documents.get(document_id) if document_id else None
    confidence = fact.get("confidence") or {}
    return {
        "id": fact.get("id"),
        "fact": fact,
        "attribute": fact.get("attribute"),
        "entity": fact.get("entity"),
        "value": fact.get("value"),
        "state": (state or {}).get("state", "live"),
        "recordedAt": fact.get("recordedAt"),
        "supersedes": fact.get("supersedes"),
        "supersededBy": (state or {}).get("supersededBy"),
        "pendingSupersededBy": (state or {}).get("pendingSupersededBy"),
        "retractedAt": (state or {}).get("retractedAt"),
        "assertionKind": (fact.get("assertion") or {}).get("kind"),
        "provenance": _demo()._fact_provenance(fact),
        "confidence": {
            "score": confidence.get("score"),
            "method": confidence.get("method"),
            "calibrationRef": confidence.get("calibrationRef"),
        }
        if confidence
        else None,
        "schemaRef": fact.get("schemaRef"),
        "contentHash": fact.get("contentHash"),
        "effectiveFrom": fact.get("effectiveFrom"),
        "effectiveTo": fact.get("effectiveTo"),
        "document": {"id": document_id, "title": document["title"]} if document else None,
        "documentSha256": grounding.get("documentSha256"),
        "page": grounding.get("page"),
        "charSpan": grounding.get("charSpan"),
        "quote": grounding.get("quote"),
        "rendition": grounding.get("rendition"),
        "groundingKind": grounding.get("kind"),
        # Whatever else this grounding kind carries — a review-queue
        # attestation names an actor and a channel, and a browser that only
        # understood document groundings would show a human correction as
        # ungrounded rather than as grounded in an attestation.
        "groundingDetail": {
            key: value
            for key, value in grounding.items()
            if key
            not in (
                "kind",
                "documentId",
                "documentSha256",
                "rendition",
                "page",
                "charSpan",
                "quote",
            )
        },
    }


# ---------------------------------------------------------------------------
# Ontology conformance
# ---------------------------------------------------------------------------


def _registry() -> Any:
    global _REGISTRY, _REGISTRY_LOADED
    with _CACHE_LOCK:
        if not _REGISTRY_LOADED:
            _REGISTRY_LOADED = True
            try:
                from duly_conformance.registry import load_repo_registry  # noqa: PLC0415

                _REGISTRY = load_repo_registry(ONTOLOGIES_DIR)
            except Exception:
                _REGISTRY = None
        return _REGISTRY


def _slot_record(slot: Any, owner: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "curie": slot.curie,
        "name": slot.name,
        "kind": slot.kind,
        "required": slot.required,
        "declaredOn": owner.curie,
    }
    if slot.enum is not None:
        record["enum"] = {
            "name": slot.enum.name,
            "codeSystem": slot.enum.code_system,
            "openCodeSet": slot.enum.open_code_set,
            "values": sorted(slot.enum.values),
        }
    return record


def _conformance(fact: dict[str, Any]) -> dict[str, Any]:
    """This fact against the ontology its own `schemaRef` pins.

    The gate is the same one CI runs over every committed fact
    (`python -m duly_conformance check`), so a green badge here means exactly
    what a green gate means — no more.
    """
    registry = _registry()
    schema_ref = fact.get("schemaRef") or {}
    ref = f"{schema_ref.get('ontology')}@{schema_ref.get('version')}"
    if registry is None:
        return {
            "available": False,
            "ref": ref,
            "note": "The conformance checker is unavailable, so this fact's "
            "ontology has not been consulted.",
        }
    try:
        from duly_conformance.gate import check_fact  # noqa: PLC0415

        issues = check_fact(fact, registry)
    except Exception as exc:
        return {"available": False, "ref": ref, "note": f"Conformance check failed: {exc}"}

    record: dict[str, Any] = {
        "available": True,
        "ref": ref,
        "conformant": not issues,
        "issues": [{"code": i.code, "message": i.message} for i in issues],
        "slot": None,
        "entityType": (fact.get("entity") or {}).get("type"),
    }
    ontology = registry.get(schema_ref.get("ontology"), schema_ref.get("version"))
    if ontology is not None:
        found = ontology.find_slot(fact.get("attribute"))
        if found is not None:
            owner, slot = found
            record["slot"] = _slot_record(slot, owner)
    return record


# ---------------------------------------------------------------------------
# Citations: which questions actually used this fact
# ---------------------------------------------------------------------------


def _citations(
    scenario: dict[str, Any],
    facts: list[dict[str, Any]],
    fact_id: str,
    effective: str,
    knowledge: str,
) -> dict[str, Any]:
    """Every question of this case's pack, and this fact's role in answering it.

    Adjudicated against the projection at the *selected* knowledge time, not
    the current one — otherwise dragging the timeline would move the facts a
    reader sees while leaving the citations describing a different world.
    """
    demo = _demo()
    questions = scenario.get("questions") or []
    if not questions:
        return {"available": False, "note": "This case's pack declares no questions."}

    at_knowledge = dict(scenario)
    at_knowledge["facts"] = facts

    results = []
    engine_ran = False
    for question in questions:
        attribute = question["attribute"]
        receipt, no_decision = demo._run_kernel(
            at_knowledge, attribute, effective, knowledge
        )
        if receipt is None:
            results.append(
                {
                    "attribute": attribute,
                    "question": question.get("question", attribute),
                    "role": None,
                    "note": no_decision or "The engine reached no decision here.",
                }
            )
            continue
        engine_ran = True
        input_ids = {
            ref.get("id")
            for ref in receipt.get("inputFacts") or []
            if isinstance(ref, dict)
        }
        abstained_ids = {
            fid
            for entry in receipt.get("abstentions") or []
            if isinstance(entry, dict)
            for fid in entry.get("facts") or []
        }
        if fact_id in abstained_ids:
            role = "abstained"
        elif fact_id in input_ids:
            role = "input"
        else:
            role = None
        results.append(
            {
                "attribute": attribute,
                "question": question.get("question", attribute),
                "role": role,
                "decision": receipt.get("decision", {}).get("value"),
            }
        )
    if not engine_ran:
        return {
            "available": False,
            "note": "The kernel is unavailable, so which questions cite this "
            "fact cannot be determined.",
            "questions": results,
        }
    return {"available": True, "effective": effective, "questions": results}


# ---------------------------------------------------------------------------
# Case assembly
# ---------------------------------------------------------------------------


def _case_projection(
    scenario: dict[str, Any], knowledge: str | None
) -> dict[str, Any]:
    """The case at a knowledge horizon: documents, facts, states, timeline.

    Two shapes come out of here. Store-backed: a real event log, a timeline,
    and facts that can be superseded or not-yet-known. Disk-backed (no session
    store, or fixture mode): the committed facts, all live, and a note saying
    the timeline is absent rather than empty-because-nothing-happened.
    """
    demo = _demo()
    runtime = demo._active_runtime()
    meta = runtime.cases.get(scenario["id"]) if runtime is not None else None
    store_backed = runtime is not None and meta is not None and meta["caseId"] == scenario["caseId"]

    documents = {
        doc_id: {
            "id": doc_id,
            "title": doc["title"],
            "renditionText": doc.get("renditionText", ""),
            "source": _source_meta(doc_id),
        }
        for doc_id, doc in scenario["documents"].items()
    }

    if not store_backed:
        facts = list(scenario["facts"])
        return {
            "storeBacked": False,
            "note": NO_STORE_NOTE,
            "timeline": [],
            "knowledge": None,
            "documents": documents,
            "facts": [_fact_record(f, None, documents) for f in facts],
            "liveFacts": facts,
        }

    events, asserted = _case_events(runtime.store, scenario["caseId"])
    timeline = _timeline(events)
    if not timeline:
        return {
            "storeBacked": True,
            "note": "The session store holds no events for this case.",
            "timeline": [],
            "knowledge": None,
            "documents": documents,
            "facts": [],
            "liveFacts": [],
        }

    horizon = knowledge or timeline[-1]["at"]
    states = _states_at(events, asserted, horizon)
    records = [
        _fact_record(asserted[fact_id], states.get(fact_id), documents)
        for fact_id in sorted(asserted)
    ]
    live = [asserted[fid] for fid in sorted(asserted) if states.get(fid, {}).get("state") == "live"]
    return {
        "storeBacked": True,
        "note": None,
        "timeline": timeline,
        "knowledge": horizon,
        "documents": documents,
        "facts": records,
        "liveFacts": live,
    }


def _counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in FACT_STATES}
    for record in records:
        counts[record["state"]] = counts.get(record["state"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/cases")
def api_cases() -> dict[str, Any]:
    demo = _demo()
    runtime = demo._active_runtime()
    cases = []
    for scenario in demo.load_scenarios().values():
        meta = runtime.cases.get(scenario["id"]) if runtime is not None else None
        cases.append(
            {
                "id": scenario["id"],
                "title": scenario["title"],
                "domain": scenario.get("domain", demo.DEFAULT_DOMAIN),
                "domainLabel": scenario.get("domainLabel")
                or demo._domain_fields(scenario.get("domain"))["domainLabel"],
                "caseId": scenario["caseId"],
                "source": scenario["source"],
                "storeBacked": bool(meta) and meta["caseId"] == scenario["caseId"],
                "documentCount": len(scenario["documents"]),
                "factCount": len(scenario["facts"]),
                "defaultAsOf": scenario["defaultAsOf"],
            }
        )
    return {
        "cases": cases,
        "capabilities": {
            "store": runtime is not None,
            "conformance": _registry() is not None,
            "sourceDocuments": bool(_document_index()),
        },
    }


@router.get("/cases/{scenario_id}")
def api_case(scenario_id: str, knowledge: str | None = None) -> dict[str, Any]:
    scenario = _get_scenario(scenario_id)
    projection = _case_projection(scenario, _valid_point(knowledge, "knowledge"))
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "caseId": scenario["caseId"],
        "domainLabel": scenario.get("domainLabel"),
        "source": scenario["source"],
        "extraction": scenario.get("extraction"),
        "defaultAsOf": scenario["defaultAsOf"],
        "storeBacked": projection["storeBacked"],
        "note": projection["note"],
        "knowledge": projection["knowledge"],
        "timeline": projection["timeline"],
        "documents": list(projection["documents"].values()),
        "facts": projection["facts"],
        "counts": _counts(projection["facts"]),
    }


@router.get("/cases/{scenario_id}/facts/{fact_id}")
def api_fact(
    scenario_id: str,
    fact_id: str,
    knowledge: str | None = None,
    effective: str | None = None,
) -> dict[str, Any]:
    """One fact in full: the record, its ontology, its history, and which of
    this case's questions actually cite it at this horizon."""
    demo = _demo()
    scenario = _get_scenario(scenario_id)
    projection = _case_projection(scenario, _valid_point(knowledge, "knowledge"))
    record = next((r for r in projection["facts"] if r["id"] == fact_id), None)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Case {scenario_id} holds no fact {fact_id}"
        )

    effective_point = demo._normalize_effective(
        _valid_point(effective, "effective") or scenario["defaultAsOf"]
    )
    knowledge_point = projection["knowledge"] or demo._now_knowledge()

    # The audit trail is the whole chain, not the part before the horizon — a
    # history that stopped at the dial would hide the correction that makes
    # the dial worth dragging. Events the horizon has not reached are marked
    # rather than dropped, so the trail stays complete without pretending the
    # case knew things it did not.
    history: list[dict[str, Any]] = []
    runtime = demo._active_runtime()
    if projection["storeBacked"] and runtime is not None:
        horizon = _point(knowledge_point)
        for event in runtime.store.history(fact_id):
            history.append(
                {
                    "kind": event["event_kind"],
                    "factId": event["fact_id"],
                    "recordedAt": event["recorded_at"],
                    "attribute": event["attribute"],
                    "supersedes": event["supersedes"],
                    "self": event["fact_id"] == fact_id,
                    "future": _point(event["recorded_at"]) > horizon,
                }
            )

    return {
        "record": record,
        "conformance": _conformance(record["fact"]),
        "history": history,
        "citations": _citations(
            scenario, projection["liveFacts"], fact_id, effective_point, knowledge_point
        ),
    }


@router.get("/cases/{scenario_id}/documents/{document_id}/source")
def api_document_source(scenario_id: str, document_id: str) -> Response:
    """The document's committed source bytes, inline.

    The path parameter is a document *id*, matched against the index built from
    the starter manifests — it never becomes a filesystem path. A case that
    cites a document the manifests do not carry (the fixture case does) gets a
    404 saying so, not a rendition dressed up as a source.
    """
    scenario = _get_scenario(scenario_id)
    if document_id not in scenario["documents"]:
        raise HTTPException(
            status_code=404, detail=f"Case {scenario_id} holds no document {document_id}"
        )
    entry = _document_index().get(document_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No committed source document for {document_id}. This case's "
                "facts are grounded in a rendition whose source bytes are not "
                "in starters/."
            ),
        )
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", document_id).strip("-") + ".pdf"
    return Response(
        content=entry["path"].read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
