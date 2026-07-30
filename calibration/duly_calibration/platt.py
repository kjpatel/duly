"""Platt scaling: a two-parameter logistic fit on the logit of raw scores.

The model
---------
    calibrated(s) = sigmoid(a * logit(s) + b)

Where temperature scaling can only rescale logits uniformly, Platt scaling
(Platt 1999, "Probabilistic Outputs for Support Vector Machines...") also
shifts them: ``a`` is a slope (a = 1/T recovers temperature scaling) and
``b`` absorbs a systematic bias — an extractor that is 10 points too sure
across the board. Two parameters still fit safely on modest labeled sets.

Fitting
-------
Maximum likelihood by Newton's method with backtracking (Armijo) line
search, following the numerically careful formulation of Lin, Lin & Weng
2007 ("A note on Platt's probabilistic outputs for support vector
machines"):

- **Target smoothing.** Labels are replaced by Platt's smoothed targets
  t+ = (N+ + 1)/(N+ + 2) and t- = 1/(N- + 2). This is the canonical
  algorithm, and it guarantees the likelihood has a finite maximizer even
  when the pairs are linearly separable (raw MLE would diverge).
- **Convergence criteria** (fixed, documented, deterministic): the
  objective is the *mean* cross-entropy, so every tolerance is per-sample
  and independent of calibration-set size. Stop when the gradient's
  infinity norm falls below 1e-9, or after 100 Newton
  iterations; each step is halved up to 20 times until the Armijo
  sufficient-decrease condition holds. When no decrease exists but the
  gradient inf-norm is already below 1e-6, the objective is flat to float
  precision and the current point is accepted as converged. A 1e-12 ridge
  on the Hessian diagonal guards against singularity. If the gradient
  norm is still above 1e-6 at the iteration cap, ``fit`` raises rather
  than returning a half-converged curve.
- **No randomness anywhere**: fixed start point (a=0, b=ln(N-+1)/(N++1)),
  fixed iteration budget, input order preserved. Same pairs, same params.

Like the rest of this package: no fitted (a, b) ships with the repo. The
labeled pairs required to fit one honestly arrive with the M3 review queue.
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

__all__ = ["PlattCalibrator"]

_MAX_ITERATIONS = 100
_MAX_HALVINGS = 20
_GRAD_TOL = 1e-9          # success criterion
_GRAD_FAIL_TOL = 1e-6     # if still above this at the cap, refuse to return
_ARMIJO_C = 1e-4
_RIDGE = 1e-12


def _objective(xs: list[float], ts: list[float], a: float, b: float) -> float:
    """MEAN cross-entropy against smoothed targets, in stable softplus form:
    F = (1/n) Σ t*softplus(-f) + (1-t)*softplus(f), f = a*x + b.
    The mean (not the sum) is used so the convergence tolerances below are
    per-sample quantities, independent of calibration-set size."""
    total = 0.0
    for x, t in zip(xs, ts):
        f = a * x + b
        total += t * softplus(-f) + (1.0 - t) * softplus(f)
    return total / len(xs)


class PlattCalibrator:
    """Platt scaling (spec confidence.method = ``platt``)."""

    method_name = "platt"

    def fit(self, pairs: Sequence[Pair]) -> dict[str, float]:
        """Fit (a, b) by Newton's method; returns ``{"a": a, "b": b}``.

        Raises CalibrationError on empty or single-class sets (see
        base.validate_pairs — a single-class fit would fabricate extreme
        confidence) and on non-convergence at the iteration cap.
        """
        clean = validate_pairs(pairs, require_both_classes=True)
        xs = [logit(clip_probability(s)) for s, _ in clean]
        n_pos = sum(1 for _, y in clean if y == 1)
        n_neg = len(clean) - n_pos
        # Platt's smoothed targets (see module docstring).
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        ts = [t_pos if y == 1 else t_neg for _, y in clean]

        # Lin-Weng starting point.
        a, b = 0.0, math.log((n_neg + 1.0) / (n_pos + 1.0))
        f_val = _objective(xs, ts, a, b)

        n = float(len(clean))
        for _ in range(_MAX_ITERATIONS):
            # Gradient and Hessian of the mean cross-entropy at (a, b).
            g_a = g_b = 0.0
            h_aa = h_ab = h_bb = 0.0
            for x, t in zip(xs, ts):
                p = sigmoid(a * x + b)
                d = p - t
                w = p * (1.0 - p)
                g_a += d * x
                g_b += d
                h_aa += w * x * x
                h_ab += w * x
                h_bb += w
            g_a, g_b = g_a / n, g_b / n
            h_aa, h_ab, h_bb = h_aa / n, h_ab / n, h_bb / n
            if max(abs(g_a), abs(g_b)) < _GRAD_TOL:
                break
            h_aa += _RIDGE
            h_bb += _RIDGE
            det = h_aa * h_bb - h_ab * h_ab
            if det <= 0.0:
                raise CalibrationError(
                    "Platt fit failed: singular Hessian (are all scores identical?)"
                )
            # Newton direction: solve H @ delta = -g.
            d_a = -(h_bb * g_a - h_ab * g_b) / det
            d_b = -(h_aa * g_b - h_ab * g_a) / det
            slope = g_a * d_a + g_b * d_b  # directional derivative, < 0

            step = 1.0
            for _ in range(_MAX_HALVINGS):
                cand = _objective(xs, ts, a + step * d_a, b + step * d_b)
                if cand <= f_val + _ARMIJO_C * step * slope:
                    break
                step /= 2.0
            else:
                # No decrease found. With a tiny gradient this means the
                # objective is flat to float precision — we are at the
                # optimum as precisely as doubles can express it; stop
                # here. With a large gradient it is a genuine failure.
                if max(abs(g_a), abs(g_b)) <= _GRAD_FAIL_TOL:
                    break
                raise CalibrationError(
                    "Platt fit failed: line search found no decrease "
                    f"(gradient inf-norm {max(abs(g_a), abs(g_b)):.3e})"
                )
            a, b = a + step * d_a, b + step * d_b
            f_val = cand
        else:
            # Iteration cap reached without hitting _GRAD_TOL.
            g_inf = max(abs(g_a), abs(g_b))
            if g_inf > _GRAD_FAIL_TOL:
                raise CalibrationError(
                    f"Platt fit did not converge in {_MAX_ITERATIONS} Newton "
                    f"iterations (gradient inf-norm {g_inf:.3e}); refusing to "
                    "return a half-converged calibration curve"
                )
        return {"a": a, "b": b}

    def apply(self, score: float, params: Mapping[str, float]) -> float:
        """sigmoid(a * logit(score) + b). Monotone when a > 0; a fitted
        a <= 0 would mean raw scores are anti-correlated with correctness,
        which deserves investigation, not silent use — but apply() does not
        second-guess the params it is handed."""
        return sigmoid(params["a"] * logit(clip_probability(score)) + params["b"])
