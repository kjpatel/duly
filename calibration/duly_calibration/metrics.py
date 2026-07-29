"""Validation harness: is a fitted calibrator actually better, and does a
conformal threshold actually deliver its promised coverage?

Everything here is measurement on **held-out** labeled pairs — pairs the
calibrator was not fitted on. Measuring on the fit set flatters every
method and is exactly the kind of quiet self-grading this repo forbids.

Metrics
-------
- **ECE** (expected calibration error): partition [0,1] into equal-width
  bins; within each bin compare mean predicted score against the empirical
  fraction correct; report the sample-weighted mean absolute gap. The
  standard headline number for "do 0.9s come true 90% of the time". It is
  binning-sensitive (bin count is an explicit, reported parameter) and 0.0
  ECE on a finite sample never means "calibrated", only "not measurably
  miscalibrated at this resolution".
- **Brier score**: mean squared error of the score against the 0/1 label.
  Proper (unlike ECE), so it also rewards discrimination, not just
  calibration; useful as a sanity check that calibration didn't destroy
  ranking information.
- **Conformal coverage report**: the empirical rate of the guaranteed
  event (accept AND wrong) versus the promised alpha, plus the acceptance
  rate and the *conditional* error rate among accepted facts — reported
  for honesty precisely because the guarantee does NOT bound it (see
  conformal.py).
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .base import CalibrationError, Calibrator, Pair, validate_pairs

__all__ = [
    "reliability_bins",
    "expected_calibration_error",
    "brier_score",
    "evaluate",
    "conformal_coverage",
    "improvement_report",
]


def reliability_bins(pairs: Sequence[Pair], *, n_bins: int = 10) -> list[dict]:
    """Equal-width reliability table. Each row: bin bounds, count, mean
    predicted score, empirical accuracy. Empty bins are omitted (they
    carry no evidence and would divide by zero)."""
    if n_bins < 1:
        raise CalibrationError(f"n_bins must be >= 1, got {n_bins!r}")
    clean = validate_pairs(pairs)
    counts = [0] * n_bins
    score_sums = [0.0] * n_bins
    correct_sums = [0] * n_bins
    for score, label in clean:
        idx = min(int(score * n_bins), n_bins - 1)  # score 1.0 joins the top bin
        counts[idx] += 1
        score_sums[idx] += score
        correct_sums[idx] += label
    table = []
    for idx in range(n_bins):
        if counts[idx] == 0:
            continue
        table.append({
            "lo": idx / n_bins,
            "hi": (idx + 1) / n_bins,
            "count": counts[idx],
            "meanScore": score_sums[idx] / counts[idx],
            "accuracy": correct_sums[idx] / counts[idx],
        })
    return table


def expected_calibration_error(pairs: Sequence[Pair], *, n_bins: int = 10) -> float:
    """Binned ECE: sum over bins of (bin weight) * |mean score - accuracy|."""
    clean = validate_pairs(pairs)
    n = len(clean)
    return sum(
        (row["count"] / n) * abs(row["meanScore"] - row["accuracy"])
        for row in reliability_bins(clean, n_bins=n_bins)
    )


def brier_score(pairs: Sequence[Pair]) -> float:
    """Mean squared error of scores against 0/1 labels. Lower is better;
    a proper scoring rule, unlike ECE."""
    clean = validate_pairs(pairs)
    return sum((score - label) ** 2 for score, label in clean) / len(clean)


def evaluate(pairs: Sequence[Pair], *, n_bins: int = 10) -> dict:
    """Calibration quality of a set of (score, correct) pairs — typically
    scores already passed through a fitted calibrator, on held-out labels.

    Returns ``{"nSamples", "nBins", "ece", "brier", "bins"}``. The bin
    count is included because ECE is meaningless without it.
    """
    clean = validate_pairs(pairs)
    return {
        "nSamples": len(clean),
        "nBins": n_bins,
        "ece": expected_calibration_error(clean, n_bins=n_bins),
        "brier": brier_score(clean),
        "bins": reliability_bins(clean, n_bins=n_bins),
    }


def conformal_coverage(pairs: Sequence[Pair], params: Mapping[str, float]) -> dict:
    """Empirical check of a fitted conformal threshold on held-out pairs.

    Returns:
    - ``promisedMaxMarginalErrorRate`` — the alpha the threshold certifies;
    - ``empiricalMarginalErrorRate`` — observed P(accept AND wrong); this is
      the quantity the guarantee bounds and should sit at or below alpha
      (up to ~1/sqrt(n) sampling noise);
    - ``acceptanceRate`` — how often the threshold lets a fact through;
    - ``errorRateAmongAccepted`` — observed P(wrong | accepted), or None if
      nothing was accepted. Reported for transparency; the conformal
      guarantee does NOT bound this conditional rate (see conformal.py) —
      never quote it as the promised number.
    """
    clean = validate_pairs(pairs)
    threshold = params["threshold"]
    n = len(clean)
    accepted = sum(1 for s, _ in clean if s > threshold)
    errors = sum(1 for s, y in clean if s > threshold and y == 0)
    return {
        "promisedMaxMarginalErrorRate": params["alpha"],
        "empiricalMarginalErrorRate": errors / n,
        "acceptanceRate": accepted / n,
        "errorRateAmongAccepted": (errors / accepted) if accepted else None,
        "nSamples": n,
    }


def improvement_report(
    calibrator: Calibrator,
    fit_pairs: Sequence[Pair],
    heldout_pairs: Sequence[Pair],
    *,
    n_bins: int = 10,
) -> dict:
    """Fit on one split, score the other: the honest before/after picture.

    Returns ``{"method", "params", "before", "after"}`` where before/after
    are :func:`evaluate` results on the held-out pairs with raw versus
    calibrated scores. For conformal (whose apply is the identity) the
    before/after ECE will match by construction — use
    :func:`conformal_coverage` for the check that method actually makes.
    """
    params = calibrator.fit(fit_pairs)
    heldout = validate_pairs(heldout_pairs)
    calibrated = [(calibrator.apply(s, params), y) for s, y in heldout]
    return {
        "method": calibrator.method_name,
        "params": params,
        "before": evaluate(heldout, n_bins=n_bins),
        "after": evaluate(calibrated, n_bins=n_bins),
    }
