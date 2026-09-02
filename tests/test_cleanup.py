"""Tests for final FITAGE config-entry cleanup."""

from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.recorder import DATA_INSTANCE

from custom_components.fitage import async_remove_entry
from custom_components.fitage.history import FitageHistoryManager
from custom_components.fitage.statistics import (
    STATISTIC_METRICS,
    StatisticsCleanupError,
    async_clear_entry_statistics,
    statistic_id,
)


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


@run_async
async def test_remove_entry_clears_only_owned_statistics_and_store() -> None:
    loop = asyncio.get_running_loop()
    store = MagicMock()
    store.async_remove = AsyncMock()
    history = FitageHistoryManager(None, "entry-own", store=store)
    history.load_for_test(
        {
            "profiles": {
                "profile-from-store": {
                    "cursor": {"last_updated_at": 0, "last_measurement_id": "0"},
                    "measurements": {},
                    "sync": {"complete": True},
                    "statistics": {
                        "version": 1,
                        "fingerprints": {"weight": "scheduled"},
                        "pending_rebuilds": [],
                        "imported_metrics": ["weight"],
                    },
                }
            }
        }
    )
    hass = SimpleNamespace(
        data={DATA_INSTANCE: object(), "fitage": {"entry-own": {"history": history}}},
        loop=loop,
    )
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = lambda ids, on_done: on_done()
    entry = SimpleNamespace(
        entry_id="entry-own",
        data={
            "profiles_list": [{"user_id": "profile-from-config"}],
            "selected_profiles": ["profile-selected"],
            "user_info": {"user_id": "profile-primary"},
        },
    )
    with patch(
        "custom_components.fitage.statistics.get_instance", return_value=recorder
    ):
        await async_remove_entry(hass, entry)

    cleared = set(recorder.async_clear_statistics.call_args.args[0])
    expected_profiles = {
        "profile-from-store",
        "profile-from-config",
        "profile-selected",
        "profile-primary",
    }
    assert cleared == {
        statistic_id("entry-own", profile, metric)
        for profile in expected_profiles
        for metric in STATISTIC_METRICS
    }
    other_entry_statistics = {
        statistic_id("entry-other", profile, metric)
        for profile in expected_profiles
        for metric in STATISTIC_METRICS
    }
    assert cleared.isdisjoint(other_entry_statistics)
    store.async_remove.assert_awaited_once()


@run_async
async def test_cleanup_without_recorder_is_idempotent() -> None:
    hass = SimpleNamespace(data={}, loop=asyncio.get_running_loop())
    with patch("custom_components.fitage.statistics.get_instance") as get_recorder:
        await async_clear_entry_statistics(hass, "entry", set())
    get_recorder.assert_not_called()


@run_async
async def test_history_store_removal_is_idempotent() -> None:
    store = MagicMock()
    store.async_remove = AsyncMock()
    history = FitageHistoryManager(None, "entry", store=store)
    history.load_for_test({"profiles": {}})

    await history.async_remove_store()
    await history.async_remove_store()

    assert store.async_remove.await_count == 2


@run_async
async def test_clear_failure_preserves_store() -> None:
    store = MagicMock()
    store.async_remove = AsyncMock()
    history = FitageHistoryManager(None, "entry", store=store)
    history.load_for_test(
        {
            "profiles": {
                "profile": {
                    "cursor": {"last_updated_at": 0, "last_measurement_id": "0"},
                    "measurements": {},
                    "sync": {"complete": True},
                    "statistics": {
                        "version": 1,
                        "fingerprints": {"weight": "scheduled"},
                        "pending_rebuilds": [],
                        "imported_metrics": ["weight"],
                    },
                }
            }
        }
    )
    hass = SimpleNamespace(
        data={"fitage": {"entry": {"history": history}}},
        loop=asyncio.get_running_loop(),
    )
    entry = SimpleNamespace(entry_id="entry", data={})
    with patch(
        "custom_components.fitage.async_clear_entry_statistics",
        AsyncMock(side_effect=StatisticsCleanupError("redacted")),
    ):
        await async_remove_entry(hass, entry)
    store.async_remove.assert_not_awaited()


@run_async
async def test_never_imported_entry_skips_recorder_and_removes_store() -> None:
    store = MagicMock()
    store.async_remove = AsyncMock()
    history = FitageHistoryManager(None, "entry", store=store)
    history.load_for_test({"profiles": {}})
    hass = SimpleNamespace(
        data={"fitage": {"entry": {"history": history}}},
        loop=asyncio.get_running_loop(),
    )
    entry = SimpleNamespace(entry_id="entry", data={})

    with patch("custom_components.fitage.async_clear_entry_statistics") as clear:
        await async_remove_entry(hass, entry)

    clear.assert_not_called()
    store.async_remove.assert_awaited_once()


@run_async
async def test_recorder_unavailable_preserves_store() -> None:
    store = MagicMock()
    store.async_remove = AsyncMock()
    history = FitageHistoryManager(None, "entry", store=store)
    history.load_for_test(
        {
            "profiles": {
                "profile": {
                    "cursor": {"last_updated_at": 0, "last_measurement_id": "0"},
                    "measurements": {},
                    "sync": {"complete": True},
                    "statistics": {
                        "version": 1,
                        "fingerprints": {"weight": "scheduled"},
                        "pending_rebuilds": [],
                        "imported_metrics": ["weight"],
                    },
                }
            }
        }
    )
    hass = SimpleNamespace(
        data={"fitage": {"entry": {"history": history}}},
        loop=asyncio.get_running_loop(),
    )
    entry = SimpleNamespace(entry_id="entry", data={})

    await async_remove_entry(hass, entry)

    store.async_remove.assert_not_awaited()
