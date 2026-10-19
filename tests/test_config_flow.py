"""Tests for FITAGE config flow reauthentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.common import MockConfigEntry

from custom_components.fitage.api import FeelfitAuthError, FeelfitConnectionError
from custom_components.fitage.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ENTRY_DATA = {
    "email": "user@example.test",
    "token": "expired-token",
    "token_expires": "1",
    "user_info": {"user_id": "primary-user", "account_name": "Primary"},
    "selected_profiles": ["primary-user", "family-user"],
    "profiles_list": [
        {"user_id": "primary-user", "account_name": "Primary"},
        {"user_id": "family-user", "account_name": "Family"},
    ],
}
ENTRY_OPTIONS = {
    "selected_profiles": ["primary-user", "family-user"],
    "import_history_statistics": True,
}


async def test_reauth_success_preserves_existing_entry_data(
    hass: HomeAssistant,
) -> None:
    """Reauthentication updates credentials without replacing profile data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="primary-user",
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
    )
    entry.add_to_hass(hass)
    update_listener = AsyncMock()
    entry.add_update_listener(update_listener)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.fitage.config_flow.validate_input",
        return_value={"token_info": {"token": "new-token", "remaining_time": 3600}},
    ) as validate_input:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"password": "new-password"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    validate_input.assert_awaited_once_with(
        hass,
        {"email": "user@example.test", "password": "new-password"},
    )
    assert entry.data == {
        **ENTRY_DATA,
        "token": "new-token",
        "token_expires": "3600",
    }
    assert entry.options == ENTRY_OPTIONS
    await hass.async_block_till_done()
    update_listener.assert_awaited_once_with(hass, entry)


async def test_reauth_success_reloads_entry_without_update_listener(
    hass: HomeAssistant,
) -> None:
    """An entry that failed initial setup is reloaded after reauth."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="primary-user", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    schedule_reload = MagicMock()
    hass.config_entries.async_schedule_reload = schedule_reload
    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.fitage.config_flow.validate_input",
        return_value={"token_info": {"token": "new-token", "remaining_time": 3600}},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"password": "new-password"}
        )

    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == "new-token"
    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_reauth_invalid_credentials_keep_existing_token(
    hass: HomeAssistant,
) -> None:
    """Invalid credentials leave the existing config untouched."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="primary-user", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.fitage.config_flow.validate_input",
        side_effect=FeelfitAuthError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"password": "wrong-password"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == ENTRY_DATA


async def test_reauth_connection_failure_is_retryable(
    hass: HomeAssistant,
) -> None:
    """Temporary connection failures are not reported as invalid credentials."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="primary-user", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.fitage.config_flow.validate_input",
        side_effect=FeelfitConnectionError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"password": "password"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == ENTRY_DATA
