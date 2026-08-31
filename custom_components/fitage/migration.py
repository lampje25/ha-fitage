"""Entity registry migration helpers for FITAGE."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_PROFILES_LIST,
    DOMAIN,
    GOAL_METRICS,
    MEASUREMENT_METRICS,
    PROFILE_METRICS,
)

_LOGGER = logging.getLogger(__name__)
_ENTITY_DOMAIN = "sensor"


@dataclass(frozen=True)
class LegacyProfile:
    """Profile identity needed to reconstruct exact v1.2 unique IDs."""

    user_id: str
    prefix: str


@dataclass(frozen=True)
class MigrationResult:
    """Result of an entity registry migration attempt."""

    migrated: int = 0
    collisions: int = 0


class EntityRegistryLike(Protocol):
    """Subset of the entity registry used by the migration."""

    def async_get_entity_id(
        self, domain: str, platform: str, unique_id: str
    ) -> str | None:
        """Return an entity ID for a registry identity."""

    def async_update_entity(self, entity_id: str, *, new_unique_id: str) -> Any:
        """Update an entity registry entry."""


def canonical_unique_id(user_id: str, entity_kind: str, metric: str) -> str:
    """Build a canonical v1.3 profile entity unique ID."""
    return f"{user_id}_{entity_kind}_{metric}"


def legacy_profiles_from_entry_data(data: dict[str, Any]) -> tuple[LegacyProfile, ...]:
    """Extract only profiles whose exact v1.2 prefix can be reconstructed."""
    profiles: list[LegacyProfile] = []
    seen: set[tuple[str, str]] = set()

    for profile in data.get(CONF_PROFILES_LIST) or []:
        raw_user_id = profile.get("user_id")
        if raw_user_id is None:
            continue
        user_id = str(raw_user_id)
        if not user_id:
            continue
        if profile.get("is_primary", False):
            prefix = ""
        else:
            account_name = profile.get("account_name")
            if not isinstance(account_name, str) or not account_name:
                continue
            prefix = f"{account_name.lower().replace(' ', '_')}_"
        candidate = (user_id, prefix)
        if candidate not in seen:
            profiles.append(LegacyProfile(*candidate))
            seen.add(candidate)

    saved_user_info = data.get("user_info") or {}
    raw_primary_user_id = saved_user_info.get("user_id")
    if raw_primary_user_id is not None:
        candidate = (str(raw_primary_user_id), "")
        if candidate[0] and candidate not in seen:
            profiles.append(LegacyProfile(*candidate))

    return tuple(profiles)


def legacy_unique_id_mapping(
    entry_id: str, profiles: tuple[LegacyProfile, ...]
) -> dict[str, str]:
    """Return the complete exact v1.2-to-v1.3 unique ID mapping."""
    mapping: dict[str, str] = {}
    kinds_and_metrics = (
        ("profile", PROFILE_METRICS),
        ("goal", GOAL_METRICS),
        ("measurement", MEASUREMENT_METRICS),
    )
    for profile in profiles:
        for entity_kind, metrics in kinds_and_metrics:
            for metric in metrics:
                legacy_key = (
                    metric if entity_kind == "profile" else f"{entity_kind}_{metric}"
                )
                legacy_unique_id = (
                    f"{entry_id}_{profile.prefix}{legacy_key}_{profile.user_id}"
                )
                mapping[legacy_unique_id] = canonical_unique_id(
                    profile.user_id, entity_kind, metric
                )
    return mapping


def parse_legacy_unique_id(
    unique_id: str, entry_id: str, profiles: tuple[LegacyProfile, ...]
) -> str | None:
    """Map one exact known v1.2 unique ID, or return None."""
    return legacy_unique_id_mapping(entry_id, profiles).get(unique_id)


def migrate_entity_registry(
    registry: EntityRegistryLike,
    entry: ConfigEntry,
    registry_entries: list[er.RegistryEntry],
) -> MigrationResult:
    """Migrate provable v1.2 FITAGE sensor entries in place."""
    profiles = legacy_profiles_from_entry_data(dict(entry.data))
    legacy_mapping = legacy_unique_id_mapping(entry.entry_id, profiles)
    migrated = 0
    collisions = 0

    for registry_entry in registry_entries:
        if (
            registry_entry.domain != _ENTITY_DOMAIN
            or registry_entry.platform != DOMAIN
            or registry_entry.config_entry_id != entry.entry_id
        ):
            continue
        new_unique_id = legacy_mapping.get(registry_entry.unique_id)
        if new_unique_id is None or new_unique_id == registry_entry.unique_id:
            continue

        existing_entity_id = registry.async_get_entity_id(
            _ENTITY_DOMAIN, DOMAIN, new_unique_id
        )
        if existing_entity_id is not None:
            if existing_entity_id != registry_entry.entity_id:
                collisions += 1
                _LOGGER.warning(
                    "Cannot migrate a FITAGE entity because its canonical identity "
                    "is already in use"
                )
            continue

        try:
            registry.async_update_entity(
                registry_entry.entity_id, new_unique_id=new_unique_id
            )
        except ValueError:
            collisions += 1
            _LOGGER.warning(
                "Cannot migrate a FITAGE entity because its canonical identity "
                "became unavailable"
            )
            continue
        migrated += 1

    return MigrationResult(migrated=migrated, collisions=collisions)
