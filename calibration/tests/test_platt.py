"""Platt scaling: parameter recovery, convergence, determinism,
serialization, and edge cases."""

import pytest

from duly_calibration import (
    CalibrationError,
    PlattCalibrator,
    deserialize_params,
    expected_calibration_error,
    serialize_params,
)

from calibtest_helpers import overconfident_pairs

CAL = PlattCalibrator()


def test_fit_recovers_known_slope():
    # Scores inflated by T=2.5 correspond to a Platt slope a ~= 1/2.5 = 0.4
    # and no bias (b ~= 0); Platt target smoothing biases the fit slightly,
    # so bounds are loose.
    params = CAL.fit(overconfident_pairs(4000, seed=21, inflate=2.5))
    assert 0.3 < params["a"] < 0.5
    assert abs(params["b"]) < 0.2


def test_fit_improves_heldout_ece():
    fit_pairs = overconfident_pairs(4000, seed=21)
    heldout = overconfident_pairs(4000, seed=77)
    params = CAL.fit(fit_pairs)
    before = expected_calibration_error(heldout)
    after = expected_calibration_error([(CAL.apply(s, params), y) for s, y in heldout])
    assert before > 0.10
    assert after < before
    assert after < 0.05


def test_apply_is_monotone_for_positive_slope():
    params = {"a": 0.4, "b": 0.1}
    scores = [i / 20 for i in range(21)]
    calibrated = [CAL.apply(s, params) for s in scores]
    assert calibrated == sorted(calibrated)
    assert all(0.0 <= c <= 1.0 for c in calibrated)


def test_identity_params_are_near_identity():
    for score in (0.1, 0.5, 0.73, 0.9):
        assert CAL.apply(score, {"a": 1.0, "b": 0.0}) == pytest.approx(score, abs=1e-9)


def test_fit_is_deterministic():
    pairs = overconfident_pairs(500, seed=5)
    assert CAL.fit(pairs) == CAL.fit(list(pairs))


def test_fit_converges_on_separable_pairs():
    # Perfectly separable labels diverge under raw MLE; Platt's smoothed
    # targets keep the optimum finite. The fit must converge, stay finite,
    # and not fabricate hard 0/1 outputs.
    pairs = [(0.9, 1), (0.95, 1), (0.85, 1), (0.1, 0), (0.05, 0), (0.15, 0)]
    params = CAL.fit(pairs)
    assert params["a"] > 0
    assert 0.0 < CAL.apply(0.99, params) < 1.0
    assert 0.0 < CAL.apply(0.01, params) < 1.0


def test_boundary_scores_are_clipped_not_fatal():
    pairs = [(0.0, 0), (1.0, 1), (0.9, 1), (0.2, 0), (0.7, 1), (0.4, 0)]
    params = CAL.fit(pairs)
    assert 0.0 <= CAL.apply(0.0, params) <= 1.0
    assert 0.0 <= CAL.apply(1.0, params) <= 1.0


def test_empty_pairs_raise():
    with pytest.raises(CalibrationError, match="empty"):
        CAL.fit([])


@pytest.mark.parametrize("label", [0, 1])
def test_single_class_raises(label):
    with pytest.raises(CalibrationError, match="degenerate"):
        CAL.fit([(0.6, label), (0.8, label), (0.9, label)])


def test_identical_scores_terminate_with_constant_calibrator():
    # All scores equal carries zero slope information. The fit must
    # terminate deterministically (Hessian ridge keeps it solvable) with
    # a ~ 0, i.e. a constant output at the pooled base rate — not hang,
    # and not invent a slope from nothing.
    params = CAL.fit([(0.5, 1), (0.5, 0)] * 10)
    assert params["a"] == pytest.approx(0.0, abs=1e-9)
    assert CAL.apply(0.1, params) == pytest.approx(CAL.apply(0.9, params), abs=1e-9)
    assert CAL.apply(0.5, params) == pytest.approx(0.5, abs=1e-6)


def test_serialization_round_trip():
    params = CAL.fit(overconfident_pairs(300, seed=9))
    blob = serialize_params(
        CAL.method_name, params, n_samples=300,
        fitted_at="2026-07-29T00:00:00Z", dataset="synthetic:seed=9",
    )
    assert blob["fit"]["dataset"] == "synthetic:seed=9"
    method, restored = deserialize_params(blob)
    assert method == "platt"
    assert restored == params
    assert CAL.apply(0.87, restored) == CAL.apply(0.87, params)
