"""Validation harness: hand-computed ECE/Brier, reliability bins, the
before/after improvement report on known-miscalibrated synthetic data,
and the conformal coverage report shape."""

import pytest

from duly_calibration import (
    CalibrationError,
    ConformalCalibrator,
    PlattCalibrator,
    TemperatureCalibrator,
    brier_score,
    conformal_coverage,
    evaluate,
    expected_calibration_error,
    improvement_report,
    reliability_bins,
)

from calibtest_helpers import overconfident_pairs


def test_ece_hand_computed_single_bin():
    # Four scores of 0.95 land in the top bin; 3 of 4 correct.
    # ECE = (4/4) * |0.95 - 0.75| = 0.2
    pairs = [(0.95, 1), (0.95, 1), (0.95, 1), (0.95, 0)]
    assert expected_calibration_error(pairs) == pytest.approx(0.2)


def test_ece_hand_computed_two_bins():
    # Bin [0.6, 0.7): two 0.65 scores, one correct -> gap |0.65 - 0.5| = 0.15, weight 2/4
    # Bin [0.9, 1.0]: two 0.95 scores, both correct -> gap |0.95 - 1.0| = 0.05, weight 2/4
    # ECE = 0.5*0.15 + 0.5*0.05 = 0.1
    pairs = [(0.65, 1), (0.65, 0), (0.95, 1), (0.95, 1)]
    assert expected_calibration_error(pairs) == pytest.approx(0.1)


def test_perfectly_calibrated_bins_score_zero():
    pairs = [(0.75, 1), (0.75, 1), (0.75, 1), (0.75, 0)]  # 0.75 predicted, 0.75 observed
    assert expected_calibration_error(pairs) == pytest.approx(0.0)


def test_brier_hand_computed():
    assert brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)
    assert brier_score([(0.5, 1)]) == pytest.approx(0.25)
    assert brier_score([(0.8, 1), (0.8, 0)]) == pytest.approx((0.04 + 0.64) / 2)


def test_score_of_exactly_one_joins_top_bin():
    bins = reliability_bins([(1.0, 1), (0.97, 1)], n_bins=10)
    assert len(bins) == 1
    assert bins[0]["count"] == 2 and bins[0]["hi"] == 1.0


def test_reliability_bins_omit_empty_bins():
    bins = reliability_bins([(0.05, 0), (0.95, 1)], n_bins=10)
    assert [(b["lo"], b["count"]) for b in bins] == [(0.0, 1), (0.9, 1)]


def test_evaluate_reports_shape():
    report = evaluate(overconfident_pairs(200, seed=1), n_bins=8)
    assert report["nSamples"] == 200
    assert report["nBins"] == 8
    assert 0.0 <= report["ece"] <= 1.0
    assert 0.0 <= report["brier"] <= 1.0
    assert sum(b["count"] for b in report["bins"]) == 200


def test_empty_pairs_raise():
    with pytest.raises(CalibrationError, match="empty"):
        evaluate([])
    with pytest.raises(CalibrationError, match="n_bins"):
        expected_calibration_error([(0.5, 1)], n_bins=0)


@pytest.mark.parametrize("calibrator", [TemperatureCalibrator(), PlattCalibrator()])
def test_improvement_report_shows_ece_gain_on_known_miscalibration(calibrator):
    # Scores are overconfident by construction (T=2.5); fitting on one
    # split must cut ECE on the other. This asserts the machinery works
    # on synthetic data; it says nothing about any real extractor.
    report = improvement_report(
        calibrator,
        overconfident_pairs(4000, seed=31),
        overconfident_pairs(4000, seed=32),
    )
    assert report["method"] == calibrator.method_name
    assert report["before"]["ece"] > 0.10
    assert report["after"]["ece"] < report["before"]["ece"]
    assert report["after"]["ece"] < 0.05
    # Calibration must not destroy ranking quality (Brier is proper).
    assert report["after"]["brier"] <= report["before"]["brier"]


def test_conformal_coverage_report_promised_vs_empirical():
    cal = ConformalCalibrator(alpha=0.15)
    params = cal.fit(overconfident_pairs(2000, seed=41))
    report = conformal_coverage(overconfident_pairs(4000, seed=42), params)
    assert report["promisedMaxMarginalErrorRate"] == 0.15
    assert report["empiricalMarginalErrorRate"] <= 0.15 + 0.02
    assert 0.0 < report["acceptanceRate"] <= 1.0
    assert report["nSamples"] == 4000
    # The conditional rate is reported but is NOT the guaranteed quantity;
    # it must always be at least the marginal rate.
    if report["errorRateAmongAccepted"] is not None:
        assert report["errorRateAmongAccepted"] >= report["empiricalMarginalErrorRate"]


def test_conformal_coverage_with_total_abstention_reports_none():
    report = conformal_coverage(
        [(0.9, 1), (0.4, 0)], {"alpha": 0.05, "threshold": 1.0, "nCalibration": 3}
    )
    assert report["acceptanceRate"] == 0.0
    assert report["empiricalMarginalErrorRate"] == 0.0
    assert report["errorRateAmongAccepted"] is None
