"""Temperature scaling: recovery of known miscalibration, determinism,
serialization, and edge cases."""

import pytest

from duly_calibration import (
    CalibrationError,
    TemperatureCalibrator,
    deserialize_params,
    expected_calibration_error,
    serialize_params,
)

from calibtest_helpers import overconfident_pairs

CAL = TemperatureCalibrator()


def test_fit_recovers_known_temperature():
    # Scores were inflated by T=2.5 by construction; NLL fitting should
    # find approximately that temperature.
    pairs = overconfident_pairs(4000, seed=11, inflate=2.5)
    params = CAL.fit(pairs)
    assert 2.1 < params["temperature"] < 2.9


def test_fit_improves_heldout_ece():
    fit_pairs = overconfident_pairs(4000, seed=11)
    heldout = overconfident_pairs(4000, seed=99)
    params = CAL.fit(fit_pairs)
    before = expected_calibration_error(heldout)
    after = expected_calibration_error([(CAL.apply(s, params), y) for s, y in heldout])
    assert before > 0.10  # the synthetic miscalibration is real
    assert after < before
    assert after < 0.05


def test_apply_identity_at_temperature_one():
    for score in (0.1, 0.5, 0.73, 0.9):
        assert CAL.apply(score, {"temperature": 1.0}) == pytest.approx(score, abs=1e-9)


def test_apply_softens_when_t_above_one():
    assert CAL.apply(0.95, {"temperature": 2.0}) < 0.95
    assert CAL.apply(0.05, {"temperature": 2.0}) > 0.05  # pulled toward 0.5 from below too


def test_apply_is_monotone():
    params = {"temperature": 3.7}
    scores = [i / 20 for i in range(21)]
    calibrated = [CAL.apply(s, params) for s in scores]
    assert calibrated == sorted(calibrated)
    assert all(0.0 <= c <= 1.0 for c in calibrated)


def test_fit_is_deterministic():
    pairs = overconfident_pairs(500, seed=3)
    assert CAL.fit(pairs) == CAL.fit(list(pairs))


def test_boundary_scores_are_clipped_not_fatal():
    pairs = [(0.0, 0), (1.0, 1), (0.9, 1), (0.2, 0), (0.7, 1), (0.4, 0)]
    params = CAL.fit(pairs)
    assert params["temperature"] > 0
    assert 0.0 <= CAL.apply(0.0, params) <= 1.0
    assert 0.0 <= CAL.apply(1.0, params) <= 1.0


def test_empty_pairs_raise():
    with pytest.raises(CalibrationError, match="empty"):
        CAL.fit([])


@pytest.mark.parametrize("label", [0, 1])
def test_single_class_raises(label):
    with pytest.raises(CalibrationError, match="degenerate"):
        CAL.fit([(0.6, label), (0.8, label), (0.9, label)])


def test_score_out_of_range_raises():
    with pytest.raises(CalibrationError, match=r"\[0,1\]"):
        CAL.fit([(1.2, 1), (0.4, 0)])
    with pytest.raises(CalibrationError, match=r"\[0,1\]"):
        CAL.apply(-0.1, {"temperature": 1.5})


def test_nonpositive_temperature_rejected_by_apply():
    with pytest.raises(CalibrationError, match="positive"):
        CAL.apply(0.5, {"temperature": 0.0})


def test_serialization_round_trip():
    params = CAL.fit(overconfident_pairs(300, seed=7))
    blob = serialize_params(
        CAL.method_name, params, n_samples=300, fitted_at="2026-07-29T00:00:00Z"
    )
    assert blob["formatVersion"] == 1
    assert blob["fit"] == {"nSamples": 300, "fittedAt": "2026-07-29T00:00:00Z"}
    method, restored = deserialize_params(blob)
    assert method == "temperature"
    assert restored == params
    assert CAL.apply(0.87, restored) == CAL.apply(0.87, params)
