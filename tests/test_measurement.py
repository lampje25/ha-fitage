"""Tests for effective FITAGE measurement values."""

from typing import Any

import pytest

from custom_components.fitage.measurement import effective_mass_value


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("body_fat_mass", 27.6524),
        ("body_water_mass", 48.3917),
        ("protein_mass", 15.3414),
    ],
)
def test_zero_sentinels_are_derived(metric: str, expected: float) -> None:
    record = {
        "weight": 94.7,
        "bodyfat": 29.2,
        "water": 51.1,
        "protein": 16.2,
        metric: 0,
    }

    assert effective_mass_value(record, metric) == pytest.approx(expected)


def test_positive_cloud_mass_remains_authoritative() -> None:
    record = {"weight": 100, "bodyfat": 25, "body_fat_mass": 24.5}

    assert effective_mass_value(record, "body_fat_mass") == 24.5


@pytest.mark.parametrize(
    "cloud_mass", [None, "invalid", float("nan"), float("inf"), True]
)
def test_missing_or_invalid_cloud_mass_is_derived(cloud_mass: Any) -> None:
    record = {"weight": 80, "bodyfat": 25}
    if cloud_mass is not None:
        record["body_fat_mass"] = cloud_mass

    assert effective_mass_value(record, "body_fat_mass") == 20


@pytest.mark.parametrize(
    "changes",
    [
        {"weight": None},
        {"weight": 0},
        {"weight": -1},
        {"weight": True},
        {"bodyfat": None},
        {"bodyfat": 0},
        {"bodyfat": -1},
        {"bodyfat": "invalid"},
        {"bodyfat": False},
    ],
)
def test_invalid_sources_do_not_create_a_mass(changes: dict[str, Any]) -> None:
    record = {"weight": 80, "bodyfat": 25, "body_fat_mass": 0, **changes}

    assert effective_mass_value(record, "body_fat_mass") is None


def test_missing_cloud_field_is_derived() -> None:
    assert effective_mass_value({"weight": 80, "bodyfat": 25}, "body_fat_mass") == 20


def test_explicit_none_cloud_mass_is_derived() -> None:
    record = {"weight": 80, "bodyfat": 25, "body_fat_mass": None}

    assert effective_mass_value(record, "body_fat_mass") == 20


@pytest.mark.parametrize(
    "record",
    [
        {"bodyfat": 25, "body_fat_mass": 0},
        {"weight": 80, "body_fat_mass": 0},
    ],
)
def test_missing_source_does_not_create_a_mass(record: dict[str, Any]) -> None:
    assert effective_mass_value(record, "body_fat_mass") is None
