"""Tests for assessment integration with multi-profile sensors."""

from types import SimpleNamespace

from custom_components.fitage.assessment import assess_measurement
from custom_components.fitage.sensor import FeelfitMeasurementSensor


def test_measurement_sensor_never_falls_back_to_another_profile() -> None:
    """A missing profile cannot expose the first profile's measurement."""
    measurement = {"weight": 70, "height": 175, "bmi": 22, "gender": 1}
    coordinator = SimpleNamespace(
        data={
            "profiles": [
                {
                    "user_info": {"user_id": "profile-a", "area_code": "NL"},
                    "measurements": {"last_measurement": measurement},
                    "assessments": assess_measurement(measurement, {"area_code": "NL"}),
                }
            ]
        }
    )
    sensor = FeelfitMeasurementSensor(
        coordinator,
        "entry",
        "measurement_bmi",
        "BMI",
        None,
        "bmi",
        "profile-b",
    )

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_sensor_uses_precomputed_assessment_for_its_profile() -> None:
    """Entity matching uses profile ID and the internal measurement key."""
    measurement = {"weight": 70, "height": 175, "bmi": 25, "gender": 1}
    assessments = assess_measurement(measurement, {"area_code": "NL"})
    coordinator = SimpleNamespace(
        data={
            "profiles": [
                {
                    "user_info": {"user_id": "profile-a"},
                    "measurements": {"last_measurement": measurement},
                    "assessments": assessments,
                }
            ]
        }
    )
    sensor = FeelfitMeasurementSensor(
        coordinator,
        "entry",
        "measurement_bmi",
        "BMI",
        None,
        "bmi",
        "profile-a",
    )

    assert sensor.native_value == 25
    assert sensor.extra_state_attributes["assessment"] == "overweight"
