"""Regression tests ensuring the existing FITAGE setup entry points keep
working after adding the bundled frontend card registration in __init__.py."""

from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.fitage import async_setup, async_setup_entry
from custom_components.fitage.const import DOMAIN


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def fake_entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        data={"email": "private@example.test", "token": "token", "user_info": {}},
        options={},
        add_update_listener=MagicMock(return_value=MagicMock()),
        async_on_unload=MagicMock(),
    )


@run_async
async def test_async_setup_entry_still_sets_up_the_integration() -> None:
    hass = SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = fake_entry()

    api = MagicMock()
    api.token = "token"
    api.user_info = {"user_id": "user-1"}
    api.async_fetch_all = AsyncMock(return_value={"profiles": [], "device_binds": {}})

    with (
        patch("custom_components.fitage.async_get_clientsession"),
        patch("custom_components.fitage.FeelfitApi", return_value=api),
        patch("custom_components.fitage.FitageHistoryManager") as history_cls,
        patch("custom_components.fitage.FitageStatisticsImporter"),
        patch("custom_components.fitage.async_register_history_websocket"),
    ):
        history_cls.return_value.async_load = AsyncMock()
        result = await async_setup_entry(hass, entry)

    assert result is True
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()
    assert hass.data[DOMAIN][entry.entry_id]["api"] is api


@run_async
async def test_async_setup_still_returns_true_and_registers_the_frontend() -> None:
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(async_register_static_paths=AsyncMock()),
    )
    assert await async_setup(hass, {}) is True
    hass.http.async_register_static_paths.assert_awaited_once()
