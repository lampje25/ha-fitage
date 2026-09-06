"""The FITAGE integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import FeelfitApi, FeelfitApiError
from .const import (
    CONF_IMPORT_HISTORY_STATISTICS,
    CONF_SELECTED_PROFILES,
    DOMAIN,
    PLATFORMS,
)
from .frontend import async_register_frontend
from .history import FitageHistoryManager
from .history_websocket import async_register_history_websocket
from .migration import migrate_entity_registry
from .statistics import (
    FitageStatisticsImporter,
    StatisticsCleanupError,
    async_clear_entry_statistics,
)

_LOGGER = logging.getLogger("custom_components.fitage")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the FITAGE integration.

    Called once per Home Assistant runtime regardless of how many FITAGE
    config entries exist, which is why the frontend card registration lives
    here instead of in ``async_setup_entry``.
    """
    await async_register_frontend(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a v1.2 config entry before canonical entities are registered."""
    if entry.version != 1:
        return False
    if entry.minor_version >= 2:
        return True

    registry = er.async_get(hass)
    result = migrate_entity_registry(
        registry,
        entry,
        er.async_entries_for_config_entry(registry, entry.entry_id),
    )
    if result.collisions:
        _LOGGER.error(
            "FITAGE entity migration stopped because %d canonical identity "
            "collision(s) require manual resolution",
            result.collisions,
        )
        return False

    hass.config_entries.async_update_entry(entry, version=1, minor_version=2)
    _LOGGER.debug(
        "Successfully migrated %d FITAGE entity registry entries",
        result.migrated,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FITAGE from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    email: str | None = entry.data.get("email")
    token: str | None = entry.data.get("token")
    saved_user_info: dict[str, Any] = entry.data.get("user_info") or {}

    selected_profiles: list[str] = (
        entry.options.get(CONF_SELECTED_PROFILES)
        or entry.data.get(CONF_SELECTED_PROFILES)
        or []
    )

    if not email:
        _LOGGER.error("No email found in config entry")
        return False

    session = async_get_clientsession(hass)
    api = FeelfitApi(hass, session, email)

    if token:
        api.token = token
    if saved_user_info:
        api.user_info = saved_user_info

    history = FitageHistoryManager(hass, entry.entry_id)
    await history.async_load()
    api.history = history
    statistics = FitageStatisticsImporter(
        hass,
        entry.entry_id,
        history,
        enabled=entry.options.get(CONF_IMPORT_HISTORY_STATISTICS, False),
    )
    api.statistics = statistics

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "history": history,
        "statistics": statistics,
        "user_info": api.user_info,
        "selected_profiles": selected_profiles,
    }
    async_register_history_websocket(hass)

    try:
        user_id = (
            api.user_info.get("user_id")
            if api.user_info
            else entry.unique_id or entry.entry_id
        )
        if api.token and user_id:
            payload = await api.async_fetch_all(
                str(user_id),
                selected_profiles=selected_profiles if selected_profiles else None,
            )
            hass.data[DOMAIN][entry.entry_id].update(
                {
                    "profiles": payload.get("profiles") or [],
                    "device_binds": payload.get("device_binds") or {},
                }
            )
    except FeelfitApiError:
        _LOGGER.debug("Initial fetch failed; the coordinator will retry")
    except Exception:
        _LOGGER.error("Unexpected error during initial FITAGE fetch")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - rimuove entità e device dei profili disattivati."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    new_selected = entry.options.get(CONF_SELECTED_PROFILES, [])
    old_selected = entry.data.get(CONF_SELECTED_PROFILES, [])

    removed_profiles = set(old_selected) - set(new_selected)

    if removed_profiles:
        _LOGGER.debug(
            "Removing entities for %d deselected profile(s)", len(removed_profiles)
        )

        entity_registry = er.async_get(hass)
        device_registry = dr.async_get(hass)

        devices_to_remove = []
        for device_entry in device_registry.devices.values():
            for identifier_tuple in device_entry.identifiers:
                if identifier_tuple[0] == DOMAIN:
                    device_id_str = identifier_tuple[1]

                    if device_id_str.startswith("user_"):
                        user_id = device_id_str.replace("user_", "")
                        if user_id in removed_profiles:
                            devices_to_remove.append(device_entry.id)
                            break

        for device_id in devices_to_remove:
            device_registry.async_remove_device(device_id)
            _LOGGER.debug("Removed a device for a deselected profile")

        if devices_to_remove:
            _LOGGER.info(
                "Removed %d devices for deselected profiles", len(devices_to_remove)
            )
        else:
            entries_to_remove = []
            for entity_entry in entity_registry.entities.values():
                if entity_entry.config_entry_id == entry.entry_id:
                    for removed_user_id in removed_profiles:
                        if str(removed_user_id) in entity_entry.unique_id:
                            entries_to_remove.append(entity_entry.entity_id)
                            break

            for entity_id in entries_to_remove:
                entity_registry.async_remove(entity_id)

            if entries_to_remove:
                _LOGGER.info(
                    "Removed %d entities for deselected profiles",
                    len(entries_to_remove),
                )

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove only this entry's derived statistics and private raw Store."""
    loaded_data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
    loaded_history = (
        loaded_data.get("history") if isinstance(loaded_data, dict) else None
    )
    history = (
        loaded_history
        if isinstance(loaded_history, FitageHistoryManager)
        else FitageHistoryManager(hass, entry.entry_id)
    )
    user_ids: set[str] = set()
    try:
        if not history.is_loaded:
            await history.async_load()
        user_ids.update(history.profile_ids())
    except Exception:  # noqa: BLE001 -- preserve Store and redact load failures.
        _LOGGER.error(
            "FITAGE cleanup could not verify stored statistics; preserving the "
            "private history Store for recovery"
        )
        return

    if not history.statistics_may_exist():
        await history.async_remove_store()
        return

    user_ids.update(
        str(profile["user_id"])
        for profile in entry.data.get("profiles_list") or []
        if isinstance(profile, dict) and profile.get("user_id") not in (None, "")
    )
    user_ids.update(str(item) for item in entry.data.get(CONF_SELECTED_PROFILES) or [])
    user_info = entry.data.get("user_info") or {}
    if user_info.get("user_id") not in (None, ""):
        user_ids.add(str(user_info["user_id"]))

    try:
        await async_clear_entry_statistics(hass, entry.entry_id, user_ids)
    except StatisticsCleanupError:
        _LOGGER.error(
            "FITAGE statistics cleanup did not complete; preserving the private "
            "history Store for recovery"
        )
        return
    await history.async_remove_store()
