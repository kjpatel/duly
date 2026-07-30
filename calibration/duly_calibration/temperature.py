"""Temperature scaling: one shared scalar that softens (or sharpens) scores.

The model
---------
A raw score ``s`` is mapped through its logit and back:

    calibrated(s) = sigmoid(logit(s) / T)

``T > 1`` shrinks logits toward zero — the classic fix for the systematic
overconfidence of modern neural extractors (Guo et al. 2017, "On Calibration
of Modern Neural Networks"). ``T < 1`` sharpens; ``T = 1`` is the identity.
One parameter means it cannot overfit small labeled sets, which is exactly
the regime the review queue will start in — but also means it can only fix
*uniform* over/underconfidence, never a score-dependent bias (Platt's two
parameters, or binning methods, handle those).

Fitting
-------
``fit`` minimizes the negative log-likelihood of the labels under the
calibrated scores, by golden-section search on ln T over T ∈ [1e-3, 1e3].
The NLL is convex in 1/T (logistic regression in a single scale parameter),
hence unimodal in T and in ln T, so golden-section converges to the global
minimum. A fixed 200 iterations shrinks the bracket by ~0.618^200 — far
below float resolution — with no tolerance parameter, no randomness, and no
data-dependent iteration count: same pairs in, same T out, byte for byte.

What this module does NOT do: ship a fitted T. There is no labeled data for
any real extractor in this repository yet (that arrives with the M3 review
queue), so any T you see in tests was fitted to synthetic data to prove the
math, not to bless an extractor.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .base import (
    CalibrationError,
    Pair,
    clip_probability,
    logit,
    sigmoid,
    softplus,
    validate_pairs,
)

__all__ = ["TemperatureCalibrator", "nll"]

# Search bracket for T, generous on both sides; and the fixed iteration
# count that makes the search deterministic (bracket width 6.9 - (-6.9) in
# ln-space times 0.618^200 is ~1e-41, i.e. exhausted double precision).
_LN_T_LO = math.log(1e-3)
_LN_T_HI = math.log(1e3)
_ITERATIONS = 200
_INV_PHI = (math.sqrt(5.0) - 1.0) / 2.0


def nll(pairs: Sequence[Pair], temperature: float) -> float:
    """Mean negative log-likelihood of labels under temperature-scaled scores.

    Computed via softplus on the scaled logit for numerical stability at
    extreme scores; scores are boundary-clipped by 1e-6 (see base.py).
    """
    total = 0.0
    for score, label in pairs:
        f = logit(clip_probability(score)) / temperature
        total += softplus(-f) if label == 1 else softplus(f)
    return total / len(pairs)


class TemperatureCalibrator:
    """Temperature scaling (spec confidence.method = ``temperature``)."""

    method_name = "temperature"

    def fit(self, pairs: Sequence[Pair]) -> dict[str, float]:
        """Fit T by NLL minimization; returns ``{"temperature": T}``.

        Raises CalibrationError on an empty set or a single-class set — on
        all-correct (or all-wrong) labels the likelihood is maximized by
        driving every score to 1 (or 0), which would fabricate certainty
        rather than measure it.
        """
        clean = validate_pairs(pairs, require_both_classes=True)
        # Golden-section search on t = ln T. NLL is unimodal in t (see
        # module docstring), so this finds the global minimum.
        lo, hi = _LN_T_LO, _LN_T_HI
        for _ in range(_ITERATIONS):
            mid_lo = hi - _INV_PHI * (hi - lo)
            mid_hi = lo + _INV_PHI * (hi - lo)
            if nll(clean, math.exp(mid_lo)) <= nll(clean, math.exp(mid_hi)):
                hi = mid_hi
            else:
                lo = mid_lo
        return {"temperature": math.exp((lo + hi) / 2.0)}

    def apply(self, score: float, params: Mapping[str, float]) -> float:
        """sigmoid(logit(score) / T). Monotone in ``score``, so score
        rankings survive calibration; only the probability values move."""
        temperature = params["temperature"]
        if not (isinstance(temperature, (int, float)) and temperature > 0.0):
            raise CalibrationError(f"temperature must be positive, got {temperature!r}")
        return sigmoid(logit(clip_probability(score)) / temperature)
