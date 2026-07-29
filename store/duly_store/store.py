"""Append-only bitemporal fact store (spec/grounded-facts.md D6/D7/D8).

Storage model
-------------
One table, ``fact_events``, holding an immutable event log:

- ``asserted``   — a GroundedFact entered the store (payload = canonical fact JSON).
- ``superseded`` — a later fact carried ``supersedes: <this fact id>``; recorded
  with the *superseding* fact's ``recordedAt``.
- ``retracted``  — the fact was withdrawn without replacement.

Nothing is ever updated or deleted; every projection (``as_of``) is derived by
replaying the log up to a knowledge horizon. A fact's knowledge time IS its
``recordedAt`` from the fact document — this module never reads the wall clock,
so replays are deterministic.

Postgres portability
--------------------
The DDL sticks to ANSI SQL types (TEXT, INTEGER) and a plain CHECK constraint.
Known divergences to mind when porting:

- ``event_id INTEGER PRIMARY KEY`` relies on SQLite's rowid aliasing for
  auto-increment; on Postgres declare it
  ``BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY``.
- Timestamps are TEXT holding ISO-8601 UTC strings (portable everywhere).
  Because callers may mix bare dates, second- and microsecond-precision
  forms, temporal comparisons are done in application code after parsing,
  never via SQL string comparison — so no SQL dialect issue arises.
- ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS`` are
  supported by both SQLite and Postgres.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3

__all__ = [
    "FactStore",
    "FactStoreError",
    "HashMismatchError",
    "DuplicateFactError",
    "canonical",
    "content_hash",
]


class FactStoreError(Exception):
    """Base error for the fact store."""


class HashMismatchError(FactStoreError):
    """The fact's contentHash does not match its canonical content."""


class DuplicateFactError(FactStoreError):
    """A different payload was ingested under an already-known fact id."""


# --- canonicalization (must match spec/validate.py exactly) -----------------

def canonical(obj) -> bytes:
    """RFC 8785-subset canonical JSON: sorted keys, minimal separators, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(fact: dict) -> str:
    """SHA-256 over the canonical fact, excluding ``id`` and ``contentHash``."""
    body = {k: v for k, v in fact.items() if k not in ("id", "contentHash")}
    return hashlib.sha256(canonical(body)).hexdigest()


# --- temporal helpers -------------------------------------------------------

def _parse_point(s: str) -> _dt.datetime:
    """Parse an ISO-8601 point: a bare date is midnight UTC; a naive
    datetime is taken as UTC; an aware datetime is converted to UTC.
    Mirrors duly_kernel.engine.normalize_point."""
    try:
        d = _dt.date.fromisoformat(s)
    except ValueError:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc)
    return _dt.datetime.combine(d, _dt.time(0, 0, 0), tzinfo=_dt.timezone.utc)


def _window_contains(point: _dt.datetime, frm, to) -> bool:
    """[frm, to) containment; either bound may be absent."""
    if frm is not None and point < _parse_point(str(frm)):
        return False
    if to is not None and point >= _parse_point(str(to)):
        return False
    return True


# --- schema -----------------------------------------------------------------

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS fact_events (
    event_id       INTEGER PRIMARY KEY,
    event_kind     TEXT NOT NULL CHECK (event_kind IN ('asserted', 'superseded', 'retracted')),
    fact_id        TEXT NOT NULL,
    case_id        TEXT,
    entity_id      TEXT,
    attribute      TEXT,
    effective_from TEXT,
    effective_to   TEXT,
    recorded_at    TEXT NOT NULL,
    payload        TEXT NOT NULL,
    supersedes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_fact_events_case        ON fact_events (case_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_attribute   ON fact_events (attribute);
CREATE INDEX IF NOT EXISTS idx_fact_events_recorded_at ON fact_events (recorded_at);
CREATE INDEX IF NOT EXISTS idx_fact_events_fact_id     ON fact_events (fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_supersedes  ON fact_events (supersedes);
"""

_REQUIRED_FIELDS = ("id", "contentHash", "caseId", "entity", "attribute", "recordedAt")

_EVENT_COLUMNS = (
    "event_id", "event_kind", "fact_id", "case_id", "entity_id", "attribute",
    "effective_from", "effective_to", "recorded_at", "payload", "supersedes",
)


class FactStore:
    """Append-only bitemporal store for GroundedFact documents."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)

    @classmethod
    def in_memory(cls) -> "FactStore":
        return cls(":memory:")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FactStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- schema --

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA_DDL)
        self._conn.commit()

    # -- writes --

    def ingest(self, fact: dict) -> bool:
        """Append an 'asserted' event for `fact` (and a 'superseded' event for
        its target when the fact carries ``supersedes``).

        Returns True if the fact was inserted, False if it was already present
        with an identical payload (idempotent no-op).

        Raises HashMismatchError when contentHash does not verify, and
        DuplicateFactError when a *different* payload arrives under an
        existing fact id.
        """
        self._validate_shape(fact)
        expected = content_hash(fact)
        if fact["contentHash"] != expected:
            raise HashMismatchError(
                f"contentHash mismatch for {fact['id']}: "
                f"declared {fact['contentHash'][:12]}…, canonical form hashes to {expected[:12]}…"
            )

        payload = canonical(fact).decode("utf-8")
        row = self._conn.execute(
            "SELECT payload FROM fact_events WHERE event_kind = 'asserted' AND fact_id = ?",
            (fact["id"],),
        ).fetchone()
        if row is not None:
            if row[0] == payload:
                return False  # idempotent re-ingest
            raise DuplicateFactError(
                f"fact id {fact['id']} already ingested with a different payload"
            )

        supersedes = fact.get("supersedes")
        self._conn.execute(
            "INSERT INTO fact_events (event_kind, fact_id, case_id, entity_id, attribute,"
            " effective_from, effective_to, recorded_at, payload, supersedes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "asserted",
                fact["id"],
                fact["caseId"],
                fact["entity"]["id"],
                fact["attribute"],
                fact.get("effectiveFrom"),
                fact.get("effectiveTo"),
                fact["recordedAt"],
                payload,
                supersedes,
            ),
        )
        if supersedes:
            # The target's status becomes 'superseded' as a projection of this
            # event — the original 'asserted' record is never touched (D7).
            # The event's `supersedes` column points at the superseding fact.
            target_case = self._case_of(supersedes) or fact["caseId"]
            self._conn.execute(
                "INSERT INTO fact_events (event_kind, fact_id, case_id, recorded_at, payload, supersedes)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "superseded",
                    supersedes,
                    target_case,
                    fact["recordedAt"],
                    canonical({"factId": supersedes, "supersededBy": fact["id"]}).decode("utf-8"),
                    fact["id"],
                ),
            )
        self._conn.commit()
        return True

    def retract(self, fact_id: str, recorded_at: str) -> None:
        """Append a 'retracted' event. `recorded_at` is supplied by the
        caller — the store never reads the wall clock."""
        _parse_point(recorded_at)  # validate early
        self._conn.execute(
            "INSERT INTO fact_events (event_kind, fact_id, case_id, recorded_at, payload)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                "retracted",
                fact_id,
                self._case_of(fact_id),
                recorded_at,
                canonical({"factId": fact_id, "retracted": True}).decode("utf-8"),
            ),
        )
        self._conn.commit()

    # -- projections --

    def as_of(self, case_id: str, knowledge: str, effective: str | None = None) -> list[dict]:
        """Project the facts of `case_id` as known at `knowledge`.

        Only events with recorded_at <= knowledge are considered. A fact is
        live when it has an 'asserted' event and no 'superseded'/'retracted'
        event within that horizon. Facts without effective windows always
        participate; facts with windows participate only if the window
        contains `effective` (when `effective` is given). Result is ordered
        by fact id — deterministic by construction.
        """
        k = _parse_point(knowledge)
        e = _parse_point(effective) if effective is not None else None

        asserted: dict[str, dict] = {}
        for fact_id, recorded_at, payload in self._conn.execute(
            "SELECT fact_id, recorded_at, payload FROM fact_events"
            " WHERE event_kind = 'asserted' AND case_id = ?",
            (case_id,),
        ):
            if _parse_point(recorded_at) <= k:
                asserted[fact_id] = json.loads(payload)
        if not asserted:
            return []

        placeholders = ",".join("?" * len(asserted))
        dead: set[str] = set()
        for fact_id, recorded_at in self._conn.execute(
            "SELECT fact_id, recorded_at FROM fact_events"
            " WHERE event_kind IN ('superseded', 'retracted')"
            f" AND fact_id IN ({placeholders})",
            tuple(asserted),
        ):
            if _parse_point(recorded_at) <= k:
                dead.add(fact_id)

        projection = []
        for fact_id in sorted(asserted):
            if fact_id in dead:
                continue
            fact = asserted[fact_id]
            if e is not None and not _window_contains(
                e, fact.get("effectiveFrom"), fact.get("effectiveTo")
            ):
                continue
            projection.append(fact)
        return projection

    def history(self, fact_id: str) -> list[dict]:
        """All events touching `fact_id` and its supersession chain (walked in
        both directions), ordered by event id — the audit trail."""
        chain = {fact_id}
        frontier = [fact_id]
        while frontier:
            current = frontier.pop()
            linked = set()
            for (other,) in self._conn.execute(
                "SELECT supersedes FROM fact_events WHERE fact_id = ? AND supersedes IS NOT NULL",
                (current,),
            ):
                linked.add(other)
            for (other,) in self._conn.execute(
                "SELECT fact_id FROM fact_events WHERE supersedes = ?",
                (current,),
            ):
                linked.add(other)
            for other in linked:
                if other not in chain:
                    chain.add(other)
                    frontier.append(other)

        placeholders = ",".join("?" * len(chain))
        rows = self._conn.execute(
            f"SELECT {', '.join(_EVENT_COLUMNS)} FROM fact_events"
            f" WHERE fact_id IN ({placeholders}) ORDER BY event_id",
            tuple(sorted(chain)),
        ).fetchall()
        events = []
        for row in rows:
            event = dict(zip(_EVENT_COLUMNS, row))
            event["payload"] = json.loads(event["payload"])
            events.append(event)
        return events

    # -- internals --

    def _case_of(self, fact_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT case_id FROM fact_events WHERE event_kind = 'asserted' AND fact_id = ?",
            (fact_id,),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _validate_shape(fact: dict) -> None:
        if not isinstance(fact, dict):
            raise FactStoreError("fact must be a dict")
        missing = [f for f in _REQUIRED_FIELDS if f not in fact]
        if missing:
            raise FactStoreError(f"fact is missing required field(s): {', '.join(missing)}")
        entity = fact["entity"]
        if not isinstance(entity, dict) or "id" not in entity:
            raise FactStoreError("fact.entity must be an object with an 'id'")
        _parse_point(fact["recordedAt"])  # must be a parseable ISO-8601 point
