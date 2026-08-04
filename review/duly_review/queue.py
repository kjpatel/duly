"""Review queue: abstention routing and human corrections re-entering the
store (README roadmap, M3).

Storage model
-------------
One table, ``review_events``, holding an immutable event log — the same
discipline as the fact store's ``fact_events``:

- ``opened``    — a receipt abstention became a queue item (payload = the
  item projection seed plus the enqueueing receipt, verbatim).
- ``claimed``   — an assignee took the item (assignment is a field, not a
  state: the item stays open).
- ``resolved``  — a human-asserted correction was validated and ingested
  into the caller's :class:`~duly_store.store.FactStore`; terminal.
- ``dismissed`` — the abstention was judged correct (the machine fact was
  genuinely unusable); no fact enters the store; terminal.

Nothing is updated or deleted; item status/assignee are projections derived
by replaying the log. Every timestamp is caller-supplied — this module never
reads the wall clock, so replays are deterministic.

Item identity and dedup
-----------------------
An item's natural key is the SHA-256 of the canonical JSON of
``{"caseId": <case id>, "entry": <abstention entry verbatim>}`` —
``urn:duly:review:sha256:<hex>``. Re-adjudicating the same case under the
same pack reproduces the identical abstention entry (entries carry no
timestamps), so re-enqueueing is an idempotent no-op for the item's whole
lifetime: no duplicate open item, and no reopened item after resolution or
dismissal. The receipt hash is deliberately NOT part of the key — every
re-adjudication mints a new receipt. A pack version bump that changes the
floor (``threshold.packVersion`` lives inside the entry) yields a NEW item:
the floor that excluded a fact is part of the abstention's identity.

Fact custody
------------
The fact store remains the system of record. The queue stores abstention
entries and receipts (already content-addressed artifacts), never fact
documents; a correction reaches the store only through ``FactStore.ingest``,
and the durable correction mechanism is the fact's own ``supersedes`` field
(spec D7).

**Resolving a ``low_confidence`` item requires supersession**
(`spec/compatibility.md <../../spec/compatibility.md>`_ C6): resolving one is,
by construction, a ruling on one specific fact. The queue refuses a correction
that does not carry it, and names the id it must carry — see
``_require_supersession`` for why it cannot simply write the field in.

The rule binds *this* boundary and no other. ``FactStore.ingest`` still takes
an independent human fact that supersedes nothing, and the conflict-resolution
policy (spec resolved question 2) still makes a lone live human assertion
outrank machine facts without it — because a value known from a phone call is
not a ruling on anybody's extraction.

Postgres portability: same conventions as duly_store.store — ANSI types,
TEXT ISO-8601 timestamps, ``INTEGER PRIMARY KEY`` needs
``BIGINT GENERATED ALWAYS AS IDENTITY`` on Postgres.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from duly_store.store import FactStore, canonical, content_hash

__all__ = [
    "ReviewQueue",
    "ReviewQueueError",
    "UnknownItemError",
    "InvalidTransitionError",
    "InvalidCorrectionError",
    "enqueue_receipt",
    "calibration_pairs",
    "values_equal",
    "item_natural_key",
    "ITEM_URN_PREFIX",
]

ITEM_URN_PREFIX = "urn:duly:review:sha256:"

# The grounded-fact schema ships inside `duly_core`, so this resolves
# identically in a checkout and in site-packages. It used to be
# `parents[2]/spec/schemas/...`, which resolves in exactly one of those: `spec/`
# is in no wheel, so `resolve()` raised FileNotFoundError for every adopter
# while every test here passed (M5 plan, A8).
def _default_fact_schema() -> dict:
    from duly_core import load_schema

    return load_schema("grounded-fact")


class ReviewQueueError(Exception):
    """Base error for the review queue."""


class UnknownItemError(ReviewQueueError):
    """No item with that id exists in the queue."""


class InvalidTransitionError(ReviewQueueError):
    """The item is not in a state that admits the requested transition."""


class InvalidCorrectionError(ReviewQueueError):
    """The supplied correction fact is unusable: schema-invalid, not a
    human assertion, or inconsistent with the item it resolves."""


# --- temporal helper (mirrors duly_store.store._parse_point) -----------------

def _parse_point(s: str) -> _dt.datetime:
    try:
        d = _dt.date.fromisoformat(s)
    except ValueError:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc)
    return _dt.datetime.combine(d, _dt.time(0, 0, 0), tzinfo=_dt.timezone.utc)


# --- item identity ------------------------------------------------------------

def item_natural_key(case_id: str, entry: dict) -> str:
    """The queue item id for one (case, abstention entry) pair — see the
    module docstring for what is (and is not) inside the key."""
    digest = hashlib.sha256(canonical({"caseId": case_id, "entry": entry})).hexdigest()
    return ITEM_URN_PREFIX + digest


# --- value equality -----------------------------------------------------------

def values_equal(a: dict, b: dict) -> bool:
    """Whether two GroundedFact ``value`` objects assert the same value.

    Semantics, per kind (mismatched kinds are never equal — a human
    asserting a different kind did not confirm the machine's value):

    - ``decimal``       — numeric equality (``"45"`` == ``"45.0"``).
    - ``money``         — numeric amount equality AND exact currency match.
    - ``datetime``      — same instant after UTC normalization
      (``...T00:00:00Z`` == ``...T00:00:00+00:00``).
    - ``date``          — exact ISO string equality (the schema already
      forces canonical YYYY-MM-DD).
    - ``code``          — same ``value`` and ``codeSystem``;
      ``codeSystemVersion`` is deliberately ignored — the same code read
      from a newer catalog printing is the same assertion.
    - ``string`` / ``boolean`` / ``entityRef`` — exact equality.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    kind = a.get("kind")
    if kind != b.get("kind"):
        return False
    try:
        if kind == "decimal":
            return Decimal(a["value"]) == Decimal(b["value"])
        if kind == "money":
            return a["currency"] == b["currency"] and Decimal(a["amount"]) == Decimal(b["amount"])
        if kind == "datetime":
            return _parse_point(a["value"]) == _parse_point(b["value"])
        if kind == "code":
            return a["value"] == b["value"] and a["codeSystem"] == b["codeSystem"]
        return a.get("value") == b.get("value")
    except (KeyError, InvalidOperation, ValueError):
        return False


# --- schema -------------------------------------------------------------------

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS review_events (
    event_id    INTEGER PRIMARY KEY,
    event_kind  TEXT NOT NULL CHECK (event_kind IN ('opened', 'claimed', 'resolved', 'dismissed')),
    item_id     TEXT NOT NULL,
    case_id     TEXT,
    attribute   TEXT,
    recorded_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_events_item ON review_events (item_id);
CREATE INDEX IF NOT EXISTS idx_review_events_case ON review_events (case_id);
"""

_TERMINAL = {"resolved", "dismissed"}

_EVENT_COLUMNS = (
    "event_id", "event_kind", "item_id", "case_id", "attribute", "recorded_at", "payload",
)


class ReviewQueue:
    """Append-only review queue over SQLite (Postgres-portable schema)."""

    def __init__(
        self,
        path: str,
        *,
        check_same_thread: bool = True,
        fact_schema: dict | None = None,
    ):
        """``check_same_thread=False`` allows use from threads other than the
        creating one (the FastAPI surface needs it; sqlite3 serializes
        access internally).

        ``fact_schema`` is the JSON Schema a correction is validated against.
        It defaults to the contract duly ships, and is a parameter because a
        deployment may hold corrections to a *narrower* shape than the base
        contract — required sensitivity, a house actor vocabulary — and the
        library should take that rather than make the deployment fork it.
        """
        self._conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        self._fact_schema = fact_schema

    @classmethod
    def in_memory(cls) -> "ReviewQueue":
        queue = cls(":memory:")
        queue.init_schema()
        return queue

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ReviewQueue":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- schema --

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_DDL)
        self._conn.commit()

    # -- enqueue --

    def enqueue_receipt(
        self,
        receipt: dict,
        case_id: str | None = None,
        *,
        recorded_at: str,
        routed_to: str | None = None,
    ) -> list[dict]:
        """Ingest a DecisionReceipt's ``abstentions`` into queue items — one
        item per entry, deduplicated by the natural key (module docstring).

        - ``case_id`` defaults to the receipt's own ``caseId``.
        - ``recorded_at`` is caller-supplied (never wall clock).
        - ``routed_to``: when given, only entries whose ``routedTo`` matches
          are enqueued — a queue serving one route ignores entries addressed
          elsewhere. When omitted, every entry is enqueued, routed or not.

        Returns ``[{"itemId", "created"}]`` in receipt entry order
        (``created`` False = the item already existed, in any status; no
        event is appended for a re-sighting). The receipt's content hash is
        verified first — a tampered receipt never enters the queue.
        """
        if not isinstance(receipt, dict):
            raise ReviewQueueError("receipt must be a dict")
        for field in ("caseId", "receiptSha256", "abstentions"):
            if field not in receipt:
                raise ReviewQueueError(f"receipt is missing required field {field!r}")
        expected = content_hash({k: v for k, v in receipt.items() if k != "receiptSha256"})
        # content_hash excludes 'id'/'contentHash'; receipts hash-exclude
        # 'id'/'receiptSha256', so drop receiptSha256 above and hash the rest.
        if receipt["receiptSha256"] != expected:
            raise ReviewQueueError(
                f"receiptSha256 mismatch: declared {receipt['receiptSha256'][:12]}…, "
                f"canonical form hashes to {expected[:12]}…"
            )
        _parse_point(recorded_at)  # validate early
        case = case_id if case_id is not None else receipt["caseId"]

        results: list[dict] = []
        for entry in receipt["abstentions"]:
            if routed_to is not None and entry.get("routedTo") != routed_to:
                continue
            item_id = item_natural_key(case, entry)
            exists = self._conn.execute(
                "SELECT 1 FROM review_events WHERE event_kind = 'opened' AND item_id = ?",
                (item_id,),
            ).fetchone()
            if exists:
                results.append({"itemId": item_id, "created": False})
                continue
            seed = {
                "itemId": item_id,
                "caseId": case,
                "entity": entry.get("entity"),
                "attribute": entry.get("attribute"),
                "reason": entry.get("reason"),
                "entry": entry,
                "receipt": {"id": receipt.get("id"), "receiptSha256": receipt["receiptSha256"]},
            }
            self._append(
                "opened", item_id, case, entry.get("attribute"), recorded_at,
                {"item": seed, "receipt": receipt},
            )
            results.append({"itemId": item_id, "created": True})
        self._conn.commit()
        return results

    # -- lifecycle --

    def claim(self, item_id: str, assignee: str, recorded_at: str) -> dict:
        """Record an assignee on an open item. Assignment is a field, not a
        state: the item stays open, and a later claim overwrites it."""
        item = self.item(item_id)
        if item["status"] != "open":
            raise InvalidTransitionError(
                f"cannot claim item in status {item['status']!r} (only open items)"
            )
        if not assignee or not isinstance(assignee, str):
            raise ReviewQueueError("assignee must be a non-empty string")
        _parse_point(recorded_at)
        self._append("claimed", item_id, item["caseId"], item["attribute"], recorded_at,
                     {"assignee": assignee})
        self._conn.commit()
        return self.item(item_id)

    def resolve(
        self, item_id: str, correction: dict, store: FactStore, recorded_at: str
    ) -> dict:
        """Resolve an open item with a human-asserted correction fact.

        The correction is validated against the grounded-fact schema and
        against the item (human assertion with actor id + role; same case,
        entity, and attribute; ``supersedes``, when present, must point at
        one of the item's abstained facts), then ingested into ``store``
        through its public API. The resolved event records the correction
        verbatim plus — when the abstention carried a machine confidence
        and the abstained fact is retrievable from ``store`` — the
        calibration label (see :meth:`calibration_pairs`).
        """
        item = self.item(item_id)
        if item["status"] != "open":
            raise InvalidTransitionError(
                f"cannot resolve item in status {item['status']!r} (only open items)"
            )
        _parse_point(recorded_at)
        self._validate_correction(correction, item)

        label = self._label_for(item, correction, store)
        store.ingest(correction)
        payload: dict = {"factId": correction["id"], "correction": correction}
        if label is not None:
            payload["label"] = label
        self._append("resolved", item_id, item["caseId"], item["attribute"], recorded_at, payload)
        self._conn.commit()
        return self.item(item_id)

    def dismiss(self, item_id: str, reason: str, recorded_at: str) -> dict:
        """Dismiss an open item: the abstention was correct — the machine
        fact was genuinely unusable. No fact enters the store; the dismissal
        and its reason are recorded. Dismissals never yield calibration
        pairs (documented in :meth:`calibration_pairs`)."""
        item = self.item(item_id)
        if item["status"] != "open":
            raise InvalidTransitionError(
                f"cannot dismiss item in status {item['status']!r} (only open items)"
            )
        if not reason or not isinstance(reason, str):
            raise ReviewQueueError("dismissal requires a non-empty reason")
        _parse_point(recorded_at)
        self._append("dismissed", item_id, item["caseId"], item["attribute"], recorded_at,
                     {"reason": reason})
        self._conn.commit()
        return self.item(item_id)

    # -- projections --

    def items(self, *, status: str | None = None, case_id: str | None = None) -> list[dict]:
        """Project every item, in enqueue order (first-opened first),
        optionally filtered by status and/or case id."""
        rows = self._conn.execute(
            "SELECT item_id FROM review_events WHERE event_kind = 'opened' ORDER BY event_id"
        ).fetchall()
        out = []
        for (item_id,) in rows:
            item = self.item(item_id)
            if status is not None and item["status"] != status:
                continue
            if case_id is not None and item["caseId"] != case_id:
                continue
            out.append(item)
        return out

    def item(self, item_id: str) -> dict:
        """Project one item from its event history."""
        events = self.events(item_id)
        if not events:
            raise UnknownItemError(f"no such review item: {item_id}")
        opened = events[0]
        item = dict(opened["payload"]["item"])
        item["status"] = "open"
        item["assignee"] = None
        item["openedAt"] = opened["recorded_at"]
        item["closedAt"] = None
        for event in events[1:]:
            if event["event_kind"] == "claimed":
                item["assignee"] = event["payload"]["assignee"]
            elif event["event_kind"] == "resolved":
                item["status"] = "resolved"
                item["closedAt"] = event["recorded_at"]
                item["resolution"] = {
                    "factId": event["payload"]["factId"],
                    "label": event["payload"].get("label"),
                }
            elif event["event_kind"] == "dismissed":
                item["status"] = "dismissed"
                item["closedAt"] = event["recorded_at"]
                item["dismissal"] = {"reason": event["payload"]["reason"]}
        return item

    def events(self, item_id: str) -> list[dict]:
        """All events for one item, ordered by event id — the audit trail."""
        rows = self._conn.execute(
            f"SELECT {', '.join(_EVENT_COLUMNS)} FROM review_events"
            " WHERE item_id = ? ORDER BY event_id",
            (item_id,),
        ).fetchall()
        events = []
        for row in rows:
            event = dict(zip(_EVENT_COLUMNS, row))
            event["payload"] = json.loads(event["payload"])
            events.append(event)
        return events

    def opened_receipt(self, item_id: str) -> dict:
        """The DecisionReceipt (verbatim) whose abstention opened this item."""
        events = self.events(item_id)
        if not events:
            raise UnknownItemError(f"no such review item: {item_id}")
        return events[0]["payload"]["receipt"]

    # -- calibration label export --

    def calibration_pairs(self) -> list[tuple[float, int]]:
        """Labeled ``(raw_score, correct)`` pairs for duly_calibration
        (compatible with ``duly_calibration.base.Pair``), in enqueue order.

        A resolved item yields exactly one pair when — and only when — its
        abstention entry carried a machine ``confidence`` AND the abstained
        fact was retrievable from the fact store at resolution time:
        ``correct=1`` if the human correction confirmed the machine fact's
        value (see :func:`values_equal`), ``0`` if it contradicted it.

        Items that yield NO pair, by design (a missing label is honest; a
        guessed one is not):

        - **dismissed** items — dismissal says the machine fact was
          unusable, which is a statement about the abstention, not a value
          judgment we can score against the confidence;
        - entries without a ``confidence`` (conflict entries, and the
          fail-closed no-confidence exclusions) — there is no score to pair;
        - resolutions where the abstained fact was not in the store, so no
          machine value existed to compare against.

        HONEST CONSTRAINT — censored sample: these pairs label *abstained*
        (below-floor) facts only. The facts that cleared the floor were
        never reviewed, so this export says nothing about the upper score
        range. Fitting a calibrator on these pairs alone does NOT calibrate
        the full score distribution; it characterizes the region the policy
        already distrusts. Use them to validate or tighten floors, or
        combine them with labels from audit sampling of *accepted* facts
        before fitting anything that claims full-range calibration.
        """
        pairs: list[tuple[float, int]] = []
        for item in self.items(status="resolved"):
            label = (item.get("resolution") or {}).get("label")
            if label is not None:
                pairs.append((float(label["score"]), int(label["correct"])))
        return pairs

    # -- internals --

    def _append(
        self, kind: str, item_id: str, case_id: str | None, attribute: str | None,
        recorded_at: str, payload: dict,
    ) -> None:
        self._conn.execute(
            "INSERT INTO review_events (event_kind, item_id, case_id, attribute, recorded_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, item_id, case_id, attribute, recorded_at, canonical(payload).decode("utf-8")),
        )

    def _label_for(self, item: dict, correction: dict, store: FactStore) -> dict | None:
        """The calibration label a resolution produces, or None (see
        :meth:`calibration_pairs` for exactly when None is the answer)."""
        entry = item["entry"]
        confidence = entry.get("confidence")
        if confidence is None:
            return None
        fact_ids = entry.get("facts") or []
        if len(fact_ids) != 1:
            return None  # only single-fact (low_confidence) entries are scoreable
        machine_fact = self._asserted_payload(store, fact_ids[0])
        if machine_fact is None:
            return None
        correct = int(values_equal(machine_fact.get("value"), correction.get("value")))
        return {
            "score": confidence["score"],
            "method": confidence["method"],
            "correct": correct,
            "machineFactId": fact_ids[0],
            "machineValue": machine_fact.get("value"),
            "humanValue": correction.get("value"),
        }

    @staticmethod
    def _asserted_payload(store: FactStore, fact_id: str) -> dict | None:
        """The fact document as asserted into ``store``, via the store's
        public history API; None when the store never saw the fact."""
        for event in store.history(fact_id):
            if event["event_kind"] == "asserted" and event["fact_id"] == fact_id:
                return event["payload"]
        return None

    def _validate_correction(self, correction: dict, item: dict) -> None:
        if not isinstance(correction, dict):
            raise InvalidCorrectionError("correction must be a GroundedFact dict")

        # Grounded-fact schema first (jsonschema is imported lazily, matching
        # duly_assurance.generate — it is a dev/tooling dependency).
        from jsonschema import Draft202012Validator, FormatChecker  # noqa: PLC0415

        validator = getattr(self, "_fact_validator", None)
        if validator is None:
            schema = self._fact_schema if self._fact_schema is not None else _default_fact_schema()
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            self._fact_validator = validator
        errors = sorted(validator.iter_errors(correction), key=lambda e: list(e.absolute_path))
        if errors:
            msgs = "; ".join(e.message for e in errors[:3])
            raise InvalidCorrectionError(f"correction fails the grounded-fact schema: {msgs}")

        expected = content_hash(correction)
        if correction["contentHash"] != expected:
            raise InvalidCorrectionError(
                f"correction contentHash mismatch: declared {correction['contentHash'][:12]}…, "
                f"canonical form hashes to {expected[:12]}…"
            )

        assertion = correction["assertion"]
        if assertion["kind"] != "human":
            raise InvalidCorrectionError(
                "correction must be a human assertion (assertion.kind == 'human', spec D3/D9)"
            )
        actor = assertion.get("actor") or {}
        if not actor.get("id") or not actor.get("role"):
            raise InvalidCorrectionError(
                "correction's assertion.actor must carry both id and role (spec D3)"
            )

        if correction["caseId"] != item["caseId"]:
            raise InvalidCorrectionError(
                f"correction caseId {correction['caseId']!r} does not match "
                f"the item's case {item['caseId']!r}"
            )
        if correction["entity"]["id"] != item["entity"]:
            raise InvalidCorrectionError(
                f"correction entity {correction['entity']['id']!r} does not match "
                f"the item's entity {item['entity']!r}"
            )
        if correction["attribute"] != item["attribute"]:
            raise InvalidCorrectionError(
                f"correction attribute {correction['attribute']!r} does not match "
                f"the item's attribute {item['attribute']!r}"
            )
        abstained = item["entry"].get("facts") or []
        supersedes = correction.get("supersedes")
        if supersedes is not None and supersedes not in abstained:
            raise InvalidCorrectionError(
                "correction supersedes a fact that is not among the item's abstained facts"
            )
        self._require_supersession(item, supersedes, abstained)

    @staticmethod
    def _require_supersession(item: dict, supersedes, abstained: list) -> None:
        """A `low_confidence` resolution must supersede the fact it rules on.

        [spec/compatibility.md](../../spec/compatibility.md) C6, and
        [grounded-facts.md](../../spec/grounded-facts.md) open question 2 before
        it. Resolving one of these items is, by construction, a ruling on one
        specific fact, so `supersedes` is the truthful record of the act. The
        coexisting form — a human fact that merely outranks — leaves the
        below-floor fact live, so every future receipt carries a persistent
        `low_confidence` entry for an attribute the decision *did* use, which
        contradicts the fact spec's own definition of `abstentions`.

        **The queue refuses; it does not stamp.** The obvious implementation is
        to write `supersedes` in from the entry's own fact id rather than trust
        the caller, and it is not available: a correction arrives
        content-addressed, so writing a field into it changes its hash and
        therefore its identity, and the queue would be handing the store a
        document its author never sealed. Naming the required id is the same
        invariant without any component rewriting a hashed document behind its
        author's back.

        Deliberately narrow, on three axes. Only `low_confidence` items —
        `conflict` entries carry several facts and the analogous rule is not
        obvious. Only the *queue*: `FactStore.ingest` still accepts independent
        human facts, because a value known from a phone call is not a ruling on
        an extraction. And only where the entry names exactly one fact, since
        an entry naming none has nothing to rule on.
        """
        if item.get("reason") != "low_confidence" or supersedes is not None:
            return
        if len(abstained) != 1:
            return
        raise InvalidCorrectionError(
            f"resolving a low_confidence item is a ruling on the fact it "
            f"abstained over, so the correction must supersede it: set "
            f'"supersedes": "{abstained[0]}" and re-seal. Without it the fact '
            f"stays live and every future receipt carries a low_confidence "
            f"entry for an attribute the decision used (spec/compatibility.md "
            f"C6). A human fact that is not a ruling on this extraction "
            f"belongs in the store directly, not through the queue."
        )


# --- module-level conveniences (the names the roadmap promises) ---------------

def enqueue_receipt(
    queue: ReviewQueue,
    receipt: dict,
    case_id: str | None = None,
    *,
    recorded_at: str,
    routed_to: str | None = None,
) -> list[dict]:
    """Function form of :meth:`ReviewQueue.enqueue_receipt`."""
    return queue.enqueue_receipt(receipt, case_id, recorded_at=recorded_at, routed_to=routed_to)


def calibration_pairs(queue: ReviewQueue) -> list[tuple[float, int]]:
    """Function form of :meth:`ReviewQueue.calibration_pairs` — see its
    docstring, especially the censored-sample constraint."""
    return queue.calibration_pairs()
