"""Rewrite a GroundedFact's confidence through a fitted calibrator.

Facts are content-addressed (spec D8): ``contentHash`` is SHA-256 over the
RFC 8785 canonical JSON of the fact minus ``id`` and ``contentHash``, and
the id is ``urn:duly:fact:sha256:<hash>``. A changed confidence therefore
changes the hash — a recalibrated fact is a **new fact**, not an edit
(facts are immutable, spec D7). This module builds that new fact with
``supersedes`` pointing at the original, so the correction chain records
that calibration happened and to what. Actually ingesting it — which marks
the original superseded as a store projection — is the caller's job
(``duly_store.FactStore.ingest``); this module never touches a store.
"""

from __future__ import annotations

import copy
from typing import Mapping

from .base import CalibrationError, Calibrator
from duly_core import canonical, content_hash as _content_hash  # noqa: F401

__all__ = ["canonical", "content_hash", "recalibrate_fact"]


# Canonicalization lives in duly_core (see its charter). This module keeps a
# fact-shaped wrapper because that is what its callers pass.


def content_hash(fact: dict) -> str:
    """SHA-256 over the canonical fact, excluding ``id`` and ``contentHash``."""
    return _content_hash(fact, "contentHash")


# Calibrated scores are rounded before entering the fact so the canonical
# JSON carries "0.874312", not a 17-digit float artifact. Six decimals is
# far finer than any calibration on realistic label volumes can resolve
# (ECE noise floor ~1/sqrt(n)), and rounding is deterministic.
_SCORE_DECIMALS = 6


def recalibrate_fact(
    fact: dict,
    calibrator: Calibrator,
    params: Mapping[str, float],
    *,
    recorded_at: str,
    calibration_ref: str | None = None,
) -> dict:
    """Return a NEW GroundedFact dict with confidence rewritten through
    ``calibrator``/``params``, superseding ``fact``.

    The new fact:

    - carries ``confidence: {score: <calibrated>, method: <calibrator's
      method_name>}`` — plus ``calibrationRef`` when given, which should
      name the serialized params artifact (base.serialize_params) so an
      auditor can trace the score to the fit that produced it;
    - carries ``supersedes: <old fact id>`` and a freshly computed
      ``contentHash``/``id`` (content-addressing means new content = new
      identity);
    - takes ``recorded_at`` from the caller: recalibration is new
      *knowledge* about the same world, so knowledge time moves while
      ``effectiveFrom``/``effectiveTo`` stay untouched. Caller-supplied,
      never wall clock — determinism (and honest knowledge-time replay)
      requires it.

    Refuses (CalibrationError) to recalibrate a fact whose confidence
    method is not ``raw``: calibrators are fitted on raw extractor scores,
    and stacking one calibration on top of another produces a number no
    fit ever validated. Re-run from the raw original instead.

    The input ``fact`` is not mutated. Store supersession (marking the old
    fact superseded) happens when the caller ingests the result.
    """
    conf = fact.get("confidence")
    if not isinstance(conf, dict) or "score" not in conf or "method" not in conf:
        raise CalibrationError(
            "fact has no confidence {score, method} to recalibrate "
            "(human attestations without machine confidence are not calibrator input)"
        )
    if conf["method"] != "raw":
        raise CalibrationError(
            f"refusing to recalibrate a fact whose confidence.method is "
            f"{conf['method']!r}: calibrators are fitted on raw scores, and "
            "calibrating twice yields a score no fit validated — start from "
            "the raw-scored original"
        )
    old_id = fact.get("id")
    if not old_id:
        raise CalibrationError("fact has no id; cannot record what the new fact supersedes")

    new_fact = copy.deepcopy(fact)
    new_confidence: dict = {
        "score": round(calibrator.apply(conf["score"], params), _SCORE_DECIMALS),
        "method": calibrator.method_name,
    }
    if calibration_ref is not None:
        new_confidence["calibrationRef"] = calibration_ref
    new_fact["confidence"] = new_confidence
    new_fact["supersedes"] = old_id
    new_fact["recordedAt"] = recorded_at

    digest = content_hash(new_fact)
    new_fact["contentHash"] = digest
    new_fact["id"] = f"urn:duly:fact:sha256:{digest}"
    return new_fact
