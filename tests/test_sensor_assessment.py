"""Tests for stable multi-profile FITAGE sensor entities."""

from types import SimpleNamespace

import pytest
from homeassistant.components.sensor import SensorEntityDescription

from custom_components.fitage.assessment import assess_measurement
from custom_components.fitage.sensor import (
    FeelfitBirthdaySensor,
    FeelfitGoalSensor,
    FeelfitMeasurementSensor,
    FeelfitUserSensor,
    _create_profile_entities,
)


def _description(key: str, kind: str) -> SensorEntityDescription:
    translation_key = key if kind == "profile" else f"{kind}_{key}"
    return SensorEntityDescription(key=key, translation_key=translation_key)


def _coordinator(profiles: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(data={"profiles": profiles}, last_update_success=True)


def _profile(
    user_id: str,
    name: str,
    *,
    user_values: dict[str, object] | None = None,
    goals: list[dict[str, object]] | None = None,
    measurement: dict[str, object] | None = None,
) -> dict[str, object]:
    user_info: dict[str, object] = {"user_id": user_id, "account_name": name}
    user_info.update(user_values or {})
    return {
        "user_info": user_info,
        "user_settings": {"date_format": "yyyy-MM-dd"},
        "goals": {"goals": goals or []},
        "measurements": {"last_measurement": measurement},
        "assessments": (
            assess_measurement(measurement, user_info) if measurement else {}
        ),
    }


def test_canonical_unique_ids_are_namespaced_and_profile_name_independent() -> None:
    """Canonical identity uses only user ID, entity kind, and metric."""
    coordinator = _coordinator([_profile("profile-1", "Same name")])
    profile_weight = FeelfitUserSensor(
        coordinator, _description("weight", "profile"), "profile-1"
    )
    measurement_weight = FeelfitMeasurementSensor(
        coordinator, _description("weight", "measurement"), "profile-1"
    )
    other_profile_weight = FeelfitUserSensor(
        coordinator, _description("weight", "profile"), "profile-2"
    )

    assert profile_weight.unique_id == "profile-1_profile_weight"
    assert measurement_weight.unique_id == "profile-1_measurement_weight"
    assert other_profile_weight.unique_id == "profile-2_profile_weight"
    assert profile_weight.unique_id != measurement_weight.unique_id
    assert "Same name" not in profile_weight.unique_id
    assert "entry" not in profile_weight.unique_id


def test_similarly_named_profiles_remain_isolated() -> None:
    """Display names never participate in identity or value lookup."""
    coordinator = _coordinator(
        [
            _profile("profile-a", "Alex", user_values={"weight": 70}),
            _profile("profile-b", "Alex", user_values={"weight": 80}),
        ]
    )
    first = FeelfitUserSensor(
        coordinator, _description("weight", "profile"), "profile-a"
    )
    second = FeelfitUserSensor(
        coordinator, _description("weight", "profile"), "profile-b"
    )

    assert first.native_value == 70
    assert second.native_value == 80
    assert first.unique_id != second.unique_id


def test_profile_rename_does_not_change_unique_id() -> None:
    """A display-name change has no effect on technical identity."""
    before = FeelfitUserSensor(
        _coordinator([_profile("stable-id", "Before")]),
        _description("height", "profile"),
        "stable-id",
    )
    after = FeelfitUserSensor(
        _coordinator([_profile("stable-id", "After")]),
        _description("height", "profile"),
        "stable-id",
    )

    assert before.unique_id == after.unique_id == "stable-id_profile_height"


def test_profile_entities_never_fall_back_to_another_profile() -> None:
    """Every profile-bound entity reads only its exact user ID."""
    measurement = {"weight": 70, "height": 175, "bmi": 22, "gender": 1}
    coordinator = _coordinator(
        [
            _profile(
                "profile-a",
                "A",
                user_values={"weight": 70, "birthday": "1990-01-01"},
                goals=[{"goal_type": "weight", "goal_value": 65}],
                measurement=measurement,
            )
        ]
    )

    sensors = (
        FeelfitUserSensor(coordinator, _description("weight", "profile"), "profile-b"),
        FeelfitBirthdaySensor(
            coordinator, _description("birthday", "profile"), "profile-b"
        ),
        FeelfitGoalSensor(coordinator, _description("weight", "goal"), "profile-b"),
        FeelfitMeasurementSensor(
            coordinator, _description("bmi", "measurement"), "profile-b"
        ),
    )

    assert [sensor.native_value for sensor in sensors] == [None, None, None, None]


@pytest.mark.parametrize(
    ("goals", "expected"),
    [
        ([{"goal_type": "weight", "goal_value": 85}], 85),
        ([{"goal_type": "weight", "goal_value": 0}], 0),
        ([{"goal_type": "weight", "goal_value": None}], None),
        ([], None),
    ],
)
def test_goal_weight_always_exists_and_preserves_value_semantics(
    goals: list[dict[str, object]], expected: object
) -> None:
    """Goal 0, None, and a missing object remain distinct."""
    profile = _profile("profile-a", "A", goals=goals)
    coordinator = _coordinator([profile])
    entities = _create_profile_entities(coordinator, profile)
    goal_weight = next(
        entity for entity in entities if entity.unique_id == "profile-a_goal_weight"
    )

    assert goal_weight.native_value == expected


def test_supported_entities_exist_when_optional_profile_data_is_missing() -> None:
    """Stable entities do not depend on truthy setup-time values."""
    profile = _profile(
        "profile-a",
        "A",
        user_values={"weight": None, "height": None},
    )
    coordinator = _coordinator([profile])
    entities = _create_profile_entities(coordinator, profile)
    by_unique_id = {entity.unique_id: entity for entity in entities}

    for unique_id in (
        "profile-a_profile_weight",
        "profile-a_profile_height",
        "profile-a_profile_birthday",
        "profile-a_profile_email",
        "profile-a_goal_weight",
        "profile-a_goal_bodyfat",
        "profile-a_measurement_weight",
        "profile-a_measurement_bmi",
    ):
        assert unique_id in by_unique_id
        assert by_unique_id[unique_id].native_value is None


def test_measurement_entity_receives_later_measurement_without_recreation() -> None:
    """A stable entity updates when the profile later gets a measurement."""
    profile = _profile("profile-a", "A")
    coordinator = _coordinator([profile])
    entities = _create_profile_entities(coordinator, profile)
    sensor = next(
        entity for entity in entities if entity.unique_id == "profile-a_measurement_bmi"
    )

    assert sensor.native_value is None
    profile["measurements"] = {"last_measurement": {"bmi": 22.5}}
    assert sensor.native_value == 22.5
    assert sensor.unique_id == "profile-a_measurement_bmi"


@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("body_fat_mass", 27.65),
        ("body_water_mass", 48.39),
        ("protein_mass", 15.34),
    ],
)
def test_explicit_zero_measurement_mass_uses_percentage_fallback(
    metric: str, expected: float
) -> None:
    """A FITAGE zero sentinel is replaced by the derived body mass."""
    measurement = {
        "weight": 94.7,
        "bodyfat": 29.2,
        "water": 51.1,
        "protein": 16.2,
        metric: 0,
    }
    sensor = FeelfitMeasurementSensor(
        _coordinator([_profile("profile-a", "A", measurement=measurement)]),
        _description(metric, "measurement"),
        "profile-a",
    )

    assert sensor.native_value == pytest.approx(expected)


def test_zero_for_an_unrelated_measurement_is_preserved() -> None:
    """The FITAGE sentinel rule is limited to the three body masses."""
    sensor = FeelfitMeasurementSensor(
        _coordinator([_profile("profile-a", "A", measurement={"weight": 0})]),
        _description("weight", "measurement"),
        "profile-a",
    )

    assert sensor.native_value == 0


def test_profile_entity_metadata_and_device_are_consistent() -> None:
    """Profile, goal, and measurement entities expose stable metadata."""
    profile = _profile("synthetic-profile", "Synthetic Profile")
    coordinator = _coordinator([profile])
    entities = _create_profile_entities(coordinator, profile)

    expected = {
        "synthetic-profile_profile_weight": ("profile", "weight"),
        "synthetic-profile_goal_weight": ("goal", "weight"),
        "synthetic-profile_measurement_weight": ("measurement", "weight"),
    }
    for unique_id, (kind, metric) in expected.items():
        entity = next(item for item in entities if item.unique_id == unique_id)
        assert entity.extra_state_attributes["fitage_user_id"] == ("synthetic-profile")
        assert entity.extra_state_attributes["fitage_entity_kind"] == kind
        assert entity.extra_state_attributes["fitage_metric"] == metric
        assert entity.device_info["identifiers"] == {
            ("fitage", "user_synthetic-profile")
        }


def test_sensor_uses_precomputed_assessment_for_its_profile() -> None:
    """Assessment matching uses profile ID and measurement key."""
    measurement = {"weight": 70, "height": 175, "bmi": 25, "gender": 1}
    profile = _profile(
        "profile-a", "A", user_values={"area_code": "NL"}, measurement=measurement
    )
    coordinator = _coordinator([profile])
    sensor = FeelfitMeasurementSensor(
        coordinator, _description("bmi", "measurement"), "profile-a"
    )

    assert sensor.native_value == 25
    assert sensor.extra_state_attributes["assessment"] == "overweight"
    assert sensor.extra_state_attributes["fitage_user_id"] == "profile-a"
