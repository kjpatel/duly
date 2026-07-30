"""Shared calibration contract: the ``Calibrator`` protocol, pair validation,
fitted-parameter serialization, and numeric helpers.

Read this first
---------------
This package ships calibration *machinery*, not calibration. A fitted
temperature, Platt curve, or conformal threshold is only as trustworthy as
the labeled pairs it was fitted on — ``(raw_score, correct)`` pairs where
``correct`` was decided by a human. Until the review queue (M3) produces
those labels for a real extractor, nothing in this repository can honestly
be fitted, and **no fitted parameters ship anywhere in this repo**. A
calibration module that pretended to be fitted would be the exact
confident-wrongness failure duly exists to eliminate (spec D5).

The API is shaped to make silent overclaiming hard:

- ``fit`` demands real pairs and raises :class:`CalibrationError` on empty
  or degenerate input instead of inventing defaults;
- ``apply`` demands explicit fitted params — there is no built-in fallback
  parameter set anywhere in the package;
- serialized params must carry fit provenance (sample count and a
  caller-supplied fit timestamp), so a params blob can never appear to
  come from nowhere.

Determinism: no function in this package reads the clock or draws random
numbers. Same pairs in, same params out, byte for byte. That is why
``fitted_at`` is an argument to :func:`serialize_params`, never a call to
``datetime.now()``.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Protocol, Sequence

__all__ = [
    "Pair",
    "CalibrationError",
    "Calibrator",
    "PARAMS_FORMAT_VERSION",
    "REQUIRED_PARAM_KEYS",
    "validate_pairs",
    "serialize_params",
    "deserialize_params",
    "clip_probability",
    "logit",
    "sigmoid",
    "softplus",
]

# One labeled calibration example: (raw_score in [0,1], correct in {0,1}).
# ``correct`` means a human (or gold data) judged the extracted assertion
# right; it is the label the review queue will eventually produce.
Pair = tuple[float, int]

PARAMS_FORMAT_VERSION = 1

# The exact parameter keys each method's fit() emits and apply() consumes.
# Matches the spec/grounded-facts.md D5 confidence.method enum minus "raw"
# (raw is the absence of calibration and has no parameters).
REQUIRED_PARAM_KEYS: dict[str, frozenset[str]] = {
    "temperature": frozenset({"temperature"}),
    "platt": frozenset({"a", "b"}),
    "conformal": frozenset({"alpha", "threshold", "nCalibration"}),
}


class CalibrationError(ValueError):
    """Unusable calibration input: empty or degenerate pair sets, scores
    outside [0,1], malformed params blobs, or fits that fail to converge.
    Loud failure is the point — never a silently fabricated parameter."""


class Calibrator(Protocol):
    """The common shape of every calibration method in this package.

    - ``method_name`` matches the spec confidence.method enum
      (``temperature`` | ``platt`` | ``conformal``).
    - ``fit(pairs)`` consumes labeled ``(raw_score, correct)`` pairs and
      returns a flat, JSON-safe params dict (see REQUIRED_PARAM_KEYS).
    - ``apply(score, params)`` maps one raw score through the fitted
      transform. For conformal this is the identity — conformal certifies
      an abstention threshold rather than remapping scores; see
      conformal.py for the rationale.

    Params are plain dicts, not objects, because they must round-trip
    through JSON to live in versioned calibration artifacts; use
    :func:`serialize_params` / :func:`deserialize_params` for the
    versioned envelope with fit provenance.
    """

    method_name: str

    def fit(self, pairs: Sequence[Pair]) -> dict[str, float]: ...

    def apply(self, score: float, params: Mapping[str, float]) -> float: ...


# --- numeric helpers ---------------------------------------------------------

# Scores of exactly 0 or 1 have infinite logits. They are clipped to this
# epsilon before the logit transform (documented behavior, not an error:
# real extractors emit hard 0/1 scores all the time).
_EPS = 1e-6


def clip_probability(p: float) -> float:
    """Validate ``p`` is in [0,1] and clip away from the boundaries so the
    logit is finite. Raises CalibrationError outside [0,1]."""
    if not isinstance(p, (int, float)) or isinstance(p, bool) or math.isnan(p):
        raise CalibrationError(f"score must be a number in [0,1], got {p!r}")
    if p < 0.0 or p > 1.0:
        raise CalibrationError(f"score must be in [0,1], got {p!r}")
    return min(max(float(p), _EPS), 1.0 - _EPS)


def logit(p: float) -> float:
    """log(p / (1-p)); callers clip first."""
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    """Numerically stable logistic function."""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def softplus(x: float) -> float:
    """Numerically stable log(1 + e^x); the building block of the logistic
    negative log-likelihood used by both temperature and Platt fitting."""
    return max(x, 0.0) + math.log1p(math.exp(-abs(x)))


# --- pair validation ---------------------------------------------------------

def validate_pairs(
    pairs: Iterable[Pair], *, require_both_classes: bool = False
) -> list[Pair]:
    """Normalize and validate a calibration set.

    Returns ``[(float score, int label), ...]`` in input order (order is
    preserved so fitting is deterministic). Raises CalibrationError when:

    - the set is empty — there is nothing honest to fit to;
    - a score falls outside [0,1] or a label outside {0,1};
    - ``require_both_classes`` and every label is identical. Temperature
      and Platt scaling set this: a single-class set drives the likelihood
      maximum to a boundary (scores pushed to 0 or 1), which is exactly
      the confident-wrongness this repo exists to avoid. Conformal does
      not set it — its quantile construction stays valid on degenerate
      sets (see conformal.py).
    """
    out: list[Pair] = []
    for pair in pairs:
        score, label = pair
        if not isinstance(score, (int, float)) or isinstance(score, bool) or math.isnan(float(score)):
            raise CalibrationError(f"score must be a number in [0,1], got {score!r}")
        if score < 0.0 or score > 1.0:
            raise CalibrationError(f"score must be in [0,1], got {score!r}")
        if label not in (0, 1, False, True):
            raise CalibrationError(f"label must be 0 or 1 (correct/incorrect), got {label!r}")
        out.append((float(score), int(label)))
    if not out:
        raise CalibrationError(
            "calibration set is empty: fitting requires labeled (score, correct) "
            "pairs — for duly these come from human review outcomes, not from thin air"
        )
    if require_both_classes:
        labels = {y for _, y in out}
        if len(labels) == 1:
            which = "correct" if labels == {1} else "incorrect"
            raise CalibrationError(
                f"degenerate calibration set: every example is labeled {which}; "
                "temperature/Platt likelihoods have no interior optimum on a "
                "single-class set and would fabricate extreme confidence — collect "
                "labels of both kinds before fitting"
            )
    return out


# --- versioned params serialization ------------------------------------------

def serialize_params(
    method_name: str,
    params: Mapping[str, float],
    *,
    n_samples: int,
    fitted_at: str,
    dataset: str | None = None,
) -> dict:
    """Wrap fitted params in the versioned artifact envelope.

    Fit provenance is mandatory by design: a params dict without a sample
    count and a fit timestamp is indistinguishable from an invented one.
    ``fitted_at`` is caller-supplied ISO-8601 text — this library never
    reads the wall clock, so re-serializing the same fit yields identical
    bytes. ``dataset`` optionally names the labeled set (e.g. a review-queue
    export id) so an auditor can trace the params to their evidence.
    """
    if method_name not in REQUIRED_PARAM_KEYS:
        raise CalibrationError(
            f"unknown calibration method {method_name!r}; expected one of "
            f"{sorted(REQUIRED_PARAM_KEYS)}"
        )
    missing = REQUIRED_PARAM_KEYS[method_name] - set(params)
    if missing:
        raise CalibrationError(f"params for {method_name!r} missing keys: {sorted(missing)}")
    for key, value in params.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise CalibrationError(f"param {key!r} must be a finite number, got {value!r}")
    if not isinstance(n_samples, int) or isinstance(n_samples, bool) or n_samples < 1:
        raise CalibrationError(f"n_samples must be a positive integer, got {n_samples!r}")
    if not isinstance(fitted_at, str) or not fitted_at:
        raise CalibrationError("fitted_at must be caller-supplied ISO-8601 text (never wall clock)")

    fit: dict = {"nSamples": n_samples, "fittedAt": fitted_at}
    if dataset is not None:
        fit["dataset"] = dataset
    return {
        "formatVersion": PARAMS_FORMAT_VERSION,
        "method": method_name,
        "params": dict(params),
        "fit": fit,
    }


def deserialize_params(blob: Mapping) -> tuple[str, dict[str, float]]:
    """Unwrap a serialized artifact back to ``(method_name, params)``.

    Validates the format version, the method name against the spec enum,
    and the presence/finiteness of that method's required parameter keys,
    so a truncated or hand-edited artifact fails loudly instead of
    producing quietly wrong scores.
    """
    if blob.get("formatVersion") != PARAMS_FORMAT_VERSION:
        raise CalibrationError(
            f"unsupported params formatVersion {blob.get('formatVersion')!r}; "
            f"this library reads version {PARAMS_FORMAT_VERSION}"
        )
    method = blob.get("method")
    if method not in REQUIRED_PARAM_KEYS:
        raise CalibrationError(
            f"unknown calibration method {method!r}; expected one of {sorted(REQUIRED_PARAM_KEYS)}"
        )
    params = blob.get("params")
    if not isinstance(params, Mapping):
        raise CalibrationError("params blob has no 'params' mapping")
    missing = REQUIRED_PARAM_KEYS[method] - set(params)
    if missing:
        raise CalibrationError(f"params for {method!r} missing keys: {sorted(missing)}")
    for key, value in params.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise CalibrationError(f"param {key!r} must be a finite number, got {value!r}")
    return method, dict(params)
