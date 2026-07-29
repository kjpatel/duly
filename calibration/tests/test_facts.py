"""recalibrate_fact: content-addressing survives the rewrite, the new fact
validates against the spec schema, supersession is recorded, and the
original is untouched."""

import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from duly_calibration import CalibrationError, TemperatureCalibrator, recalibrate_fact
from duly_calibration.facts import canonical, content_hash

from calibtest_helpers import FACT_SCHEMA, load_raw_spec_fact

CAL = TemperatureCalibrator()
PARAMS = {"temperature": 2.5}
RECORDED_AT = "2026-07-29T12:00:00Z"


@pytest.fixture()
def raw_fact() -> dict:
    return load_raw_spec_fact()


@pytest.fixture(scope="module")
def schema_validator() -> Draft202012Validator:
    schema = json.loads(FACT_SCHEMA.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_new_fact_hash_and_id_are_self_consistent(raw_fact):
    new_fact = recalibrate_fact(raw_fact, CAL, PARAMS, recorded_at=RECORDED_AT)
    # The contract's rule (spec D8, as spec/validate.py checks it):
    # contentHash = sha256 of canonical fact minus id/contentHash; id ends with it.
    assert new_fact["contentHash"] == content_hash(new_fact)
    assert new_fact["id"] == f"urn:duly:fact:sha256:{new_fact['contentHash']}"
    # Changed confidence -> changed content -> a NEW fact, never an edit.
    assert new_fact["id"] != raw_fact["id"]


def test_new_fact_validates_against_spec_schema(raw_fact, schema_validator):
    new_fact = recalibrate_fact(
        raw_fact, CAL, PARAMS,
        recorded_at=RECORDED_AT, calibration_ref="calib:temperature:2026-07-29:v1",
    )
    errors = list(schema_validator.iter_errors(new_fact))
    assert errors == []


def test_confidence_supersession_and_knowledge_time(raw_fact):
    new_fact = recalibrate_fact(
        raw_fact, CAL, PARAMS,
        recorded_at=RECORDED_AT, calibration_ref="calib:temperature:2026-07-29:v1",
    )
    expected_score = round(CAL.apply(raw_fact["confidence"]["score"], PARAMS), 6)
    assert new_fact["confidence"] == {
        "score": expected_score,
        "method": "temperature",
        "calibrationRef": "calib:temperature:2026-07-29:v1",
    }
    assert new_fact["supersedes"] == raw_fact["id"]
    assert new_fact["recordedAt"] == RECORDED_AT
    # Everything that is not confidence/supersedes/recordedAt/identity is untouched:
    # recalibration changes what we believe about the score, not the assertion.
    for key in raw_fact:
        if key not in ("id", "contentHash", "confidence", "supersedes", "recordedAt"):
            assert new_fact[key] == raw_fact[key]


def test_original_fact_is_not_mutated(raw_fact):
    before = json.dumps(raw_fact, sort_keys=True)
    recalibrate_fact(raw_fact, CAL, PARAMS, recorded_at=RECORDED_AT)
    assert json.dumps(raw_fact, sort_keys=True) == before


def test_rewrite_is_deterministic(raw_fact):
    a = recalibrate_fact(raw_fact, CAL, PARAMS, recorded_at=RECORDED_AT)
    b = recalibrate_fact(raw_fact, CAL, PARAMS, recorded_at=RECORDED_AT)
    assert canonical(a) == canonical(b)


def test_refuses_already_calibrated_facts(raw_fact):
    already = dict(raw_fact, confidence={"score": 0.9, "method": "platt"})
    with pytest.raises(CalibrationError, match="raw"):
        recalibrate_fact(already, CAL, PARAMS, recorded_at=RECORDED_AT)


def test_refuses_facts_without_confidence(raw_fact):
    attested = {k: v for k, v in raw_fact.items() if k != "confidence"}
    with pytest.raises(CalibrationError, match="confidence"):
        recalibrate_fact(attested, CAL, PARAMS, recorded_at=RECORDED_AT)


def test_refuses_facts_without_id(raw_fact):
    anonymous = {k: v for k, v in raw_fact.items() if k != "id"}
    with pytest.raises(CalibrationError, match="id"):
        recalibrate_fact(anonymous, CAL, PARAMS, recorded_at=RECORDED_AT)
