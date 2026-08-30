"""FITAGE assessment and reference calculations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

ASIA_AREA_CODES = frozenset({"CN", "JP", "HK", "TW", "MO", "KR"})
COUNTRY_NAMES = {
    "CHINA": "CN",
    "HONG KONG": "HK",
    "JAPAN": "JP",
    "MACAO": "MO",
    "MACAU": "MO",
    "NETHERLANDS": "NL",
    "SOUTH KOREA": "KR",
    "TAIWAN": "TW",
}

ASSESSMENT_LABELS = {
    "above_average": "Above average",
    "acceptable": "Acceptable",
    "athletes": "Athletes",
    "average": "Average",
    "below_average": "Below average",
    "essential_fat": "Essential fat",
    "excellent": "Excellent",
    "excessive": "Excessive",
    "fitness": "Fitness",
    "good": "Good",
    "high": "High",
    "insufficient": "Insufficient",
    "low": "Low",
    "normal": "Normal",
    "obesity": "Obesity",
    "overweight": "Overweight",
    "underweight": "Underweight",
}


@dataclass(frozen=True, slots=True)
class Assessment:
    """Assessment attributes for one measurement entity."""

    assessment: str
    normal_min: float | int | None = None
    normal_max: float | int | None = None
    assessment_height: float | int | None = None
    reference_bmr: float | None = None
    storage_level: int | None = None

    def as_attributes(self, standard_region: str) -> dict[str, Any]:
        """Return Home Assistant state attributes."""
        attributes: dict[str, Any] = {
            "assessment": self.assessment,
            "assessment_label": ASSESSMENT_LABELS[self.assessment],
            "standard_region": standard_region,
        }
        for key in (
            "normal_min",
            "normal_max",
            "assessment_height",
            "reference_bmr",
            "storage_level",
        ):
            if (value := getattr(self, key)) is not None:
                attributes[key] = value
        return attributes


def finite_float(value: Any) -> float | None:
    """Return a finite float without accepting booleans."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def finite_int(value: Any) -> int | None:
    """Return a finite integer without accepting booleans."""
    number = finite_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def standard_region(*sources: dict[str, Any] | None) -> str | None:
    """Select the FITAGE region, or None when it cannot be established.

    Measurement data has priority over profile data, which has priority over
    settings. Locale-like values (for example ``nl_NL``) use their country part.
    """
    for source in sources:
        if not source:
            continue
        for key in ("register_area_code", "area_code", "country"):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = value.strip().upper().replace("_", "-")
            normalized = COUNTRY_NAMES.get(normalized, normalized)
            parts = normalized.split("-")
            country_code = parts[-1] if len(parts) > 1 else normalized
            if len(country_code) != 2 or not country_code.isalpha():
                continue
            return "asia" if country_code in ASIA_AREA_CODES else "occident"
    return None


def _display_number(value: float, digits: int = 2) -> float | int:
    """Round a reference for compact, stable state attributes."""
    rounded = round(value, digits)
    return int(rounded) if rounded.is_integer() else rounded


def _three_zone(
    value: float,
    normal_min: float,
    normal_max: float,
    low: str,
    normal: str,
    high: str,
) -> str:
    if value < normal_min:
        return low
    if value <= normal_max:
        return normal
    return high


def _bodyfat_assessment(value: float, gender: int) -> tuple[str, float, float]:
    if gender == 1:
        limits = (6.0, 13.0, 17.0, 25.0, 32.0)
    else:
        limits = (14.0, 21.0, 25.0, 32.0, 38.0)
    categories = (
        "essential_fat",
        "athletes",
        "fitness",
        "acceptable",
        "overweight",
        "excessive",
    )
    index = next((index for index, limit in enumerate(limits) if value < limit), 5)
    return categories[index], limits[2], limits[3]


def _muscle_mass_range(height: float, gender: int) -> tuple[float, float]:
    if gender == 1:
        if height < 160:
            return 38.5, 46.5
        if height <= 170:
            return 44.0, 52.4
        return 49.4, 59.4
    if height < 150:
        return 29.1, 34.7
    if height <= 160:
        return 32.9, 37.5
    return 36.5, 42.5


def _measurement_age(measurement: dict[str, Any]) -> int | None:
    birthday = measurement.get("birthday")
    if birthday in (None, ""):
        return None

    born: date | None = None
    if isinstance(birthday, str):
        try:
            born = date.fromisoformat(birthday[:10])
        except ValueError:
            if birthday.isdigit():
                birthday = int(birthday)
    if (
        born is None
        and not isinstance(birthday, bool)
        and isinstance(birthday, (int, float))
    ):
        timestamp = float(birthday)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            born = datetime.fromtimestamp(timestamp, UTC).date()
        except (OSError, OverflowError, ValueError):
            return None
    if born is None:
        return None

    measured_on = datetime.now(UTC).date()
    timestamp = finite_float(measurement.get("time_stamp"))
    if timestamp is not None and timestamp > 0:
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            measured_on = datetime.fromtimestamp(timestamp, UTC).date()
        except (OSError, OverflowError, ValueError):
            pass
    age = (
        measured_on.year
        - born.year
        - ((measured_on.month, measured_on.day) < (born.month, born.day))
    )
    return age if 0 <= age <= 130 else None


def _number_in_range(
    measurement: dict[str, Any], key: str, minimum: float, maximum: float
) -> float | None:
    """Return a finite measurement value inside an inclusive semantic range."""
    value = finite_float(measurement.get(key))
    return value if value is not None and minimum <= value <= maximum else None


def _bmr_factor(age: int, gender: int) -> float:
    table = (
        (15, 46.7, 41.2),
        (17, 46.2, 43.4),
        (19, 39.7, 36.8),
        (30, 37.7, 35.0),
        (40, 37.9, 35.0),
        (50, 36.8, 34.0),
    )
    for maximum_age, male, female in table:
        if age <= maximum_age:
            return male if gender == 1 else female
    return 35.6 if gender == 1 else 33.1


def _assessment(
    value: float,
    normal_min: float,
    normal_max: float,
    low: str = "low",
    normal: str = "normal",
    high: str = "high",
    *,
    height: float | None = None,
) -> Assessment:
    return Assessment(
        _three_zone(value, normal_min, normal_max, low, normal, high),
        _display_number(normal_min),
        _display_number(normal_max),
        _display_number(height) if height is not None else None,
    )


def assess_measurement(
    measurement: dict[str, Any],
    user_info: dict[str, Any] | None = None,
    user_settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Calculate FITAGE assessment attributes for one measurement."""
    region = standard_region(measurement, user_info, user_settings)
    # Asia uses different tables which have not all been verified. An unknown
    # region is equally unsafe: omit attributes instead of presenting an
    # Occident classification as fact.
    if region != "occident":
        return {}
    assessments: dict[str, Assessment] = {}
    weight = _number_in_range(measurement, "weight", 0.01, 1000)
    height = _number_in_range(measurement, "height", 50, 300)
    gender = finite_int(measurement.get("gender"))
    if gender not in (0, 1):
        gender = None

    def add_three_zone(
        key: str,
        source_key: str,
        bounds: tuple[float, float],
        labels: tuple[str, str, str] = ("low", "normal", "high"),
    ) -> None:
        value = _number_in_range(measurement, source_key, 0, 100)
        if value is not None:
            assessments[key] = _assessment(value, *bounds, *labels)

    if height is not None and height > 0 and weight is not None and weight > 0:
        height_m = height / 100
        weight_bounds = (18.5 * height_m**2, 25.0 * height_m**2, 30.0 * height_m**2)
        weight_categories = ("underweight", "normal", "overweight", "obesity")
        index = next(
            (index for index, limit in enumerate(weight_bounds) if weight < limit),
            3,
        )
        assessments["weight"] = Assessment(
            weight_categories[index],
            _display_number(weight_bounds[0]),
            _display_number(weight_bounds[1]),
            _display_number(height),
        )

    bmi = _number_in_range(measurement, "bmi", 0.01, 200)
    if bmi is not None:
        bmi_categories = ("underweight", "normal", "overweight", "obesity")
        index = next(
            (index for index, limit in enumerate((18.5, 25.0, 30.0)) if bmi < limit),
            3,
        )
        assessments["bmi"] = Assessment(bmi_categories[index], 18.5, 25)

    if gender is not None:
        bodyfat = _number_in_range(measurement, "bodyfat", 0, 100)
        if bodyfat is not None:
            category, acceptable_min, acceptable_max = _bodyfat_assessment(
                bodyfat, gender
            )
            assessments["bodyfat"] = Assessment(
                category, acceptable_min, acceptable_max
            )
            if weight is not None and weight > 0:
                assessments["body_fat_mass"] = Assessment(
                    category,
                    _display_number(weight * acceptable_min / 100),
                    _display_number(weight * acceptable_max / 100),
                )

        muscle_bounds = (49.0, 59.0) if gender == 1 else (40.0, 50.0)
        add_three_zone("muscle", "muscle", muscle_bounds)

        if height is not None and height > 0:
            sinew = _number_in_range(measurement, "sinew", 0, weight or 1000)
            muscle_mass_bounds = _muscle_mass_range(height, gender)
            if sinew is not None:
                assessments["sinew"] = _assessment(
                    sinew,
                    *muscle_mass_bounds,
                    "insufficient",
                    "normal",
                    "excellent",
                    height=height,
                )
                if weight is not None and weight > 0:
                    ratio = sinew / weight * 100
                    ratio_bounds = tuple(
                        boundary / weight * 100 for boundary in muscle_mass_bounds
                    )
                    assessments["muscle_ratio"] = _assessment(
                        ratio,
                        *ratio_bounds,
                        "insufficient",
                        "normal",
                        "excellent",
                        height=height,
                    )

        if weight is not None and weight > 0:
            sinew = _number_in_range(measurement, "sinew", 0, weight)
            if sinew is not None and sinew > 0:
                ratio = sinew / weight * 100
                limits = (59, 64, 69, 74) if gender == 1 else (52, 57, 62, 67)
                level = next(
                    (
                        index
                        for index, limit in enumerate(limits, 1)
                        if sinew * 100 < limit * weight
                    ),
                    5,
                )
                category = "low" if level < 2 else "normal" if level <= 4 else "high"
                assessments["muscle_storage_capacity"] = Assessment(
                    category, 2, 4, storage_level=level
                )

        protein_bounds = (16.0, 18.0) if gender == 1 else (14.0, 16.0)
        add_three_zone(
            "protein", "protein", protein_bounds, ("low", "normal", "excellent")
        )
        if weight is not None and weight > 0:
            protein = _number_in_range(measurement, "protein", 0, 100)
            if protein is not None:
                mass_bounds = tuple(weight * value / 100 for value in protein_bounds)
                assessments["protein_mass"] = _assessment(
                    weight * protein / 100,
                    *mass_bounds,
                    "low",
                    "normal",
                    "excellent",
                )

        subfat_bounds = (8.6, 16.7) if gender == 1 else (18.5, 26.7)
        add_three_zone("subfat", "subfat", subfat_bounds)

        water_bounds = (50.0, 65.0) if gender == 1 else (45.0, 60.0)
        add_three_zone("water", "water", water_bounds)
        if weight is not None and weight > 0:
            water = _number_in_range(measurement, "water", 0, 100)
            if water is not None:
                mass_bounds = tuple(weight * value / 100 for value in water_bounds)
                assessments["body_water_mass"] = _assessment(
                    weight * water / 100, *mass_bounds
                )

        bone_bounds = (3.0, 5.0) if gender == 1 else (2.5, 4.0)
        add_three_zone(
            "bone",
            "bone",
            bone_bounds,
            ("below_average", "average", "above_average"),
        )
        if weight is not None and weight > 0:
            bone = _number_in_range(measurement, "bone", 0, weight)
            if bone is not None:
                ratio_bounds = tuple(value / weight * 100 for value in bone_bounds)
                assessments["bone_ratio"] = _assessment(
                    bone / weight * 100,
                    *ratio_bounds,
                    "below_average",
                    "average",
                    "above_average",
                )

        bmr = _number_in_range(measurement, "bmr", 0.01, 10_000)
        age = _measurement_age(measurement)
        if (
            bmr is not None
            and height is not None
            and height > 0
            and weight is not None
            and weight > 0
            and age is not None
        ):
            reference = (
                24
                * (0.0061 * height + 0.0128 * weight - 0.1529)
                * _bmr_factor(age, gender)
                - 80
            )
            assessments["bmr"] = Assessment(
                "below_average" if bmr < reference else "above_average",
                assessment_height=_display_number(height),
                reference_bmr=float(_display_number(reference)),
            )

    visfat = _number_in_range(measurement, "visfat", 0, 100)
    if visfat is not None:
        if visfat <= 6:
            category = "good"
        elif visfat <= 11:
            category = "acceptable"
        elif visfat <= 14:
            category = "high"
        else:
            category = "excessive"
        assessments["visfat"] = Assessment(category, 6, 11)

    return {
        key: assessment.as_attributes(region) for key, assessment in assessments.items()
    }
