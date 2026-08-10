"""Review queue HTTP surface — a thin FastAPI app over ReviewQueue.

The library is the product; this app only maps it onto HTTP (duly is "not a
UI product": review interfaces belong to integrators, so the surface is JSON
in, JSON out, no rendering). Every mutating request carries a caller-supplied
``recordedAt`` — the API never reads the wall clock, matching the store and
kernel discipline, so a replayed request log reproduces the same queue.

Run standalone (in-memory by default; set the env vars for durable files):

    DULY_REVIEW_DB=review.db DULY_FACTS_DB=facts.db \\
        uv run uvicorn review.duly_review.api:app --port 8789

Or mount/create programmatically::

    from duly_review.api import create_app
    app = create_app(queue, store)

Connections are opened with ``check_same_thread=False`` because FastAPI runs
sync handlers on a threadpool; sqlite3 serializes access internally.

FastAPI is an optional dependency of the wheel, behind the ``demo`` extra —
``pip install 'duly[demo]'``. The extra is named for the demonstration
workspace and covers this module too, because what it installs is one thing
(a web framework and an ASGI server) rather than one surface; splitting it
would have given an adopter two extras naming the same two packages. That
this module is *not* the demo is why the import stays here: ``import
duly_review`` reaches the queue, the golden-case converter and the
calibration export without touching FastAPI, so the library half of this
package installs and runs on a bare ``pip install duly``. Only reaching for
``duly_review.api`` asks for the extra, and the wheel smoke job proves the
distinction rather than asserting it.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from duly_store.store import FactStore, FactStoreError

from .queue import (
    InvalidCorrectionError,
    InvalidTransitionError,
    ReviewQueue,
    ReviewQueueError,
    UnknownItemError,
)

__all__ = ["create_app", "app"]


class EnqueueRequest(BaseModel):
    receipt: dict
    recordedAt: str
    caseId: str | None = None
    routedTo: str | None = None


class ClaimRequest(BaseModel):
    assignee: str
    recordedAt: str


class ResolveRequest(BaseModel):
    correction: dict
    recordedAt: str


class DismissRequest(BaseModel):
    reason: str
    recordedAt: str


def _http_error(exc: ReviewQueueError | FactStoreError) -> HTTPException:
    if isinstance(exc, UnknownItemError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidTransitionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (InvalidCorrectionError, FactStoreError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def create_app(queue: ReviewQueue, store: FactStore) -> FastAPI:
    """Build the review API over an existing queue and fact store. The
    caller owns both (lifecycle, schema init for the store); the queue's
    schema is ensured here so a fresh database Just Works."""
    queue.init_schema()
    app = FastAPI(title="duly review queue", version="0.0.1")

    @app.post("/api/enqueue")
    def api_enqueue(body: EnqueueRequest) -> dict[str, Any]:
        try:
            items = queue.enqueue_receipt(
                body.receipt,
                body.caseId,
                recorded_at=body.recordedAt,
                routed_to=body.routedTo,
            )
        except (ReviewQueueError, ValueError) as exc:
            raise _http_error(exc) if isinstance(exc, ReviewQueueError) else HTTPException(
                status_code=422, detail=str(exc)
            )
        return {"items": items}

    @app.get("/api/items")
    def api_items(status: str | None = None, caseId: str | None = None) -> list[dict[str, Any]]:
        return queue.items(status=status, case_id=caseId)

    @app.get("/api/items/{item_id}/events")
    def api_item_events(item_id: str) -> list[dict[str, Any]]:
        events = queue.events(item_id)
        if not events:
            raise HTTPException(status_code=404, detail=f"no such review item: {item_id}")
        return events

    @app.get("/api/items/{item_id}")
    def api_item(item_id: str) -> dict[str, Any]:
        try:
            return queue.item(item_id)
        except ReviewQueueError as exc:
            raise _http_error(exc)

    @app.post("/api/items/{item_id}/claim")
    def api_claim(item_id: str, body: ClaimRequest) -> dict[str, Any]:
        try:
            return queue.claim(item_id, body.assignee, body.recordedAt)
        except (ReviewQueueError, ValueError) as exc:
            if isinstance(exc, ReviewQueueError):
                raise _http_error(exc)
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/api/items/{item_id}/resolve")
    def api_resolve(item_id: str, body: ResolveRequest) -> dict[str, Any]:
        try:
            return queue.resolve(item_id, body.correction, store, body.recordedAt)
        except (ReviewQueueError, FactStoreError) as exc:
            raise _http_error(exc)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/api/items/{item_id}/dismiss")
    def api_dismiss(item_id: str, body: DismissRequest) -> dict[str, Any]:
        try:
            return queue.dismiss(item_id, body.reason, body.recordedAt)
        except (ReviewQueueError, ValueError) as exc:
            if isinstance(exc, ReviewQueueError):
                raise _http_error(exc)
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/calibration/pairs")
    def api_calibration_pairs() -> dict[str, Any]:
        pairs = queue.calibration_pairs()
        return {
            "pairs": [list(p) for p in pairs],
            "count": len(pairs),
            # The caveat travels with the data, not just the docs.
            "note": (
                "Censored sample: these pairs label abstained (below-floor) facts "
                "only; fitting on them alone does not calibrate the full score range."
            ),
        }

    return app


def _default_app() -> FastAPI:
    """Module-level app for `uvicorn review.duly_review.api:app`. Defaults to
    in-memory databases (nothing touches disk on import); set DULY_REVIEW_DB
    / DULY_FACTS_DB for durable files."""
    queue = ReviewQueue(os.environ.get("DULY_REVIEW_DB", ":memory:"), check_same_thread=False)
    store = FactStore(os.environ.get("DULY_FACTS_DB", ":memory:"), check_same_thread=False)
    store.init_schema()
    return create_app(queue, store)


app = _default_app()
