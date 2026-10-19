"""Tests for auth failures during FITAGE coordinator updates."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry

from custom_components.fitage.api import FeelfitAuthError
from custom_components.fitage.config_flow import FeelfitConfigFlow
from custom_components.fitage.const import DOMAIN
from custom_components.fitage.sensor import async_setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_active_coordinator_auth_failure_starts_reauth(
    hass: HomeAssistant,
) -> None:
    """A rejected token during polling opens reauth for the active entry."""
    assert hasattr(FeelfitConfigFlow, "async_step_reauth")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="primary-user",
        data={
            "email": "user@example.test",
            "token": "expired-token",
            "user_info": {"user_id": "primary-user"},
            "selected_profiles": ["primary-user"],
        },
    )
    entry.add_to_hass(hass)
    api = MagicMock()
    api.user_info = {"user_id": "primary-user"}
    api.async_fetch_all = AsyncMock(return_value={"profiles": [], "device_binds": {}})
    hass.data[DOMAIN] = {
        entry.entry_id: {
            "api": api,
            "selected_profiles": ["primary-user"],
            "user_info": api.user_info,
        }
    }

    await async_setup_entry(hass, entry, MagicMock())
    api.async_fetch_all.side_effect = FeelfitAuthError
    await hass.data[DOMAIN][entry.entry_id]["coordinator"].async_refresh()
    await hass.async_block_till_done()

    active_reauth_flows = list(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))
    assert len(active_reauth_flows) == 1
    assert active_reauth_flows[0]["step_id"] == "reauth_confirm"
