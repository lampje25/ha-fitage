"""Runtime upgrade tests for FITAGE v1.2 registry identities."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from tests.common import MockConfigEntry

from custom_components.fitage.const import (
    DOMAIN,
    GOAL_METRICS,
    MEASUREMENT_METRICS,
    PROFILE_METRICS,
)

PRIMARY_ID = "runtime-primary"
SUBPROFILE_ID = "runtime-melissa"
FITAGE_SOURCE = Path("/workspaces/ha-fitage/custom_components/fitage")


def _install_worktree_component(hass: HomeAssistant) -> Path:
    """Expose the current FITAGE worktree in this test's temporary config."""
    custom_components = Path(hass.config.path("custom_components"))
    custom_components.mkdir(parents=True, exist_ok=True)
    component_link = custom_components / DOMAIN
    if component_link.exists():
        assert component_link.resolve() == FITAGE_SOURCE
        return component_link
    component_link.symlink_to(FITAGE_SOURCE, target_is_directory=True)
    return component_link


@pytest.fixture
def fitage_worktree(hass: HomeAssistant) -> Generator[None]:
    """Install and remove the worktree link in the isolated test config."""
    component_link = _install_worktree_component(hass)
    yield
    if component_link.is_symlink() and component_link.resolve() == FITAGE_SOURCE:
        component_link.unlink()


def _entry(*, minor_version: int) -> MockConfigEntry:
    """Create a synthetic FITAGE config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Runtime FITAGE",
        version=1,
        minor_version=minor_version,
        unique_id=PRIMARY_ID,
        data={
            "email": "runtime@example.invalid",
            "token": "synthetic-runtime-token",
            "user_info": {
                "user_id": PRIMARY_ID,
                "account_name": "Primary Example",
            },
            "selected_profiles": [PRIMARY_ID, SUBPROFILE_ID],
            "profiles_list": [
                {
                    "user_id": PRIMARY_ID,
                    "account_name": "Primary Example",
                    "is_primary": True,
                },
                {
                    "user_id": SUBPROFILE_ID,
                    "account_name": "Melissa Example",
                    "is_primary": False,
                },
            ],
        },
    )


def _full_payload() -> dict[str, Any]:
    """Return deterministic data for two isolated synthetic profiles."""
    return {
        "profiles": [
            {
                "user_info": {
                    "user_id": PRIMARY_ID,
                    "account_name": "Primary Example",
                    "weight": 70.0,
                    "height": 180,
                    "birthday": "1990-01-01",
                    "email": "primary@example.invalid",
                },
                "user_settings": {"gender": 1},
                "goals": {
                    "goals": [
                        {"goal_type": "weight", "goal_value": 0},
                        {"goal_type": "bodyfat", "goal_value": 18},
                        {"goal_type": "water", "goal_value": 2000},
                    ]
                },
                "measurements": {
                    "last_measurement": {
                        "measurement_id": "primary-measurement",
                        "user_id": PRIMARY_ID,
                        "weight": 70.0,
                        "bodyfat": 20.0,
                        "bmi": 21.6,
                        "bmr": 1600,
                        "bodyage": 34,
                        "fat_free_weight": 56.0,
                        "muscle": 50.0,
                        "protein": 17.0,
                        "sinew": 52.0,
                        "subfat": 18.0,
                        "visfat": 7,
                        "water": 55.0,
                        "bone": 3.0,
                        "heart_rate": 61,
                        "score": 88,
                        "time_stamp": "2026-01-02T03:04:05+00:00",
                        "gender": 1,
                        "mea_category": 0,
                    }
                },
            },
            {
                "user_info": {
                    "user_id": SUBPROFILE_ID,
                    "account_name": "Melissa Example",
                    "weight": 60.0,
                    "height": 170,
                },
                "user_settings": {"gender": 0},
                "goals": {
                    "goals": [
                        {"goal_type": "bodyfat", "goal_value": 24},
                        {"goal_type": "water", "goal_value": 1800},
                    ]
                },
                "measurements": {
                    "last_measurement": {
                        "measurement_id": "subprofile-measurement",
                        "user_id": SUBPROFILE_ID,
                        "weight": 60.0,
                        "bmi": 20.8,
                        "bmr": 1400,
                        "bodyage": 31,
                        "fat_free_weight": 45.0,
                        "muscle": 42.0,
                        "protein": 16.0,
                        "sinew": 44.0,
                        "subfat": 20.0,
                        "visfat": 5,
                        "water": 0,
                        "body_water_mass": 0,
                        "bone": 2.5,
                        "heart_rate": 64,
                        "score": 91,
                        "time_stamp": "2026-01-02T03:04:05+00:00",
                        "gender": 0,
                        "mea_category": 0,
                    }
                },
            },
        ],
        "device_binds": {"device_binds": []},
    }


def _primary_only_payload() -> dict[str, Any]:
    """Return the next refresh with the subprofile temporarily absent."""
    payload = _full_payload()
    payload["profiles"] = payload["profiles"][:1]
    return payload


def _legacy_unique_id(entry_id: str, profile_id: str, kind: str, metric: str) -> str:
    """Construct the exact FITAGE v1.2 unique ID for this fixture."""
    prefix = "" if profile_id == PRIMARY_ID else "melissa_example_"
    key = metric if kind == "profile" else f"{kind}_{metric}"
    return f"{entry_id}_{prefix}{key}_{profile_id}"


def _canonical_unique_id(profile_id: str, kind: str, metric: str) -> str:
    """Construct the current canonical unique ID."""
    return f"{profile_id}_{kind}_{metric}"


def _create_registry_entry(
    registry: er.EntityRegistry,
    entry: MockConfigEntry,
    device_id: str,
    *,
    profile_id: str,
    kind: str,
    metric: str,
    entity_id: str,
    name: str | None = None,
    disabled_by: er.RegistryEntryDisabler | None = None,
    hidden_by: er.RegistryEntryHider | None = None,
) -> er.RegistryEntry:
    """Seed and customize one real entity-registry entry through HA APIs."""
    registry_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        _legacy_unique_id(entry.entry_id, profile_id, kind, metric),
        config_entry=entry,
        device_id=device_id,
        suggested_object_id=f"seed_{profile_id}_{kind}_{metric}",
    )
    return registry.async_update_entity(
        registry_entry.entity_id,
        new_entity_id=entity_id,
        name=name,
        disabled_by=disabled_by,
        hidden_by=hidden_by,
    )


def _registry_snapshot(
    registry: er.EntityRegistry, entry_id: str
) -> dict[str, tuple[str, str | None, Any, Any, str | None]]:
    """Snapshot preservation-sensitive fields for one config entry."""
    return {
        item.entity_id: (
            item.unique_id,
            item.device_id,
            item.disabled_by,
            item.hidden_by,
            item.name,
        )
        for item in er.async_entries_for_config_entry(registry, entry_id)
        if item.domain == "sensor" and item.platform == DOMAIN
    }


def _entry_by_unique_id(
    registry: er.EntityRegistry, unique_id: str
) -> er.RegistryEntry:
    """Return a FITAGE sensor registry entry by unique ID."""
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    registry_entry = registry.async_get(entity_id)
    assert registry_entry is not None
    return registry_entry


@pytest.mark.usefixtures("enable_custom_integrations", "fitage_worktree")
async def test_successful_v12_runtime_upgrade(hass: HomeAssistant) -> None:
    """Core migrates v1.2 identities before registering stable entities."""
    entry = _entry(minor_version=1)
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    primary_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"user_{PRIMARY_ID}")},
        name="Primary Example",
    )
    subprofile_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"user_{SUBPROFILE_ID}")},
        name="Melissa Example",
    )
    registry = er.async_get(hass)

    seeded = [
        _create_registry_entry(
            registry,
            entry,
            primary_device.id,
            profile_id=PRIMARY_ID,
            kind="profile",
            metric="weight",
            entity_id="sensor.weight",
        ),
        _create_registry_entry(
            registry,
            entry,
            primary_device.id,
            profile_id=PRIMARY_ID,
            kind="goal",
            metric="weight",
            entity_id="sensor.my_personal_target",
            name="My synthetic target",
        ),
        _create_registry_entry(
            registry,
            entry,
            primary_device.id,
            profile_id=PRIMARY_ID,
            kind="measurement",
            metric="weight",
            entity_id="sensor.measurement_weight",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="profile",
            metric="weight",
            entity_id="sensor.weight_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="goal",
            metric="weight",
            entity_id="sensor.goal_weight_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="measurement",
            metric="weight",
            entity_id="sensor.measurement_weight_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="measurement",
            metric="body_water_mass",
            entity_id="sensor.body_water_mass_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="measurement",
            metric="bone",
            entity_id="sensor.bone_mass_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="profile",
            metric="height",
            entity_id="sensor.height_2",
        ),
        _create_registry_entry(
            registry,
            entry,
            subprofile_device.id,
            profile_id=SUBPROFILE_ID,
            kind="measurement",
            metric="heart_rate",
            entity_id="sensor.heart_rate_2",
            disabled_by=er.RegistryEntryDisabler.USER,
            hidden_by=er.RegistryEntryHider.USER,
        ),
    ]

    before = _registry_snapshot(registry, entry.entry_id)
    assert entry.version == 1
    assert entry.minor_version == 1
    assert len(before) == len(seeded) == 10
    assert "sensor.weight" in before
    assert "sensor.measurement_weight" in before
    suffix_ids = {entity_id for entity_id in before if entity_id.endswith("_2")}
    assert {
        "sensor.weight_2",
        "sensor.body_water_mass_2",
        "sensor.bone_mass_2",
        "sensor.height_2",
        "sensor.heart_rate_2",
    } <= suffix_ids
    assert before["sensor.my_personal_target"][4] == "My synthetic target"
    assert before["sensor.heart_rate_2"][2:4] == (
        er.RegistryEntryDisabler.USER,
        er.RegistryEntryHider.USER,
    )
    for profile_id in (PRIMARY_ID, SUBPROFILE_ID):
        for kind, metrics in (
            ("profile", PROFILE_METRICS),
            ("goal", GOAL_METRICS),
            ("measurement", MEASUREMENT_METRICS),
        ):
            for metric in metrics:
                assert (
                    registry.async_get_entity_id(
                        "sensor",
                        DOMAIN,
                        _canonical_unique_id(profile_id, kind, metric),
                    )
                    is None
                )

    return_primary_only = False

    async def mocked_fetch_all(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = _primary_only_payload() if return_primary_only else _full_payload()
        return deepcopy(payload)

    with patch(
        "custom_components.fitage.api.FeelfitApi.async_fetch_all",
        new=AsyncMock(side_effect=mocked_fetch_all),
    ) as fetch_mock:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is config_entries.ConfigEntryState.LOADED
        assert entry.version == 1
        assert entry.minor_version == 2
        assert fetch_mock.await_count >= 2

        after = _registry_snapshot(registry, entry.entry_id)
        assert len(after) == 2 * (
            len(PROFILE_METRICS) + len(GOAL_METRICS) + len(MEASUREMENT_METRICS)
        )
        assert len({values[0] for values in after.values()}) == len(after)

        for entity_id, (_, device_id, disabled_by, hidden_by, name) in before.items():
            assert entity_id in after
            assert after[entity_id][1:] == (
                device_id,
                disabled_by,
                hidden_by,
                name,
            )

        expected_migrations = {
            "sensor.weight": f"{PRIMARY_ID}_profile_weight",
            "sensor.my_personal_target": f"{PRIMARY_ID}_goal_weight",
            "sensor.measurement_weight": f"{PRIMARY_ID}_measurement_weight",
            "sensor.weight_2": f"{SUBPROFILE_ID}_profile_weight",
            "sensor.goal_weight_2": f"{SUBPROFILE_ID}_goal_weight",
            "sensor.measurement_weight_2": f"{SUBPROFILE_ID}_measurement_weight",
            "sensor.body_water_mass_2": (
                f"{SUBPROFILE_ID}_measurement_body_water_mass"
            ),
            "sensor.bone_mass_2": f"{SUBPROFILE_ID}_measurement_bone",
            "sensor.height_2": f"{SUBPROFILE_ID}_profile_height",
            "sensor.heart_rate_2": f"{SUBPROFILE_ID}_measurement_heart_rate",
        }
        for entity_id, unique_id in expected_migrations.items():
            assert after[entity_id][0] == unique_id

        for profile_id, device_id in (
            (PRIMARY_ID, primary_device.id),
            (SUBPROFILE_ID, subprofile_device.id),
        ):
            for kind, metrics in (
                ("profile", PROFILE_METRICS),
                ("goal", GOAL_METRICS),
                ("measurement", MEASUREMENT_METRICS),
            ):
                for metric in metrics:
                    registry_entry = _entry_by_unique_id(
                        registry, _canonical_unique_id(profile_id, kind, metric)
                    )
                    assert registry_entry.device_id == device_id

        primary_goal = _entry_by_unique_id(
            registry, f"{PRIMARY_ID}_goal_weight"
        ).entity_id
        subprofile_goal = _entry_by_unique_id(
            registry, f"{SUBPROFILE_ID}_goal_weight"
        ).entity_id
        subprofile_email = _entry_by_unique_id(
            registry, f"{SUBPROFILE_ID}_profile_email"
        ).entity_id
        subprofile_bodyfat = _entry_by_unique_id(
            registry, f"{SUBPROFILE_ID}_measurement_bodyfat"
        ).entity_id
        subprofile_water_mass = _entry_by_unique_id(
            registry, f"{SUBPROFILE_ID}_measurement_body_water_mass"
        ).entity_id

        assert hass.states.get(primary_goal).state == "0"
        assert hass.states.get(subprofile_goal).state == "unknown"
        assert hass.states.get(subprofile_email).state == "unknown"
        assert hass.states.get(subprofile_bodyfat).state == "unknown"
        assert hass.states.get(subprofile_water_mass).state == "0"

        for profile_id, kind, metric in (
            (PRIMARY_ID, "profile", "weight"),
            (PRIMARY_ID, "goal", "weight"),
            (PRIMARY_ID, "measurement", "weight"),
            (SUBPROFILE_ID, "measurement", "bodyfat"),
        ):
            entity_id = _entry_by_unique_id(
                registry, _canonical_unique_id(profile_id, kind, metric)
            ).entity_id
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.attributes["fitage_user_id"] == profile_id
            assert state.attributes["fitage_entity_kind"] == kind
            assert state.attributes["fitage_metric"] == metric

        sensor_component = hass.data["sensor"]
        subprofile_measurement_entity = sensor_component.get_entity(
            "sensor.measurement_weight_2"
        )
        assert subprofile_measurement_entity is not None
        coordinator = subprofile_measurement_entity.coordinator
        return_primary_only = True
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert hass.states.get("sensor.weight").state == "70.0"
        assert hass.states.get("sensor.measurement_weight_2").state == "unavailable"
        assert hass.states.get("sensor.body_water_mass_2").state == "unavailable"


@pytest.mark.usefixtures("enable_custom_integrations", "fitage_worktree")
async def test_v12_runtime_collision_fails_closed(hass: HomeAssistant) -> None:
    """A canonical collision stops Core before sensor platform setup."""
    entry = _entry(minor_version=1)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"user_{PRIMARY_ID}")},
    )
    legacy = _create_registry_entry(
        registry,
        entry,
        device.id,
        profile_id=PRIMARY_ID,
        kind="profile",
        metric="weight",
        entity_id="sensor.legacy_weight",
    )
    canonical = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{PRIMARY_ID}_profile_weight",
        config_entry=entry,
        suggested_object_id="canonical_collision",
    )
    before = _registry_snapshot(registry, entry.entry_id)

    with patch(
        "custom_components.fitage.api.FeelfitApi.async_fetch_all",
        new=AsyncMock(return_value=deepcopy(_full_payload())),
    ) as fetch_mock:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    after = _registry_snapshot(registry, entry.entry_id)
    assert entry.version == 1
    assert entry.minor_version == 1
    assert entry.state is config_entries.ConfigEntryState.MIGRATION_ERROR
    assert after == before
    assert registry.async_get(legacy.entity_id) is not None
    assert registry.async_get(canonical.entity_id) is not None
    assert fetch_mock.await_count == 0
    assert len(after) == 2
    assert not hass.states.async_all("sensor")


@pytest.mark.usefixtures("enable_custom_integrations", "fitage_worktree")
async def test_clean_v13_runtime_setup(hass: HomeAssistant) -> None:
    """A current empty entry directly registers canonical entities once."""
    entry = _entry(minor_version=2)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    with patch(
        "custom_components.fitage.api.FeelfitApi.async_fetch_all",
        new=AsyncMock(return_value=deepcopy(_full_payload())),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entries = _registry_snapshot(registry, entry.entry_id)
    expected_count = 2 * (
        len(PROFILE_METRICS) + len(GOAL_METRICS) + len(MEASUREMENT_METRICS)
    )
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.version == 1
    assert entry.minor_version == 2
    assert len(entries) == expected_count
    assert len({values[0] for values in entries.values()}) == expected_count
    for profile_id in (PRIMARY_ID, SUBPROFILE_ID):
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{profile_id}_measurement_weight"
            )
            is not None
        )
