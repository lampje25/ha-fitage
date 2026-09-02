"""Tests for read-only FITAGE history websocket commands."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.exceptions import Unauthorized

from custom_components.fitage.history import FitageHistoryManager
from custom_components.fitage.history_websocket import (
    ALLOWED_METRICS,
    COMMAND_PROFILES,
    COMMAND_QUERY,
    MAX_LIMIT,
    QUERY_SCHEMA,
    HistoryWebsocketError,
    _entry_data,
    _profile_ref,
    async_register_history_websocket,
    list_profiles,
    query_history,
    websocket_history_profiles,
)


class Store:
    def __init__(self) -> None:
        self.saves: list[Any] = []

    async def async_save(self, data: Any) -> None:
        self.saves.append(data)


def record(mid: str, uid: str, timestamp: int, **values: Any) -> dict[str, Any]:
    return {
        "measurement_id": mid,
        "user_id": uid,
        "time_stamp": timestamp,
        "birthday": "private-birthday",
        "email": "private@example.test",
        "impedance": 999,
        **values,
    }


def manager(store: Store | None = None) -> FitageHistoryManager:
    result = FitageHistoryManager(None, "entry", store=store or Store())
    result.load_for_test(
        {
            "profiles": {
                "private-user-a": {
                    "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor-a"},
                    "measurements": {
                        "private-id-b": record(
                            "private-id-b", "private-user-a", 20, weight=0, bmi=None
                        ),
                        "private-id-a": record(
                            "private-id-a", "private-user-a", 10, weight=70
                        ),
                        "private-id-c": record(
                            "private-id-c", "private-user-a", 20, weight=71
                        ),
                    },
                    "sync": {"complete": True},
                },
                "private-user-b": {
                    "cursor": {"last_updated_at": 2, "last_measurement_id": "cursor-b"},
                    "measurements": {
                        "private-id-d": record(
                            "private-id-d", "private-user-b", 30, weight=80
                        )
                    },
                    "sync": {"complete": True},
                },
            }
        }
    )
    return result


def entry_data(store: Store | None = None) -> dict[str, Any]:
    api = MagicMock()
    return {
        "history": manager(store),
        "api": api,
        "profiles": [
            {"user_info": {"user_id": "private-user-a", "account_name": "Same"}},
            {"user_info": {"user_id": "private-user-b", "account_name": "Same"}},
        ],
    }


def message(profile: str, **changes: Any) -> dict[str, Any]:
    value = {
        "config_entry_id": "entry-one",
        "profile_ref": profile,
        "metrics": ["weight"],
        "limit": 100,
        "sort": "ascending",
    }
    value.update(changes)
    return value


def test_commands_register_once_and_require_admin() -> None:
    hass = MagicMock()
    hass.data = {}
    async_register_history_websocket(hass)
    async_register_history_websocket(hass)
    assert hass.data["fitage"]["history_websocket_registered"] is True
    assert set(hass.data["websocket_api"]) == {COMMAND_PROFILES, COMMAND_QUERY}
    connection = MagicMock(user=SimpleNamespace(is_admin=False))
    with pytest.raises(Unauthorized):
        websocket_history_profiles(hass, connection, {"id": 1, "config_entry_id": "x"})


def test_profile_listing_isolated_same_names_and_private() -> None:
    data = entry_data()
    before = data["history"].data
    result = list_profiles("entry-one", data)
    assert [item["display_name"] for item in result["profiles"]] == ["Same", "Same"]
    assert len({item["profile_ref"] for item in result["profiles"]}) == 2
    assert [item["record_count"] for item in result["profiles"]] == [3, 1]
    assert result["profiles"][0]["oldest_timestamp"] == 10.0
    assert result["profiles"][0]["newest_timestamp"] == 20.0
    assert "weight" in result["profiles"][0]["available_metrics"]
    assert data["history"].data == before
    rendered = json.dumps(result)
    assert "private-user" not in rendered
    assert "private-id" not in rendered


def test_empty_history_profile_listing() -> None:
    data = entry_data()
    snapshot = data["history"].data
    snapshot["profiles"]["private-user-a"]["measurements"] = {}
    data["history"].load_for_test(snapshot)
    profile = list_profiles("entry-one", data)["profiles"][0]
    assert profile["record_count"] == 0
    assert profile["oldest_timestamp"] is None
    assert profile["available_metrics"] == []


def test_multiple_entries_resolve_independently_after_unload() -> None:
    first = entry_data()
    second = entry_data()
    hass = MagicMock()
    hass.data = {"fitage": {"entry-one": first, "entry-two": second}}
    assert _entry_data(hass, "entry-one") is first
    assert _entry_data(hass, "entry-two") is second
    hass.data["fitage"].pop("entry-one")
    assert _entry_data(hass, "entry-two") is second
    with pytest.raises(HistoryWebsocketError, match="entry is not loaded"):
        _entry_data(hass, "entry-one")


def test_unknown_entry_and_unloaded_history_are_safe() -> None:
    hass = MagicMock()
    hass.data = {"fitage": {"entry-one": entry_data()}}
    assert _entry_data(hass, "entry-one")["history"].is_loaded
    with pytest.raises(HistoryWebsocketError, match="entry is not loaded"):
        _entry_data(hass, "missing")


def test_query_metrics_zero_none_missing_and_privacy() -> None:
    data = entry_data()
    profile = _profile_ref("entry-one", "private-user-a")
    msg = message(profile, metrics=["weight", "bmi", "score"])
    before = deepcopy(data["history"].data)
    result = query_history(data, msg, b"k" * 32)
    assert result["records"] == [
        {"timestamp": 10, "metrics": {"weight": 70}},
        {"timestamp": 20, "metrics": {"weight": 0, "bmi": None}},
        {"timestamp": 20, "metrics": {"weight": 71}},
    ]
    assert data["history"].data == before
    data["api"].assert_not_called()
    rendered = json.dumps(result)
    for private in ("private-user", "private-id", "birthday", "email", "impedance"):
        assert private not in rendered


def test_time_range_and_descending_tie_breaker() -> None:
    data = entry_data()
    profile = _profile_ref("entry-one", "private-user-a")
    result = query_history(
        data,
        message(profile, start_time=20.0, end_time=20.0, sort="descending"),
        b"k" * 32,
    )
    assert [item["metrics"]["weight"] for item in result["records"]] == [71, 0]


def test_pagination_and_valid_cursor() -> None:
    data = entry_data()
    profile = _profile_ref("entry-one", "private-user-a")
    first_msg = message(profile, limit=1)
    first = query_history(data, first_msg, b"k" * 32)
    second = query_history(
        data, {**first_msg, "cursor": first["next_cursor"]}, b"k" * 32
    )
    third = query_history(
        data, {**first_msg, "cursor": second["next_cursor"]}, b"k" * 32
    )
    assert [
        first["records"][0]["timestamp"],
        second["records"][0]["timestamp"],
        third["records"][0]["timestamp"],
    ] == [10, 20, 20]
    assert third["next_cursor"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"metrics": ["bmi"]},
        {"sort": "descending"},
        {"start_time": 1.0},
        {"config_entry_id": "entry-two"},
        {"profile_ref": "profile_other"},
    ],
)
def test_cursor_rejected_for_changed_query(change: dict[str, Any]) -> None:
    data = entry_data()
    profile = _profile_ref("entry-one", "private-user-a")
    original = message(profile, limit=1)
    cursor = query_history(data, original, b"k" * 32)["next_cursor"]
    with pytest.raises(HistoryWebsocketError, match="cursor is invalid"):
        query_history(data, {**original, **change, "cursor": cursor}, b"k" * 32)


def test_cursor_tampering_and_unknown_profile_rejected() -> None:
    data = entry_data()
    profile = _profile_ref("entry-one", "private-user-a")
    cursor = query_history(data, message(profile, limit=1), b"k" * 32)["next_cursor"]
    with pytest.raises(HistoryWebsocketError, match="cursor is invalid"):
        query_history(data, {**message(profile), "cursor": cursor + "x"}, b"k" * 32)
    with pytest.raises(HistoryWebsocketError, match="profile is unavailable"):
        query_history(data, message("profile_unknown"), b"k" * 32)


def test_schema_unknown_metric_limits_and_command_names() -> None:
    schema = vol.Schema(QUERY_SCHEMA)
    valid = schema(
        {
            "type": COMMAND_QUERY,
            "config_entry_id": "entry",
            "profile_ref": "ref",
            "metrics": ["weight"],
        }
    )
    assert valid["limit"] == 100
    assert valid["sort"] == "ascending"
    with pytest.raises(vol.Invalid):
        schema(
            {
                "type": COMMAND_QUERY,
                "config_entry_id": "entry",
                "profile_ref": "ref",
                "metrics": ["secret"],
            }
        )
    with pytest.raises(vol.Invalid):
        schema(
            {
                "type": COMMAND_QUERY,
                "config_entry_id": "entry",
                "profile_ref": "ref",
                "metrics": ["weight"],
                "limit": MAX_LIMIT + 1,
            }
        )
    assert COMMAND_PROFILES == "fitage/history/profiles"
    assert set(ALLOWED_METRICS) >= {"weight", "bodyfat_right_leg"}


def test_store_not_written_and_cross_profile_isolation() -> None:
    store = Store()
    data = entry_data(store)
    profile = _profile_ref("entry-one", "private-user-b")
    result = query_history(data, message(profile), b"k" * 32)
    assert [item["metrics"]["weight"] for item in result["records"]] == [80]
    assert store.saves == []
