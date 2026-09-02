"""Tests for optional FITAGE external statistics."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from functools import wraps
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from custom_components.fitage.history import FitageHistoryManager, HistoryPage
from custom_components.fitage.statistics import (
    STATISTIC_METRICS,
    FitageStatisticsImporter,
    hourly_statistics,
    statistic_id,
)


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


class Store:
    def __init__(self, loaded: dict[str, Any] | None = None) -> None:
        self.loaded = deepcopy(loaded)
        self.saves: list[dict[str, Any]] = []

    async def async_load(self) -> dict[str, Any] | None:
        return deepcopy(self.loaded)

    async def async_save(self, data: dict[str, Any]) -> None:
        self.loaded = deepcopy(data)
        self.saves.append(deepcopy(data))


def record(mid: str, user: str, timestamp: float, **values: Any) -> dict[str, Any]:
    return {"measurement_id": mid, "user_id": user, "time_stamp": timestamp, **values}


def raw_data() -> dict[str, Any]:
    return {
        "profiles": {
            "private-a": {
                "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor"},
                "measurements": {
                    "a": record("a", "private-a", 3601, weight=60, bmi=None),
                    "b": record("b", "private-a", 3650, weight=0, bodyfat=20),
                    "c": record("c", "private-a", 7200, weight=62),
                },
                "sync": {"complete": True},
            },
            "private-b": {
                "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor"},
                "measurements": {"d": record("d", "private-b", 3602, weight=80)},
                "sync": {"complete": True},
            },
        }
    }


def loaded_manager(store: Store | None = None) -> FitageHistoryManager:
    result = FitageHistoryManager(None, "entry", store=store or Store())
    result.load_for_test(raw_data())
    result.configure_statistics(frozenset(STATISTIC_METRICS))
    return result


def test_metric_allowlist_and_metadata() -> None:
    assert STATISTIC_METRICS["weight"].unit == "kg"
    assert STATISTIC_METRICS["weight"].unit_class == "mass"
    assert STATISTIC_METRICS["bodyfat"].unit == "%"
    assert STATISTIC_METRICS["bmr"].unit_class == "energy"
    assert "body_shape" not in STATISTIC_METRICS
    assert "visfat" not in STATISTIC_METRICS
    assert "cardiac_index" not in STATISTIC_METRICS
    assert "bodyage" not in STATISTIC_METRICS


def test_statistic_id_stable_private_and_isolated() -> None:
    first = statistic_id("entry-a", "private-user", "weight")
    assert first == statistic_id("entry-a", "private-user", "weight")
    assert first != statistic_id("entry-a", "other-user", "weight")
    assert first != statistic_id("entry-b", "private-user", "weight")
    assert first.startswith("fitage:")
    assert "private-user" not in first


def test_last_of_hour_utc_tie_breaker_zero_none_and_missing() -> None:
    records = {
        "z": record("z", "u", 3605, weight=3),
        "a": record("a", "u", 3605, weight=2),
        "zero": record("zero", "u", 3700, weight=0),
        "none": record("none", "u", 7200, weight=None),
        "missing": record("missing", "u", 10800),
    }
    result = hourly_statistics(records, "weight")
    assert result == [{"start": datetime(1970, 1, 1, 1, tzinfo=UTC), "state": 0.0}]


def test_utc_hours_are_dst_independent() -> None:
    # Two distinct UTC hours during Europe's repeated autumn wall-clock hour.
    records = {
        "a": record("a", "u", 1729989000, weight=1),
        "b": record("b", "u", 1729992600, weight=2),
    }
    result = hourly_statistics(records, "weight")
    assert len(result) == 2
    assert all(item["start"].tzinfo is UTC for item in result)
    assert result[1]["start"] - result[0]["start"] == __import__("datetime").timedelta(
        hours=1
    )


@run_async
async def test_prepare_pending_is_persistent_and_restart_safe() -> None:
    store = Store()
    manager = loaded_manager(store)
    await manager.async_prepare_statistics()
    pending = manager.pending_statistics_rebuilds()
    assert ("private-a", "weight") in pending
    assert ("private-b", "weight") in pending
    restarted = FitageHistoryManager(None, "entry", store=Store(store.loaded))
    await restarted.async_load()
    restarted.configure_statistics(frozenset(STATISTIC_METRICS))
    assert restarted.pending_statistics_rebuilds() == pending


@run_async
async def test_no_import_without_opt_in() -> None:
    manager = loaded_manager()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=False)
    with patch("custom_components.fitage.statistics.get_instance") as recorder:
        await importer.async_reconcile()
    recorder.assert_not_called()
    assert manager.pending_statistics_rebuilds() == []


@run_async
async def test_rebuild_clears_only_target_then_imports_and_completes() -> None:
    store = Store()
    manager = loaded_manager(store)
    manager.configure_statistics(frozenset({"weight"}))
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    importer._history.configure_statistics(frozenset({"weight"}))
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = lambda ids, on_done: on_done()
    with (
        patch(
            "custom_components.fitage.statistics.get_instance", return_value=recorder
        ),
        patch(
            "custom_components.fitage.statistics.async_add_external_statistics"
        ) as add,
    ):
        await importer.async_reconcile()
    cleared = [
        call.args[0][0] for call in recorder.async_clear_statistics.call_args_list
    ]
    assert set(cleared) == {
        statistic_id("entry", "private-a", "weight"),
        statistic_id("entry", "private-b", "weight"),
    }
    assert add.call_count == 2
    assert manager.pending_statistics_rebuilds() == []
    assert store.saves


@run_async
async def test_import_failure_keeps_pending_and_raw_unchanged() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    before = manager.measurements("private-a")
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    importer._history.configure_statistics(frozenset({"weight"}))
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = lambda ids, on_done: on_done()
    with (
        patch(
            "custom_components.fitage.statistics.get_instance", return_value=recorder
        ),
        patch(
            "custom_components.fitage.statistics.async_add_external_statistics",
            side_effect=RuntimeError("failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        await importer.async_reconcile()
    assert ("private-a", "weight") in manager.pending_statistics_rebuilds()
    assert manager.measurements("private-a") == before


@run_async
async def test_clear_failure_keeps_pending() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    importer._history.configure_statistics(frozenset({"weight"}))
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = RuntimeError("clear failure")
    with (
        patch(
            "custom_components.fitage.statistics.get_instance", return_value=recorder
        ),
        pytest.raises(RuntimeError),
    ):
        await importer.async_reconcile()
    assert ("private-a", "weight") in manager.pending_statistics_rebuilds()


@run_async
async def test_disabling_during_pending_and_reenabling_resumes() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    await manager.async_prepare_statistics()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=False)
    importer._history.configure_statistics(frozenset({"weight"}))
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = lambda ids, on_done: on_done()
    with (
        patch(
            "custom_components.fitage.statistics.get_instance", return_value=recorder
        ),
        patch("custom_components.fitage.statistics.async_add_external_statistics"),
    ):
        await importer.async_reconcile()
        recorder.assert_not_called()
        importer.enabled = True
        await importer.async_reconcile()
    assert recorder.async_clear_statistics.called
    assert manager.pending_statistics_rebuilds() == []


async def mark_current_scheduled(manager: FitageHistoryManager) -> None:
    await manager.async_prepare_statistics()
    for user_id, metric in list(manager.pending_statistics_rebuilds()):
        await manager.async_mark_statistics_scheduled(
            user_id, metric, manager.statistics_fingerprint(user_id, metric)
        )


@run_async
async def test_unknown_delete_does_not_trigger_rebuild() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight", "bodyfat"}))
    await mark_current_scheduled(manager)
    page = HistoryPage.parse(
        {
            "measurements": [],
            "delete_measurement_ids": ["unknown-delete"],
            "last_updated_at": 2,
            "last_measurement_id": "next",
            "finish_flag": 1,
        },
        "private-a",
    )
    await manager._async_commit_page("private-a", page)
    assert manager.pending_statistics_rebuilds() == []


@run_async
async def test_known_delete_rebuilds_only_affected_profile_metrics() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight", "bodyfat"}))
    await mark_current_scheduled(manager)
    page = HistoryPage.parse(
        {
            "measurements": [],
            "delete_measurement_ids": ["b"],
            "last_updated_at": 2,
            "last_measurement_id": "next",
            "finish_flag": 1,
        },
        "private-a",
    )
    await manager._async_commit_page("private-a", page)
    assert set(manager.pending_statistics_rebuilds()) == {
        ("private-a", "weight"),
        ("private-a", "bodyfat"),
    }
    assert manager.measurements("private-b")["d"]["weight"] == 80


@run_async
async def test_update_same_hour_and_timestamp_move_mark_metric_pending() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight", "bodyfat"}))
    await mark_current_scheduled(manager)
    same_hour = HistoryPage.parse(
        {
            "measurements": [record("a", "private-a", 3601, weight=61, bmi=None)],
            "delete_measurement_ids": [],
            "last_updated_at": 2,
            "last_measurement_id": "next",
            "finish_flag": 1,
        },
        "private-a",
    )
    await manager._async_commit_page("private-a", same_hour)
    assert manager.pending_statistics_rebuilds() == [("private-a", "weight")]
    await manager.async_mark_statistics_scheduled(
        "private-a", "weight", manager.statistics_fingerprint("private-a", "weight")
    )
    moved = HistoryPage.parse(
        {
            "measurements": [record("a", "private-a", 10800, weight=61, bmi=None)],
            "delete_measurement_ids": [],
            "last_updated_at": 3,
            "last_measurement_id": "later",
            "finish_flag": 1,
        },
        "private-a",
    )
    await manager._async_commit_page("private-a", moved)
    assert manager.pending_statistics_rebuilds() == [("private-a", "weight")]


@run_async
async def test_delete_with_hour_replacement_reprojects_last_measurement() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    await mark_current_scheduled(manager)
    page = HistoryPage.parse(
        {
            "measurements": [],
            "delete_measurement_ids": ["b"],
            "last_updated_at": 2,
            "last_measurement_id": "next",
            "finish_flag": 1,
        },
        "private-a",
    )
    await manager._async_commit_page("private-a", page)
    result = hourly_statistics(manager.measurements("private-a"), "weight")
    assert result[0]["state"] == 60.0


def test_friendly_metric_names_and_stable_rc2_id() -> None:
    assert statistic_id("entry", "private-a", "weight") == (
        "fitage:923fe53966_e6db023f3a0e_weight"
    )
    assert {
        metric: definition.name for metric, definition in STATISTIC_METRICS.items()
    } == {
        "weight": "Weight",
        "bmi": "BMI",
        "bodyfat": "Body fat",
        "water": "Body water",
        "muscle": "Muscle",
        "bone": "Bone mass",
        "protein": "Protein",
        "subfat": "Subcutaneous fat",
        "fat_free_weight": "Fat-free weight",
        "body_fat_mass": "Body fat mass",
        "body_water_mass": "Body water mass",
        "protein_mass": "Protein mass",
        "bmr": "Basal metabolic rate",
        "score": "Score",
        "heart_rate": "Heart rate",
    }


@run_async
async def test_profile_rename_upserts_metadata_without_clear_or_duplicate() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    importer._history.configure_statistics(frozenset({"weight"}))
    importer.configure_profile_names(
        [
            {"user_id": "private-a", "account_name": "Old name"},
            {"user_id": "private-b", "account_name": "Melissa"},
        ]
    )
    recorder = MagicMock()
    recorder.async_clear_statistics.side_effect = lambda ids, on_done: on_done()
    with (
        patch(
            "custom_components.fitage.statistics.get_instance", return_value=recorder
        ),
        patch(
            "custom_components.fitage.statistics.async_add_external_statistics"
        ) as add,
    ):
        await importer.async_reconcile()
        original_ids = {call.args[1]["statistic_id"] for call in add.call_args_list}
        assert {call.args[1]["name"] for call in add.call_args_list} == {
            "FITAGE Old name – Weight",
            "FITAGE Melissa – Weight",
        }
        raw_before_rename = manager.data
        saves_before_rename = len(manager._store.saves)
        recorder.reset_mock()
        add.reset_mock()

        importer.configure_profile_names(
            [
                {"user_id": "private-a", "account_name": "Renamed"},
                {"user_id": "private-b", "account_name": "Melissa"},
            ]
        )
        await importer.async_reconcile()

    recorder.async_clear_statistics.assert_not_called()
    assert {call.args[1]["statistic_id"] for call in add.call_args_list} == original_ids
    assert len(add.call_args_list) == len(original_ids)
    assert {call.args[1]["name"] for call in add.call_args_list} == {
        "FITAGE Renamed – Weight",
        "FITAGE Melissa – Weight",
    }
    assert all(call.args[2] == [] for call in add.call_args_list)
    assert manager.data == raw_before_rename
    assert len(manager._store.saves) == saves_before_rename


def test_duplicate_display_names_get_short_stable_private_refs() -> None:
    manager = loaded_manager()
    hass = SimpleNamespace(loop=None)
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    profiles = [
        {"user_id": "private-a", "account_name": "Melissa"},
        {"user_id": "private-b", "account_name": "melissa"},
    ]
    importer.configure_profile_names(profiles)
    first = importer._metadata("private-a", "heart_rate")
    second = importer._metadata("private-b", "heart_rate")
    importer.configure_profile_names(list(reversed(profiles)))

    assert first["name"] != second["name"]
    assert first["name"].startswith("FITAGE Melissa (")
    assert second["name"].startswith("FITAGE melissa (")
    assert first["name"].endswith(" – Heart rate")
    assert "private-a" not in first["name"]
    assert "private-b" not in second["name"]
    assert importer._metadata("private-a", "heart_rate")["name"] == first["name"]
    assert importer._metadata("private-b", "heart_rate")["name"] == second["name"]


@run_async
async def test_metadata_upsert_does_not_touch_another_entry() -> None:
    manager = loaded_manager()
    manager.configure_statistics(frozenset({"weight"}))
    await mark_current_scheduled(manager)
    before = manager.data
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    importer = FitageStatisticsImporter(hass, "entry", manager, enabled=True)
    importer._history.configure_statistics(frozenset({"weight"}))
    importer.configure_profile_names(
        [
            {"user_id": "private-a", "account_name": "Primary"},
            {"user_id": "private-b", "account_name": "Melissa"},
        ]
    )
    with patch(
        "custom_components.fitage.statistics.async_add_external_statistics"
    ) as add:
        await importer.async_reconcile()

    expected = {
        statistic_id("entry", "private-a", "weight"),
        statistic_id("entry", "private-b", "weight"),
    }
    assert {call.args[1]["statistic_id"] for call in add.call_args_list} == expected
    assert all(
        call.args[1]["statistic_id"]
        != statistic_id("other-entry", "private-a", "weight")
        for call in add.call_args_list
    )
    assert manager.data == before
