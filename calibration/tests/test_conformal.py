"""Split-conformal: hand-computed threshold, finite-sample coverage across
seeds, degenerate sets, determinism, and serialization."""

import pytest

from duly_calibration import (
    CalibrationError,
    ConformalCalibrator,
    conformal_coverage,
    deserialize_params,
    guarantee_statement,
    serialize_params,
)

from calibtest_helpers import overconfident_pairs

# Hand-computed example: n=9, alpha=0.2.
# Error scores s_i (score if wrong, 0 if correct):
#   correct pairs  -> 0, 0, 0, 0, 0, 0
#   wrong pairs    -> 0.6, 0.8, 0.9
# sorted: [0, 0, 0, 0, 0, 0, 0.6, 0.8, 0.9]
# k = ceil((9+1) * (1 - 0.2)) = ceil(8.0) = 8  ->  threshold = 8th smallest = 0.8
HAND_PAIRS = [
    (0.95, 1), (0.9, 1), (0.85, 1), (0.7, 1), (0.6, 1), (0.5, 1),
    (0.9, 0), (0.8, 0), (0.6, 0),
]


def test_threshold_matches_hand_computation():
    params = ConformalCalibrator(alpha=0.2).fit(HAND_PAIRS)
    assert params == {"alpha": 0.2, "threshold": 0.8, "nCalibration": 9}


def test_acceptance_is_strict_at_the_threshold():
    cal = ConformalCalibrator(alpha=0.2)
    params = cal.fit(HAND_PAIRS)
    assert cal.accepts(0.85, params) is True
    assert cal.accepts(0.8, params) is False  # exactly at threshold -> abstain
    assert cal.accepts(0.5, params) is False


def test_quantile_index_uses_exact_arithmetic():
    # n=9, alpha=0.1: k = ceil(10 * 0.9) = 9 exactly. Naive float
    # arithmetic can nudge 10*(1-0.1) past 9.0 and ceil to 10 (always
    # abstain). Exact rational k keeps the 9th smallest: 0.9.
    params = ConformalCalibrator(alpha=0.1).fit(HAND_PAIRS)
    assert params["threshold"] == 0.9


def test_too_small_calibration_set_abstains_on_everything():
    # n=3, alpha=0.05: k = ceil(4 * 0.95) = 4 > n. No threshold can
    # certify 5% from three examples; the honest answer is total
    # abstention (threshold 1.0), not a made-up cutoff.
    cal = ConformalCalibrator(alpha=0.05)
    params = cal.fit([(0.9, 1), (0.8, 1), (0.7, 0)])
    assert params["threshold"] == 1.0
    assert cal.accepts(0.999, params) is False
    assert cal.accepts(1.0, params) is False


def test_all_correct_set_is_valid_and_permissive():
    cal = ConformalCalibrator(alpha=0.1)
    params = cal.fit([(0.9, 1)] * 20)
    assert params["threshold"] == 0.0
    assert cal.accepts(0.3, params) is True


def test_all_wrong_set_is_valid_and_restrictive():
    cal = ConformalCalibrator(alpha=0.1)
    params = cal.fit([(0.6, 0), (0.7, 0), (0.8, 0)] * 10)
    assert params["threshold"] == 0.8
    assert cal.accepts(0.75, params) is False


def test_marginal_coverage_holds_across_seeds():
    # The guaranteed event is P(accept AND wrong) <= alpha, marginally.
    # Fit on one draw, measure on a fresh draw, several seeds; allow
    # ~1/sqrt(n) sampling slack on the held-out estimate.
    alpha = 0.1
    cal = ConformalCalibrator(alpha=alpha)
    for seed in range(5):
        fit_pairs = overconfident_pairs(2000, seed=seed)
        heldout = overconfident_pairs(4000, seed=seed + 1000)
        params = cal.fit(fit_pairs)
        report = conformal_coverage(heldout, params)
        assert report["promisedMaxMarginalErrorRate"] == alpha
        assert report["empiricalMarginalErrorRate"] <= alpha + 0.02
        assert report["acceptanceRate"] > 0.2  # the threshold is not vacuous


def test_apply_is_identity():
    cal = ConformalCalibrator(alpha=0.2)
    params = cal.fit(HAND_PAIRS)
    for score in (0.0, 0.4, 0.85, 1.0):
        assert cal.apply(score, params) == score


def test_fit_is_deterministic():
    cal = ConformalCalibrator(alpha=0.2)
    pairs = overconfident_pairs(500, seed=4)
    assert cal.fit(pairs) == cal.fit(list(pairs))


def test_empty_pairs_raise():
    with pytest.raises(CalibrationError, match="empty"):
        ConformalCalibrator(alpha=0.1).fit([])


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5, "0.1"])
def test_invalid_alpha_rejected(alpha):
    with pytest.raises(CalibrationError, match="alpha"):
        ConformalCalibrator(alpha=alpha)


def test_guarantee_statement_is_marginal_and_conditional_honest():
    params = ConformalCalibrator(alpha=0.2).fit(HAND_PAIRS)
    text = guarantee_statement(params)
    assert "marginal" in text
    assert "exchangeable" in text
    assert "does not bound the error rate conditional on acceptance" in text
    assert "0.8" in text and "n=9" in text


def test_serialization_round_trip():
    cal = ConformalCalibrator(alpha=0.2)
    params = cal.fit(HAND_PAIRS)
    blob = serialize_params(
        cal.method_name, params, n_samples=9, fitted_at="2026-07-29T00:00:00Z"
    )
    method, restored = deserialize_params(blob)
    assert method == "conformal"
    assert restored == params
    assert cal.accepts(0.85, restored) is True
