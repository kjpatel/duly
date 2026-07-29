"""Calibrator registry and the versioned params envelope: strict method
names, mandatory provenance, and loud failure on malformed artifacts."""

import pytest

from duly_calibration import (
    CalibrationError,
    ConformalCalibrator,
    PlattCalibrator,
    TemperatureCalibrator,
    deserialize_params,
    get_calibrator,
    serialize_params,
)


def test_get_calibrator_by_spec_method_name():
    assert isinstance(get_calibrator("temperature"), TemperatureCalibrator)
    assert isinstance(get_calibrator("platt"), PlattCalibrator)
    conformal = get_calibrator("conformal", alpha=0.05)
    assert isinstance(conformal, ConformalCalibrator)
    assert conformal.alpha == 0.05


def test_method_names_match_spec_enum():
    # spec/grounded-facts.md D5: method in raw | temperature | platt | conformal.
    assert TemperatureCalibrator.method_name == "temperature"
    assert PlattCalibrator.method_name == "platt"
    assert ConformalCalibrator.method_name == "conformal"


def test_conformal_requires_explicit_alpha():
    with pytest.raises(CalibrationError, match="alpha"):
        get_calibrator("conformal")


def test_alpha_rejected_for_non_conformal():
    with pytest.raises(CalibrationError, match="alpha"):
        get_calibrator("temperature", alpha=0.1)


def test_unknown_and_raw_methods_rejected():
    with pytest.raises(CalibrationError, match="unknown"):
        get_calibrator("isotonic")
    with pytest.raises(CalibrationError, match="raw"):
        get_calibrator("raw")  # raw is the absence of calibration


def test_serialize_requires_provenance():
    with pytest.raises(CalibrationError, match="n_samples"):
        serialize_params("temperature", {"temperature": 2.0}, n_samples=0,
                         fitted_at="2026-07-29T00:00:00Z")
    with pytest.raises(CalibrationError, match="fitted_at"):
        serialize_params("temperature", {"temperature": 2.0}, n_samples=10, fitted_at="")


def test_serialize_rejects_missing_or_nonfinite_params():
    with pytest.raises(CalibrationError, match="missing keys"):
        serialize_params("platt", {"a": 0.4}, n_samples=10, fitted_at="2026-07-29T00:00:00Z")
    with pytest.raises(CalibrationError, match="finite"):
        serialize_params("temperature", {"temperature": float("inf")},
                         n_samples=10, fitted_at="2026-07-29T00:00:00Z")


def test_deserialize_rejects_malformed_blobs():
    good = serialize_params("temperature", {"temperature": 2.0},
                            n_samples=10, fitted_at="2026-07-29T00:00:00Z")
    with pytest.raises(CalibrationError, match="formatVersion"):
        deserialize_params({**good, "formatVersion": 99})
    with pytest.raises(CalibrationError, match="unknown"):
        deserialize_params({**good, "method": "isotonic"})
    with pytest.raises(CalibrationError, match="missing keys"):
        deserialize_params({**good, "params": {}})
    with pytest.raises(CalibrationError, match="finite"):
        deserialize_params({**good, "params": {"temperature": float("nan")}})


def test_envelope_is_json_round_trippable():
    import json

    blob = serialize_params(
        "conformal", {"alpha": 0.1, "threshold": 0.85, "nCalibration": 500},
        n_samples=500, fitted_at="2026-07-29T00:00:00Z", dataset="review-queue:export-0007",
    )
    restored = json.loads(json.dumps(blob))
    assert deserialize_params(restored) == deserialize_params(blob)
    assert restored["fit"]["dataset"] == "review-queue:export-0007"
