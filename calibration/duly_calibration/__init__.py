"""duly calibration: temperature / Platt / conformal machinery for extractor
confidence (spec/grounded-facts.md D5), plus a validation harness and a
fact-rewrite helper.

THIS PACKAGE SHIPS MATH, NOT CALIBRATION. No fitted parameters exist
anywhere in this repository, because no real labeled (score, correct)
pairs exist yet — they arrive with the M3 review queue, when human
corrections start labeling machine facts correct or incorrect. Until a
calibrator is fitted on such labels and validated on held-out ones
(metrics.py), every confidence score in this repo is what its fact says
it is: an extractor's raw self-report. See calibration/README.md.
"""

from .base import (
    CalibrationError,
    Calibrator,
    Pair,
    PARAMS_FORMAT_VERSION,
    deserialize_params,
    serialize_params,
)
from .conformal import ConformalCalibrator, guarantee_statement
from .facts import recalibrate_fact
from .metrics import (
    brier_score,
    conformal_coverage,
    evaluate,
    expected_calibration_error,
    improvement_report,
    reliability_bins,
)
from .platt import PlattCalibrator
from .temperature import TemperatureCalibrator

__all__ = [
    "CalibrationError",
    "Calibrator",
    "Pair",
    "PARAMS_FORMAT_VERSION",
    "TemperatureCalibrator",
    "PlattCalibrator",
    "ConformalCalibrator",
    "get_calibrator",
    "guarantee_statement",
    "serialize_params",
    "deserialize_params",
    "recalibrate_fact",
    "evaluate",
    "expected_calibration_error",
    "brier_score",
    "reliability_bins",
    "conformal_coverage",
    "improvement_report",
]


def get_calibrator(method: str, *, alpha: float | None = None) -> Calibrator:
    """Construct a calibrator by its spec method name.

    ``alpha`` is required for (and only for) ``conformal`` — a conformal
    threshold without a stated target error rate is not a thing, and a
    default alpha here would be this library quietly choosing the caller's
    risk tolerance.
    """
    if method == "temperature" or method == "platt":
        if alpha is not None:
            raise CalibrationError(f"alpha applies only to conformal, not {method!r}")
        return TemperatureCalibrator() if method == "temperature" else PlattCalibrator()
    if method == "conformal":
        if alpha is None:
            raise CalibrationError(
                "conformal requires an explicit alpha (target error rate); "
                "there is no defensible default"
            )
        return ConformalCalibrator(alpha=alpha)
    raise CalibrationError(
        f"unknown calibration method {method!r}; expected temperature | platt | conformal "
        "(raw is the absence of calibration and needs no calibrator)"
    )
