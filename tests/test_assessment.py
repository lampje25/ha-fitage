"""Tests for FITAGE assessment calculations."""

import math

import pytest

from custom_components.fitage.assessment import (
    _bmr_factor,
    _measurement_age,
    assess_measurement,
    finite_float,
    standard_region,
)


def _known_measurement(height: float = 165) -> dict[str, object]:
    return {
        "weight": 95.15,
        "height": height,
        "birthday": "1990-01-01",
        "time_stamp": 1_735_689_600,
        "gender": 1,
        "bmi": 34.9,
        "bmr": 1700,
        "bodyfat": 35.9,
        "body_fat_mass": 34.16,
        "muscle": 41.5,
        "muscle_ratio": 61.0,
        "sinew": 58.0,
        "muscle_storage_capacity": 2,
        "protein": 14.6,
        "protein_mass": 13.89,
        "subfat": 30.8,
        "visfat": 17,
        "water": 46.4,
        "body_water_mass": 44.15,
        "bone": 3.06,
        "bone_ratio": 3.2,
    }


def test_known_measurement_assessments() -> None:
    """The reconstructed FITAGE result matches the known app report."""
    result = assess_measurement(_known_measurement(), {"area_code": "NL"})

    expected = {
        "weight": "obesity",
        "bmi": "obesity",
        "bodyfat": "excessive",
        "body_fat_mass": "excessive",
        "muscle": "low",
        "sinew": "excellent",
        "muscle_ratio": "excellent",
        "muscle_storage_capacity": "normal",
        "protein": "low",
        "protein_mass": "low",
        "subfat": "high",
        "visfat": "excessive",
        "water": "low",
        "body_water_mass": "low",
        "bone": "average",
        "bone_ratio": "average",
    }
    assert {key: result[key]["assessment"] for key in expected} == expected
    assert result["weight"]["assessment_height"] == 165
    assert result["sinew"]["assessment_height"] == 165
    assert result["muscle_ratio"]["assessment_height"] == 165
    assert result["bmr"]["assessment_height"] == 165
    assert result["muscle_storage_capacity"]["storage_level"] == 2
    assert all(value["standard_region"] == "occident" for value in result.values())


def test_historical_measurement_height_changes_muscle_assessment() -> None:
    """Muscle assessment uses the height stored in each measurement."""
    result_165 = assess_measurement(
        _known_measurement(165), {"height": 176, "area_code": "NL"}
    )
    result_176 = assess_measurement(
        _known_measurement(176), {"height": 165, "area_code": "NL"}
    )

    assert result_165["sinew"]["assessment"] == "excellent"
    assert result_165["sinew"]["assessment_height"] == 165
    assert result_176["sinew"]["assessment"] == "normal"
    assert result_176["sinew"]["assessment_height"] == 176


def test_height_dependent_assessments_require_measurement_height() -> None:
    """Profile height is never substituted for missing measurement height."""
    measurement = _known_measurement()
    measurement["height"] = None
    result = assess_measurement(measurement, {"height": 176, "area_code": "NL"})

    for key in ("weight", "sinew", "muscle_ratio", "bmr"):
        assert key not in result
    assert result["bmi"]["assessment"] == "obesity"


def test_invalid_numeric_values_do_not_create_assessments() -> None:
    """Invalid, infinite, and boolean values are ignored."""
    measurement = _known_measurement()
    measurement.update(
        {
            "height": float("nan"),
            "weight": True,
            "bmi": "invalid",
            "visfat": float("inf"),
        }
    )
    result = assess_measurement(measurement, {"area_code": "NL"})

    assert "weight" not in result
    assert "bmi" not in result
    assert "visfat" not in result


def test_asia_does_not_receive_occident_assessments() -> None:
    """The implemented non-Asia tables are not applied to Asian regions."""
    assert assess_measurement(_known_measurement(), {"area_code": "JP"}) == {}


@pytest.mark.parametrize(
    "country", ["NL", "US", "DE", "nl", "us", "de", "NL-NL", "nl_NL", "Netherlands"]
)
def test_occident_region_variants(country: str) -> None:
    assert standard_region({"country": country}) == "occident"


@pytest.mark.parametrize(
    "country", ["CN", "JP", "HK", "TW", "MO", "KR", "cn", "jp", "hk", "tw", "kr"]
)
def test_asia_region_variants(country: str) -> None:
    assert standard_region({"country": country}) == "asia"
    assert assess_measurement(_known_measurement(), {"country": country}) == {}


def test_region_priority_and_safe_missing_fallback() -> None:
    assert standard_region({"area_code": "JP"}, {"area_code": "NL"}) == "asia"
    assert standard_region({}, {"country": "unknown"}, {}) is None
    assert assess_measurement(_known_measurement()) == {}


@pytest.mark.parametrize(
    "gender", [None, "", "unknown", 2, -1, True, False, "male", "female"]
)
def test_invalid_gender_omits_gender_dependent_assessments(gender: object) -> None:
    measurement = _known_measurement()
    measurement["gender"] = gender
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert "bmi" in result
    for key in ("bodyfat", "muscle", "protein", "water", "bone", "bmr"):
        assert key not in result


@pytest.mark.parametrize(
    "value",
    [None, "", "unknown", "unavailable", True, False, math.nan, math.inf, -math.inf],
)
def test_finite_float_rejects_non_numeric_values(value: object) -> None:
    assert finite_float(value) is None


def test_numeric_strings_are_supported() -> None:
    measurement = _known_measurement()
    measurement.update({"height": "165", "weight": "95.15", "bmi": "25"})
    result = assess_measurement(measurement, {"area_code": "nl"})
    assert result["bmi"]["assessment"] == "overweight"
    assert result["sinew"]["assessment_height"] == 165


@pytest.mark.parametrize(
    "height", [None, 0, -1, math.nan, math.inf, "unknown", "49", "301"]
)
def test_invalid_height_never_uses_profile_height(height: object) -> None:
    measurement = _known_measurement()
    measurement["height"] = height
    result = assess_measurement(measurement, {"height": 176, "area_code": "NL"})
    for key in ("weight", "sinew", "muscle_ratio", "bmr"):
        assert key not in result


@pytest.mark.parametrize(
    "value, expected",
    [
        (18.499, "underweight"),
        (18.5, "normal"),
        (24.999, "normal"),
        (25, "overweight"),
        (29.999, "overweight"),
        (30, "obesity"),
    ],
)
def test_bmi_boundaries(value: float, expected: str) -> None:
    measurement = _known_measurement()
    measurement["bmi"] = value
    assert (
        assess_measurement(measurement, {"area_code": "NL"})["bmi"]["assessment"]
        == expected
    )


@pytest.mark.parametrize(
    "gender, limits", [(1, (6, 13, 17, 25, 32)), (0, (14, 21, 25, 32, 38))]
)
def test_bodyfat_boundaries(gender: int, limits: tuple[int, ...]) -> None:
    categories = (
        "essential_fat",
        "athletes",
        "fitness",
        "acceptable",
        "overweight",
        "excessive",
    )
    for index, limit in enumerate(limits):
        measurement = _known_measurement()
        measurement.update({"gender": gender, "bodyfat": limit})
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result["bodyfat"]["assessment"] == categories[index + 1]


@pytest.mark.parametrize(
    "gender,key,bounds,labels",
    [
        (1, "muscle", (49, 59), ("low", "normal", "high")),
        (0, "muscle", (40, 50), ("low", "normal", "high")),
        (1, "protein", (16, 18), ("low", "normal", "excellent")),
        (0, "protein", (14, 16), ("low", "normal", "excellent")),
        (1, "subfat", (8.6, 16.7), ("low", "normal", "high")),
        (0, "subfat", (18.5, 26.7), ("low", "normal", "high")),
        (1, "water", (50, 65), ("low", "normal", "high")),
        (0, "water", (45, 60), ("low", "normal", "high")),
        (1, "bone", (3, 5), ("below_average", "average", "above_average")),
        (0, "bone", (2.5, 4), ("below_average", "average", "above_average")),
    ],
)
def test_three_zone_boundaries(
    gender: int, key: str, bounds: tuple[float, float], labels: tuple[str, str, str]
) -> None:
    for value, expected in (
        (bounds[0] - 0.001, labels[0]),
        (bounds[0], labels[1]),
        (bounds[1], labels[1]),
        (bounds[1] + 0.001, labels[2]),
    ):
        measurement = _known_measurement()
        measurement.update({"gender": gender, key: value})
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result[key]["assessment"] == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (6, "good"),
        (6.001, "acceptable"),
        (11, "acceptable"),
        (11.001, "high"),
        (14, "high"),
        (14.001, "excessive"),
    ],
)
def test_visceral_boundaries(value: float, expected: str) -> None:
    measurement = _known_measurement()
    measurement["visfat"] = value
    assert (
        assess_measurement(measurement, {"area_code": "NL"})["visfat"]["assessment"]
        == expected
    )


@pytest.mark.parametrize(
    "gender, limits", [(1, (59, 64, 69, 74)), (0, (52, 57, 62, 67))]
)
def test_storage_level_boundaries(gender: int, limits: tuple[int, ...]) -> None:
    for expected_level, ratio in enumerate(limits, 2):
        measurement = _known_measurement()
        measurement.update({"gender": gender, "weight": 100, "sinew": ratio})
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result["muscle_storage_capacity"]["storage_level"] == expected_level


@pytest.mark.parametrize("age", [15, 16, 17, 18, 19, 20, 30, 31, 40, 41, 50, 51])
def test_bmr_age_factor_boundaries(age: int) -> None:
    expected = next(
        (
            male
            for maximum, male in (
                (15, 46.7),
                (17, 46.2),
                (19, 39.7),
                (30, 37.7),
                (40, 37.9),
                (50, 36.8),
            )
            if age <= maximum
        ),
        35.6,
    )
    assert _bmr_factor(age, 1) == expected


def test_derived_mass_classification_uses_unrounded_values() -> None:
    measurement = _known_measurement()
    measurement.update({"weight": 83.33, "protein": 16, "protein_mass": 13.3327})
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert result["protein_mass"]["assessment"] == "normal"
    assert result["protein_mass"]["normal_min"] == 13.33


def test_profile_measurements_are_isolated() -> None:
    first = _known_measurement(165)
    second = _known_measurement(176)
    second.update({"gender": 0, "bodyfat": 20})
    first_result = assess_measurement(first, {"area_code": "NL"})
    second_result = assess_measurement(second, {"area_code": "NL"})
    assert first_result["sinew"]["assessment"] == "excellent"
    assert second_result["sinew"]["assessment"] == "excellent"
    assert first_result["bodyfat"]["assessment"] == "excessive"
    assert second_result["bodyfat"]["assessment"] == "athletes"


def test_measurement_age_uses_historical_date_and_leap_birthday() -> None:
    measurement = {
        "birthday": "2000-02-29",
        "time_stamp": 1_709_078_400,  # 2024-02-28 UTC
    }
    assert _measurement_age(measurement) == 23
    measurement["time_stamp"] = 1_709_164_800  # 2024-02-29 UTC
    assert _measurement_age(measurement) == 24


@pytest.mark.parametrize(
    "birthday", [None, "", "invalid", "2999-01-01", math.nan, math.inf, True]
)
def test_invalid_measurement_birthday_omits_bmr_assessment(birthday: object) -> None:
    measurement = _known_measurement()
    measurement["birthday"] = birthday
    result = assess_measurement(
        measurement, {"area_code": "NL", "birthday": "1990-01-01"}
    )
    assert "bmr" not in result
