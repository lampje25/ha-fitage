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
    for key in ("bodyfat", "muscle", "protein", "water", "bone", "bone_ratio", "bmr"):
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
    "gender, weight, bounds",
    [
        (1, 80, (2.4, 4.0)),  # official example: 80 kg male -> 2.4-4.0 kg
        (0, 80, (2.0, 3.2)),  # 80 kg female
        (1, 60, (1.8, 3.0)),  # clearly different from 100 kg
        (0, 44, (1.1, 1.76)),  # clearly different from 100 kg
    ],
)
def test_bone_boundaries_scale_with_current_weight(
    gender: int, weight: float, bounds: tuple[float, float]
) -> None:
    """bone (kg) is bounded by weight * 3%/5% (male) or weight * 2.5%/4%
    (female), not a fixed kilogram range - proven bounds computed with the
    exact same expression as assessment.py, so the "exact on the boundary"
    cases are bit-for-bit comparable, not merely numerically close."""
    lower, upper = bounds
    for value, expected in (
        (lower - 0.001, "below_average"),
        (lower, "average"),
        (upper, "average"),
        (upper + 0.001, "above_average"),
    ):
        measurement = _known_measurement()
        measurement.update({"gender": gender, "weight": weight, "bone": value})
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result["bone"]["assessment"] == expected
        assert result["bone"]["normal_min"] == lower
        assert result["bone"]["normal_max"] == upper


@pytest.mark.parametrize("gender, bounds", [(1, (3.0, 5.0)), (0, (2.5, 4.0))])
def test_bone_ratio_boundaries_use_fixed_official_percentages(
    gender: int, bounds: tuple[float, float]
) -> None:
    """bone_ratio is judged directly against the fixed official percentage
    bounds (3%-5% male, 2.5%-4% female), never derived by dividing a
    kilogram bound by weight. Uses weight=100 kg, where bone (kg) and
    bone/weight*100 (%) coincide exactly in floating point, so the "exact on
    the boundary" cases are not sensitive to round-trip precision noise."""
    lower, upper = bounds
    weight = 100
    for ratio, expected in (
        (lower - 0.001, "below_average"),
        (lower, "average"),
        (upper, "average"),
        (upper + 0.001, "above_average"),
    ):
        measurement = _known_measurement()
        measurement.update({"gender": gender, "weight": weight, "bone": ratio})
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result["bone_ratio"]["assessment"] == expected
        assert result["bone_ratio"]["normal_min"] == lower
        assert result["bone_ratio"]["normal_max"] == upper


@pytest.mark.parametrize("weight", [50, 80, 120])
@pytest.mark.parametrize("gender, bounds", [(1, (3.0, 5.0)), (0, (2.5, 4.0))])
def test_bone_ratio_bounds_are_the_same_regardless_of_weight(
    weight: float, gender: int, bounds: tuple[float, float]
) -> None:
    """The official bone_ratio percentage bounds never change with weight -
    only the equivalent kilogram bounds (bone) do."""
    lower, upper = bounds
    measurement = _known_measurement()
    # A bone value comfortably inside the normal band for every weight
    # tested, far enough from both bounds to be immune to floating-point
    # rounding noise from the bone/weight*100 conversion.
    measurement.update(
        {
            "gender": gender,
            "weight": weight,
            "bone": weight * (lower + upper) / 2 / 100,
        }
    )
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert result["bone_ratio"]["assessment"] == "average"
    assert result["bone_ratio"]["normal_min"] == pytest.approx(lower)
    assert result["bone_ratio"]["normal_max"] == pytest.approx(upper)


@pytest.mark.parametrize("weight", [None, 0, -1, "invalid", math.nan, math.inf, True])
def test_bone_and_bone_ratio_require_a_valid_weight(weight: object) -> None:
    """Without a known current weight, neither the kilogram bounds nor the
    ratio itself can be computed - no assessment must be added, never one
    based on a stale or substituted weight."""
    measurement = _known_measurement()
    measurement["weight"] = weight
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert "bone" not in result
    assert "bone_ratio" not in result


@pytest.mark.parametrize("bone", [None, "invalid", math.nan, math.inf, -1, True, 999])
def test_bone_and_bone_ratio_require_a_valid_bone_measurement(bone: object) -> None:
    """999 exceeds _known_measurement()'s weight (95.15 kg) and is rejected
    by the same physical-plausibility bound (bone mass cannot exceed body
    weight) that already applied before this fix."""
    measurement = _known_measurement()
    measurement["bone"] = bone
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert "bone" not in result
    assert "bone_ratio" not in result


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


def _bmr_reference(height: float, weight: float, age: int, gender: int) -> float:
    """Independently reproduce the official BMR reference formula (unchanged
    by this fix) for use as test oracle, without relying on assess_measurement
    itself for the value under test."""
    return (
        24 * (0.0061 * height + 0.0128 * weight - 0.1529) * _bmr_factor(age, gender)
        - 80
    )


@pytest.mark.parametrize(
    "gender, height, weight, birthday",
    [
        (1, 165, 95.15, "1990-01-01"),
        (0, 170, 65, "1985-06-15"),
        (1, 180, 90, "2000-01-01"),
        (0, 160, 55, "1970-03-20"),
    ],
)
def test_bmr_reference_formula_is_unchanged(
    gender: int, height: float, weight: float, birthday: str
) -> None:
    """The official BMR reference formula and age/gender factor table are
    untouched by this fix - only the "below_average"/"above_average"
    assessment keys change, to "not_standard"/"standard"."""
    measurement = _known_measurement()
    measurement.update(
        {"gender": gender, "height": height, "weight": weight, "birthday": birthday}
    )
    age = _measurement_age(measurement)
    expected_reference = _bmr_reference(height, weight, age, gender)
    measurement["bmr"] = expected_reference
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert result["bmr"]["reference_bmr"] == pytest.approx(expected_reference, abs=0.01)
    assert result["bmr"]["assessment"] == "standard"


@pytest.mark.parametrize("gender", [1, 0])
def test_bmr_boundaries_below_at_and_above_reference(gender: int) -> None:
    """Official FITAGE boundary logic (proven via the app's own
    levelJudgeSymbolArray: [">="]  for bmr): bmr < reference -> not_standard,
    bmr >= reference -> standard, so exactly at the reference is "standard"."""
    measurement = _known_measurement()
    measurement["gender"] = gender
    age = _measurement_age(measurement)
    reference = _bmr_reference(
        measurement["height"], measurement["weight"], age, gender
    )
    for bmr, expected in (
        (reference - 0.01, "not_standard"),
        (reference, "standard"),
        (reference + 0.01, "standard"),
    ):
        measurement["bmr"] = bmr
        result = assess_measurement(measurement, {"area_code": "NL"})
        assert result["bmr"]["assessment"] == expected


@pytest.mark.parametrize("bmr", [None, "invalid", math.nan, math.inf, -1, True])
def test_missing_or_invalid_bmr_value_omits_bmr_assessment(bmr: object) -> None:
    measurement = _known_measurement()
    measurement["bmr"] = bmr
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert "bmr" not in result


@pytest.mark.parametrize("weight", [None, 0, -1, "invalid", math.nan, math.inf, True])
def test_bmr_requires_a_valid_weight(weight: object) -> None:
    measurement = _known_measurement()
    measurement["weight"] = weight
    result = assess_measurement(measurement, {"area_code": "NL"})
    assert "bmr" not in result


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
