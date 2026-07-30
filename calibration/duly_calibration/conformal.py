"""Split-conformal abstention thresholds with a finite-sample guarantee.

This is the piece that feeds abstention policy (spec D5): the fitted
artifact is not a remapped score but a **score threshold** — accept the
fact when ``score > threshold``, abstain otherwise — chosen so that a
precise, distribution-free error guarantee holds.

Construction
------------
Given calibration pairs ``(score_i, correct_i)`` and a target error rate
``alpha``, define for each pair the nonconformity value

    s_i = score_i   if correct_i == 0      (an accepted wrong fact = an error)
    s_i = 0         if correct_i == 1      (accepting a correct fact is never an error)

and set the threshold to the ``k``-th smallest of {s_1..s_n} with the
standard finite-sample quantile correction

    k = ceil((n + 1) * (1 - alpha))

(computed in exact rational arithmetic so float rounding can never move k).
If ``k > n`` — the calibration set is too small to certify alpha — the
threshold is 1.0: accept nothing, abstain on everything. That degenerate
outcome is the honest answer for tiny n, not a bug.

The guarantee (read the fine print)
-----------------------------------
**Marginal coverage:** if a new example is exchangeable with the
calibration pairs, then

    P( score_new > threshold  AND  fact is wrong ) <= alpha

i.e. the probability that the system *accepts an incorrect fact* is at most
alpha, in finite samples, with no distributional assumptions beyond
exchangeability. Proof sketch: the error event is exactly
{s_new > threshold}, and by exchangeability the rank of s_new among the
n+1 values is uniform, so P(s_new > k-th smallest) <= (n+1-k)/(n+1) <= alpha.

What this is **not**: a bound on the error rate *among accepted facts*
(P(wrong | accepted)), which is the conditional quantity a dashboard will
naturally display. P(wrong | accepted) = P(wrong AND accepted)/P(accepted),
so the marginal bound implies P(wrong | accepted) <= alpha / P(accepted).
When acceptance is high the two are close; when the system abstains a lot
they diverge. Report both; promise only the marginal one. Overstating this
guarantee would be confident wrongness about confident wrongness.

Assumptions that can break it
-----------------------------
- **Exchangeability**: calibration pairs and production traffic must come
  from the same distribution. A new document template, a new extractor
  version, or seasonal drift breaks it — recalibrate on fresh labels
  (which is why fitted params carry provenance; see base.serialize_params).
- The guarantee is over the joint draw of calibration set and new example;
  a specific fitted threshold's conditional error rate fluctuates around
  alpha at roughly 1/sqrt(n).

As everywhere in this package: no fitted threshold ships with this repo.
Labeled pairs arrive with the M3 review queue; until then this is math
awaiting evidence.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Mapping, Sequence

from .base import CalibrationError, Pair, validate_pairs

__all__ = ["ConformalCalibrator", "guarantee_statement"]


def guarantee_statement(params: Mapping[str, float]) -> str:
    """The precise claim a fitted threshold supports, as auditable prose.

    Deliberately worded as a *marginal* guarantee under exchangeability —
    see the module docstring for why the conditional version must not be
    promised."""
    alpha = params["alpha"]
    n = int(params["nCalibration"])
    threshold = params["threshold"]
    return (
        f"Accepting facts with score > {threshold!r} keeps the probability of "
        f"accepting an incorrect fact at or below {alpha!r} (marginal coverage, "
        f"finite-sample, from n={n} calibration pairs). Valid only while "
        "production traffic remains exchangeable with the calibration data; "
        "this does not bound the error rate conditional on acceptance."
    )


class ConformalCalibrator:
    """Split-conformal abstention (spec confidence.method = ``conformal``).

    Construct with the target error rate: ``ConformalCalibrator(alpha=0.05)``.
    ``fit`` returns ``{"alpha", "threshold", "nCalibration"}``; the threshold
    flows to a rule pack's abstention policy, applied by the kernel at
    decision time (abstention is policy, not data — spec D5).
    """

    method_name = "conformal"

    def __init__(self, alpha: float):
        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not (0.0 < alpha < 1.0):
            raise CalibrationError(f"alpha must be in (0, 1), got {alpha!r}")
        self.alpha = float(alpha)

    def fit(self, pairs: Sequence[Pair]) -> dict[str, float]:
        """Derive the abstention threshold from labeled pairs.

        Unlike temperature/Platt, degenerate single-class sets are valid
        here: all-correct yields threshold 0.0 (no observed way to err —
        but only n pairs of evidence, and k <= n must still hold), and
        all-wrong pushes the threshold to the top of the observed scores.
        Empty sets still raise.
        """
        clean = validate_pairs(pairs, require_both_classes=False)
        n = len(clean)
        # Error scores: the event "accept AND wrong" for a pair with score s
        # is exactly {s_i > t}; correct pairs can never contribute an error.
        scores = sorted((s if y == 0 else 0.0) for s, y in clean)
        # Exact rational k: float ceil((n+1)*(1-alpha)) can land on the
        # wrong integer when (n+1)*(1-alpha) is a whole number that float
        # arithmetic nudges past itself.
        k = math.ceil(Fraction(n + 1) * (1 - Fraction(str(self.alpha))))
        threshold = scores[k - 1] if k <= n else 1.0
        return {"alpha": self.alpha, "threshold": threshold, "nCalibration": n}

    def apply(self, score: float, params: Mapping[str, float]) -> float:
        """Identity, by design. Conformal calibration does not remap scores
        into better probabilities — it certifies a threshold. A fact whose
        confidence.method is 'conformal' carries its raw score plus (via
        calibrationRef) the artifact whose threshold governs abstention."""
        if not (0.0 <= score <= 1.0):
            raise CalibrationError(f"score must be in [0,1], got {score!r}")
        return float(score)

    def accepts(self, score: float, params: Mapping[str, float]) -> bool:
        """The abstention decision: True = use the fact, False = abstain.

        Strict inequality is load-bearing: the guarantee's error event is
        {s > threshold}, so a score exactly at the threshold abstains."""
        if not (0.0 <= score <= 1.0):
            raise CalibrationError(f"score must be in [0,1], got {score!r}")
        return score > params["threshold"]
