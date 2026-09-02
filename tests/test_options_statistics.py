"""Tests for the external-statistics privacy opt-in."""

from __future__ import annotations

import asyncio
from functools import wraps
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from custom_components.fitage.config_flow import FeelfitOptionsFlowHandler
from custom_components.fitage.const import (
    CONF_IMPORT_HISTORY_STATISTICS,
    CONF_SELECTED_PROFILES,
)


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def flow() -> tuple[FeelfitOptionsFlowHandler, MagicMock]:
    entry = MagicMock()
    entry.data = {
        "email": "private@example.test",
        "token": "private-token",
        "user_info": {"user_id": "private-user"},
        CONF_SELECTED_PROFILES: ["private-user"],
    }
    entry.options = {}
    result = FeelfitOptionsFlowHandler(entry)
    result.hass = MagicMock()
    return result, entry


@run_async
async def test_statistics_opt_in_defaults_false_and_is_saved() -> None:
    options_flow, entry = flow()
    profiles = [
        {"user_id": "private-user", "account_name": "Profile", "is_primary": True}
    ]
    with (
        patch.object(
            FeelfitOptionsFlowHandler,
            "config_entry",
            new_callable=PropertyMock,
            return_value=entry,
        ),
        patch(
            "custom_components.fitage.config_flow.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.fitage.config_flow.FeelfitApi.async_list_all_profiles",
            AsyncMock(return_value=profiles),
        ),
    ):
        form = await options_flow.async_step_profiles()
        schema = form["data_schema"]
        defaults = schema({})
        assert defaults[CONF_IMPORT_HISTORY_STATISTICS] is False
        result = await options_flow.async_step_profiles(
            {"Profile (Primario)": True, CONF_IMPORT_HISTORY_STATISTICS: True}
        )
    assert result["data"] == {
        CONF_SELECTED_PROFILES: ["private-user"],
        CONF_IMPORT_HISTORY_STATISTICS: True,
    }
