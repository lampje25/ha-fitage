"""Tests for durable FITAGE history synchronization."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import wraps
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fitage.api import FeelfitApi
from custom_components.fitage.history import (
    FitageHistoryManager,
    HistoryPage,
    HistorySchemaError,
    HistorySyncError,
)


def run_async(func):
    """Run a coroutine test without requiring an external pytest plugin."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def _record(
    measurement_id: str,
    user_id: str = "user-primary",
    timestamp: int | str = 1704067200,
    weight: float = 70.0,
) -> dict[str, Any]:
    return {
        "measurement_id": measurement_id,
        "user_id": user_id,
        "time_stamp": timestamp,
        "weight": weight,
        "height": 175,
        "birthday": "2000-01-01",
        "gender": 1,
    }


def _page(
    updated: int = 1,
    measurement_cursor: str = "cursor-1",
    *,
    finish: int = 1,
    records: list[dict[str, Any]] | None = None,
    deletes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "measurements": records if records is not None else [_record("measure-1")],
        "delete_measurement_ids": deletes or [],
        "last_updated_at": updated,
        "last_measurement_id": measurement_cursor,
        "finish_flag": finish,
    }


class FakeStore:
    """In-memory Store double with immutable save snapshots."""

    def __init__(self, loaded: dict[str, Any] | None = None) -> None:
        self.loaded = deepcopy(loaded)
        self.saves: list[dict[str, Any]] = []
        self.fail_on_save: int | None = None

    async def async_load(self) -> dict[str, Any] | None:
        return deepcopy(self.loaded)

    async def async_save(self, data: dict[str, Any]) -> None:
        if self.fail_on_save == len(self.saves) + 1:
            raise OSError("synthetic write failure")
        self.saves.append(deepcopy(data))
        self.loaded = deepcopy(data)


class FakeApi:
    """Serve deterministic pages and record cursor calls."""

    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int, str]] = []

    async def async_get_measurements_history_page(
        self, user_id: str, last_updated_at: int, last_measurement_id: str
    ) -> dict[str, Any]:
        self.calls.append((user_id, last_updated_at, last_measurement_id))
        result = self.pages[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


def test_history_page_parses_live_contract_types() -> None:
    raw = _page(
        updated=42,
        measurement_cursor="cursor-42",
        records=[_record("measure-a"), _record("measure-b")],
        deletes=["deleted-a"],
    )

    page = HistoryPage.parse(raw, "user-primary")

    assert page.last_updated_at == 42
    assert page.last_measurement_id == "cursor-42"
    assert page.finish is True
    assert len(page.measurements) == 2
    assert page.delete_measurement_ids == ("deleted-a",)


def test_optional_zero_none_and_missing_fields_are_preserved() -> None:
    record = _record("measure-a", weight=0)
    record["optional_none"] = None

    page = HistoryPage.parse(_page(records=[record]), "user-primary")

    stored = page.upserts["measure-a"]
    assert stored["weight"] == 0
    assert stored["optional_none"] is None
    assert "bodyfat" not in stored


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {},
        _page(updated=True),
        {**_page(), "last_measurement_id": 7},
        {**_page(), "finish_flag": "1"},
        {**_page(), "delete_measurement_ids": [7]},
        _page(records=[{"measurement_id": "measure-a", "user_id": "user-primary"}]),
    ],
)
def test_history_page_rejects_unexpected_schema(raw: Any) -> None:
    with pytest.raises(HistorySchemaError):
        HistoryPage.parse(raw, "user-primary")


def test_history_page_rejects_cross_profile_record_without_exposing_id() -> None:
    with pytest.raises(HistorySchemaError) as err:
        HistoryPage.parse(
            _page(records=[_record("measure-private", "user-other")]),
            "user-primary",
        )

    message = str(err.value)
    assert "user-primary" not in message
    assert "user-other" not in message
    assert "measure-private" not in message


@run_async
async def test_store_configuration_and_empty_load() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)

    await manager.async_load()

    assert manager.data == {"profiles": {}}
    assert store.saves == []


def test_store_is_private_versioned_atomic_and_scoped_to_entry() -> None:
    hass = MagicMock()
    with patch("custom_components.fitage.history.Store") as store_class:
        manager = FitageHistoryManager(hass, "entry-fixture")

    store_class.assert_called_once_with(
        hass,
        1,
        "fitage.history_entry-fixture",
        private=True,
        atomic_writes=True,
        serialize_in_event_loop=False,
    )
    assert manager.store_key == "fitage.history_entry-fixture"


@run_async
async def test_store_load_rejects_incomplete_profile_transaction() -> None:
    manager = FitageHistoryManager(
        None,
        "entry-fixture",
        store=FakeStore({"profiles": {"user-primary": {"measurements": {}}}}),
    )

    with pytest.raises(HistorySchemaError):
        await manager.async_load()


@run_async
async def test_page_transaction_upserts_deletes_and_cursor_together() -> None:
    initial = {
        "profiles": {
            "user-primary": {
                "cursor": {"last_updated_at": 9, "last_measurement_id": "cursor-9"},
                "measurements": {
                    "measure-update": _record("measure-update", weight=60),
                    "measure-delete": _record("measure-delete"),
                },
                "sync": {"complete": True},
            }
        }
    }
    store = FakeStore(initial)
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    api = FakeApi(
        [
            _page(
                10,
                "cursor-10",
                records=[
                    _record("measure-update", weight=61),
                    _record("measure-new", weight=62),
                ],
                deletes=["measure-delete", "missing-delete"],
            )
        ]
    )

    result = await manager.async_sync_profile(api, "user-primary")

    saved = store.saves[-1]["profiles"]["user-primary"]
    assert set(saved["measurements"]) == {"measure-update", "measure-new"}
    assert saved["measurements"]["measure-update"]["weight"] == 61
    assert saved["cursor"] == {
        "last_updated_at": 10,
        "last_measurement_id": "cursor-10",
    }
    assert saved["sync"]["complete"] is True
    assert result.pages_processed == 1


@run_async
async def test_delete_wins_when_page_also_contains_same_id() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    api = FakeApi(
        [_page(records=[_record("measure-a")], deletes=["measure-a", "measure-a"])]
    )

    await manager.async_sync_profile(api, "user-primary")

    assert manager.measurements("user-primary") == {}


@run_async
async def test_two_profiles_are_strictly_isolated() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    await manager.async_sync_profile(
        FakeApi([_page(records=[_record("same-id", "user-primary")])]),
        "user-primary",
    )
    await manager.async_sync_profile(
        FakeApi([_page(records=[_record("same-id", "user-sub")])]),
        "user-sub",
    )

    assert manager.measurements("user-primary")["same-id"]["user_id"] == "user-primary"
    assert manager.measurements("user-sub")["same-id"]["user_id"] == "user-sub"


@run_async
async def test_restart_resumes_saved_cursor_never_profile_timestamp() -> None:
    loaded = {
        "profiles": {
            "user-primary": {
                "cursor": {"last_updated_at": 25, "last_measurement_id": "cursor-25"},
                "measurements": {},
                "sync": {"complete": True},
            }
        }
    }
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore(loaded))
    await manager.async_load()
    api = FakeApi([_page(26, "cursor-26")])

    await manager.async_sync_profile(api, "user-primary")

    assert api.calls == [("user-primary", 25, "cursor-25")]


@run_async
async def test_successful_multiple_pages_commit_each_page_and_finish() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    api = FakeApi(
        [
            _page(
                1,
                "cursor-1",
                finish=0,
                records=[_record("measure-1")],
            ),
            _page(
                2,
                "cursor-2",
                finish=1,
                records=[_record("measure-2")],
            ),
        ]
    )

    result = await manager.async_sync_profile(api, "user-primary")

    assert result.pages_processed == 2
    assert result.end_reason == "finish_flag"
    assert len(store.saves) == 2
    assert manager.cursor("user-primary") == (2, "cursor-2")
    assert set(manager.measurements("user-primary")) == {"measure-1", "measure-2"}


@run_async
async def test_new_profile_starts_at_zero_cursor() -> None:
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore())
    await manager.async_load()
    api = FakeApi([_page()])

    await manager.async_sync_profile(api, "user-primary")

    assert api.calls == [("user-primary", 0, "0")]


@run_async
async def test_api_failure_on_page_two_keeps_page_one_transaction() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    api = FakeApi(
        [
            _page(1, "cursor-1", finish=0),
            RuntimeError("synthetic API failure with private-id"),
        ]
    )

    with pytest.raises(HistorySyncError) as err:
        await manager.async_sync_profile(api, "user-primary")

    assert len(store.saves) == 1
    assert manager.cursor("user-primary") == (1, "cursor-1")
    assert "private-id" not in str(err.value)
    assert err.value.__cause__ is None


@run_async
async def test_invalid_page_does_not_commit_any_part() -> None:
    store = FakeStore()
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()
    api = FakeApi([_page(records=[_record("measure-a", "wrong-user")])])

    with pytest.raises(HistorySchemaError):
        await manager.async_sync_profile(api, "user-primary")

    assert store.saves == []
    assert manager.data == {"profiles": {}}


@run_async
async def test_failed_store_save_does_not_advance_memory_cursor() -> None:
    store = FakeStore()
    store.fail_on_save = 1
    manager = FitageHistoryManager(None, "entry-fixture", store=store)
    await manager.async_load()

    with pytest.raises(OSError):
        await manager.async_sync_profile(FakeApi([_page()]), "user-primary")

    assert manager.cursor("user-primary") == (0, "0")
    assert manager.measurements("user-primary") == {}


@pytest.mark.parametrize(
    ("pages", "reason"),
    [
        ([_page(0, "0", finish=0, records=[])], "stalled_cursor"),
        (
            [
                _page(1, "cursor-1", finish=0),
                _page(0, "0", finish=0, records=[_record("measure-2")]),
            ],
            "repeated_cursor",
        ),
        (
            [
                _page(1, "cursor-1", finish=0),
                _page(2, "cursor-2", finish=0),
            ],
            "repeated_page",
        ),
    ],
)
@run_async
async def test_cursor_loop_safety_stops(
    pages: list[dict[str, Any]], reason: str
) -> None:
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore())
    await manager.async_load()

    result = await manager.async_sync_profile(FakeApi(pages), "user-primary")

    assert result.end_reason == reason


@run_async
async def test_cursor_loop_stops_after_ten_pages() -> None:
    pages = [
        _page(
            number,
            f"cursor-{number}",
            finish=0,
            records=[_record(f"measure-{number}")],
        )
        for number in range(1, 12)
    ]
    api = FakeApi(pages)
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore())
    await manager.async_load()

    result = await manager.async_sync_profile(api, "user-primary")

    assert len(api.calls) == 10
    assert result.end_reason == "page_limit"
    assert manager.cursor("user-primary") == (10, "cursor-10")


def test_latest_measurement_uses_timestamp_then_id_tiebreaker() -> None:
    loaded = {
        "profiles": {
            "user-primary": {
                "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor-1"},
                "measurements": {
                    "measure-z": _record("measure-z", timestamp=200),
                    "measure-a": _record("measure-a", timestamp=300, weight=71),
                    "measure-b": _record("measure-b", timestamp=300, weight=72),
                },
                "sync": {"complete": True},
            }
        }
    }
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore(loaded))
    manager.load_for_test(loaded)

    latest = manager.latest_measurement("user-primary")

    assert latest is not None
    assert latest["measurement_id"] == "measure-b"
    assert latest["weight"] == 72


def test_duplicate_measurement_id_in_page_is_deterministic_last_wins() -> None:
    page = HistoryPage.parse(
        _page(
            records=[
                _record("measure-a", weight=60),
                _record("measure-a", weight=61),
            ]
        ),
        "user-primary",
    )

    assert page.upserts["measure-a"]["weight"] == 61


@run_async
async def test_api_fetch_uses_history_and_selects_latest_not_first() -> None:
    api = FeelfitApi(None, None, "fixture@example.invalid")
    api.token = "synthetic-token"
    api._last_measurements_meta = {
        "user-primary": {"last_updated_at": 999, "last_measurement_id": "legacy"}
    }
    legacy_meta = deepcopy(api._last_measurements_meta)
    history = FitageHistoryManager(None, "entry-fixture", store=FakeStore())
    await history.async_load()
    api.history = history
    api.async_list_all_profiles = AsyncMock(
        return_value=[{"user_id": "user-primary", "time_stamp": 9999999999}]
    )
    api.async_get_primary_user = AsyncMock(
        return_value={"user_info": {"user_id": "user-primary"}}
    )
    api.async_get_user_settings = AsyncMock(return_value={})
    api.async_list_goals = AsyncMock(return_value={"goals": []})
    api.async_list_device_binds = AsyncMock(
        return_value={"device_binds": [], "device_models": []}
    )
    api.async_get_measurements_history_page = AsyncMock(
        return_value=_page(
            1,
            "cursor-1",
            records=[
                _record("measure-new", timestamp=300, weight=72),
                _record("measure-old", timestamp=100, weight=60),
                _record("measure-tie", timestamp=300, weight=73),
            ],
        )
    )

    payload = await api.async_fetch_all(
        "user-primary", selected_profiles=["user-primary"]
    )

    measurement = payload["profiles"][0]["measurements"]["last_measurement"]
    assert measurement["measurement_id"] == "measure-tie"
    assert measurement["weight"] == 73
    api.async_get_measurements_history_page.assert_awaited_once_with(
        "user-primary", last_updated_at=0, last_measurement_id="0"
    )
    assert api._last_measurements_meta == legacy_meta


@run_async
async def test_sync_status_reports_only_safe_counts_and_categories() -> None:
    initial = {
        "profiles": {
            "user-primary": {
                "cursor": {"last_updated_at": 9, "last_measurement_id": "cursor-9"},
                "measurements": {"measure-delete": _record("measure-delete")},
                "sync": {"complete": True},
            }
        }
    }
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore(initial))
    await manager.async_load()

    await manager.async_sync_profile(
        FakeApi([_page(deletes=["measure-delete", "unknown-private-id"])]),
        "user-primary",
    )

    assert manager.sync_status("user-primary") == {
        "end_reason": "finish_flag",
        "pages_processed": 1,
        "started_from_stored_cursor": True,
        "delete_ids_received": 2,
        "delete_ids_applied": 1,
        "delete_ids_unknown": 1,
    }


@run_async
async def test_sync_status_redacts_api_failure_and_new_profile_start() -> None:
    manager = FitageHistoryManager(None, "entry-fixture", store=FakeStore())
    await manager.async_load()

    with pytest.raises(HistorySyncError):
        await manager.async_sync_profile(
            FakeApi([RuntimeError("private request and cursor values")]),
            "user-primary",
        )

    assert manager.sync_status("user-primary") == {
        "end_reason": "api_error",
        "pages_processed": 0,
        "started_from_stored_cursor": False,
        "delete_ids_received": 0,
        "delete_ids_applied": 0,
        "delete_ids_unknown": 0,
    }
