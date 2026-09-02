"""Local Recorder runtime validation for FITAGE external statistics."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from tests.components.recorder.common import async_wait_recording_done

from custom_components.fitage.history import FitageHistoryManager
from custom_components.fitage.statistics import (
    FitageStatisticsImporter,
    statistic_id,
)


class Store:
    def __init__(self) -> None:
        self.loaded = None

    async def async_load(self):
        return deepcopy(self.loaded)

    async def async_save(self, data):
        self.loaded = deepcopy(data)


def payload() -> dict:
    return {
        "profiles": {
            "runtime-profile-a": {
                "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor"},
                "measurements": {
                    "a": {
                        "measurement_id": "a",
                        "user_id": "runtime-profile-a",
                        "time_stamp": 1735732860,
                        "weight": 60,
                    },
                    "b": {
                        "measurement_id": "b",
                        "user_id": "runtime-profile-a",
                        "time_stamp": 1735734600,
                        "weight": 61,
                    },
                },
                "sync": {"complete": True},
            },
            "runtime-profile-b": {
                "cursor": {"last_updated_at": 1, "last_measurement_id": "cursor"},
                "measurements": {
                    "c": {
                        "measurement_id": "c",
                        "user_id": "runtime-profile-b",
                        "time_stamp": 1735732920,
                        "weight": 80,
                    }
                },
                "sync": {"complete": True},
            },
        }
    }


@pytest.mark.usefixtures("recorder_mock")
async def test_statistics_rebuild_end_to_end(
    hass: HomeAssistant, recorder_mock: Recorder
) -> None:
    store = Store()
    history = FitageHistoryManager(None, "runtime-entry", store=store)
    history.load_for_test(payload())
    importer = FitageStatisticsImporter(hass, "runtime-entry", history, enabled=True)
    history.configure_statistics(frozenset({"weight"}))

    await importer.async_reconcile()
    await async_wait_recording_done(hass)

    stat_a = statistic_id("runtime-entry", "runtime-profile-a", "weight")
    stat_b = statistic_id("runtime-entry", "runtime-profile-b", "weight")
    start = datetime(2025, 1, 1, tzinfo=UTC)
    stats = statistics_during_period(
        hass,
        start,
        None,
        {stat_a, stat_b},
        "hour",
        None,
        {"state", "sum"},
    )
    assert [point["state"] for point in stats[stat_a]] == [61.0]
    assert [point["state"] for point in stats[stat_b]] == [80.0]
    assert all(point["sum"] is None for values in stats.values() for point in values)

    await importer.async_reconcile()
    await async_wait_recording_done(hass)
    unchanged = statistics_during_period(
        hass,
        start,
        None,
        {stat_a, stat_b},
        "hour",
        None,
        {"state", "sum"},
    )
    assert unchanged == stats

    changed = history.data
    changed["profiles"]["runtime-profile-a"]["measurements"].pop("b")
    history.load_for_test(changed)
    await history.async_prepare_statistics()
    await importer.async_reconcile()
    await async_wait_recording_done(hass)
    stats = statistics_during_period(
        hass,
        start,
        None,
        {stat_a, stat_b},
        "hour",
        None,
        {"state", "sum"},
    )
    assert [point["state"] for point in stats[stat_a]] == [60.0]
    assert [point["state"] for point in stats[stat_b]] == [80.0]

    changed = history.data
    changed["profiles"]["runtime-profile-a"]["measurements"].clear()
    history.load_for_test(changed)
    await history.async_prepare_statistics()
    await importer.async_reconcile()
    await async_wait_recording_done(hass)
    stats = statistics_during_period(
        hass,
        start,
        None,
        {stat_a, stat_b},
        "hour",
        None,
        {"state", "sum"},
    )
    assert stat_a not in stats
    assert [point["state"] for point in stats[stat_b]] == [80.0]
    assert history.data["profiles"]["runtime-profile-a"]["measurements"] == {}
