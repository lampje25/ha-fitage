"""Optional derived external statistics for FITAGE raw history."""

from __future__ import annotations

import asyncio
import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import DATA_INSTANCE

from .const import DOMAIN
from .history import FitageHistoryManager

_CLEAR_TIMEOUT = 30


class StatisticsCleanupError(RuntimeError):
    """Recorder cleanup did not complete with certainty."""


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Recorder metadata for one proven numeric FITAGE measurement."""

    name: str
    unit: str | None
    unit_class: str | None


STATISTIC_METRICS: dict[str, MetricDefinition] = {
    "weight": MetricDefinition("Weight", "kg", "mass"),
    "bmi": MetricDefinition("BMI", None, "unitless"),
    "bodyfat": MetricDefinition("Body fat", "%", "unitless"),
    "water": MetricDefinition("Body water", "%", "unitless"),
    "muscle": MetricDefinition("Muscle", "%", "unitless"),
    "bone": MetricDefinition("Bone mass", "kg", "mass"),
    "protein": MetricDefinition("Protein", "%", "unitless"),
    "subfat": MetricDefinition("Subcutaneous fat", "%", "unitless"),
    "fat_free_weight": MetricDefinition("Fat-free weight", "kg", "mass"),
    "body_fat_mass": MetricDefinition("Body fat mass", "kg", "mass"),
    "body_water_mass": MetricDefinition("Body water mass", "kg", "mass"),
    "protein_mass": MetricDefinition("Protein mass", "kg", "mass"),
    "bmr": MetricDefinition("Basal metabolic rate", "kcal", "energy"),
    "score": MetricDefinition("Score", None, "unitless"),
    "heart_rate": MetricDefinition("Heart rate", "bpm", None),
}


def statistic_id(entry_id: str, user_id: str, metric: str) -> str:
    """Build a stable local ID without exposing the profile identity."""
    entry_ref = hashlib.sha256(entry_id.encode()).hexdigest()[:10]
    profile_ref = hashlib.sha256(f"{entry_id}\0{user_id}".encode()).hexdigest()[:12]
    return f"{DOMAIN}:{entry_ref}_{profile_ref}_{metric}"


def hourly_statistics(
    records: dict[str, dict[str, Any]], metric: str
) -> list[StatisticData]:
    """Select one deterministic last measurement per UTC hour."""
    winners: dict[int, dict[str, Any]] = {}
    for record in records.values():
        if metric not in record or isinstance(record[metric], bool):
            continue
        try:
            timestamp = float(record["time_stamp"])
            value = float(record[metric])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(timestamp) or not math.isfinite(value):
            continue
        hour = int(timestamp // 3600)
        current = winners.get(hour)
        if current is None or (
            timestamp,
            str(record["measurement_id"]),
        ) > (
            float(current["time_stamp"]),
            str(current["measurement_id"]),
        ):
            winners[hour] = record
    return [
        StatisticData(
            start=datetime.fromtimestamp(hour * 3600, UTC),
            state=float(winners[hour][metric]),
        )
        for hour in sorted(winners)
    ]


class FitageStatisticsImporter:
    """Reconcile rebuildable Recorder projections from canonical raw history."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        history: FitageHistoryManager,
        *,
        enabled: bool,
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._history = history
        self.enabled = enabled
        self._lock = asyncio.Lock()
        self._profile_names: dict[str, str] = {}
        history.configure_statistics(frozenset(STATISTIC_METRICS))

    def configure_profile_names(self, profiles: list[dict[str, Any]]) -> None:
        """Set privacy-safe presentation names for the current profile snapshot."""
        candidates: dict[str, str] = {}
        for profile in profiles:
            user_id = profile.get("user_id")
            display_name = profile.get("account_name") or profile.get("nickname")
            if user_id in (None, "") or display_name in (None, ""):
                continue
            normalized = str(display_name).strip()
            if normalized:
                candidates[str(user_id)] = normalized

        collision_groups: dict[str, list[str]] = {}
        for user_id, display_name in candidates.items():
            collision_groups.setdefault(display_name.casefold(), []).append(user_id)

        collision_refs: dict[str, str] = {}
        for user_ids in collision_groups.values():
            if len(user_ids) < 2:
                continue
            digests = {
                user_id: hashlib.sha256(
                    f"{self._entry_id}\0{user_id}".encode()
                ).hexdigest()
                for user_id in user_ids
            }
            length = 4
            while len({digest[:length] for digest in digests.values()}) < len(digests):
                length += 1
            collision_refs.update(
                {user_id: digest[:length] for user_id, digest in digests.items()}
            )

        self._profile_names = {
            user_id: (
                f"{display_name} ({collision_refs[user_id]})"
                if user_id in collision_refs
                else display_name
            )
            for user_id, display_name in candidates.items()
        }

    def _metadata(self, user_id: str, metric: str) -> StatisticMetaData:
        """Build presentation metadata without changing the technical identity."""
        definition = STATISTIC_METRICS[metric]
        display_name = self._profile_names.get(user_id, "Profile")
        return StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"FITAGE {display_name} – {definition.name}",
            source=DOMAIN,
            statistic_id=statistic_id(self._entry_id, user_id, metric),
            unit_class=definition.unit_class,
            unit_of_measurement=definition.unit,
        )

    async def async_reconcile(self) -> None:
        """Rebuild changed projections and idempotently upsert visible metadata."""
        if not self.enabled:
            return
        async with self._lock:
            await self._history.async_prepare_statistics()
            rebuilt: set[tuple[str, str]] = set()
            for user_id, metric in self._history.pending_statistics_rebuilds():
                if not self.enabled:
                    return
                await self._async_rebuild(user_id, metric)
                rebuilt.add((user_id, metric))

            for user_id, metric in self._history.imported_statistics():
                if user_id in self._profile_names and (user_id, metric) not in rebuilt:
                    async_add_external_statistics(
                        self._hass, self._metadata(user_id, metric), []
                    )

    async def _async_rebuild(self, user_id: str, metric: str) -> None:
        stat_id = statistic_id(self._entry_id, user_id, metric)
        cleared = asyncio.Event()

        def clear_done() -> None:
            self._hass.loop.call_soon_threadsafe(cleared.set)

        get_instance(self._hass).async_clear_statistics([stat_id], on_done=clear_done)
        async with asyncio.timeout(_CLEAR_TIMEOUT):
            await cleared.wait()

        records = self._history.measurements(user_id)
        statistics = hourly_statistics(records, metric)
        if statistics:
            async_add_external_statistics(
                self._hass, self._metadata(user_id, metric), statistics
            )

        await self._history.async_mark_statistics_scheduled(
            user_id,
            metric,
            self._history.statistics_fingerprint(user_id, metric),
        )


async def async_clear_entry_statistics(
    hass: HomeAssistant, entry_id: str, user_ids: set[str]
) -> None:
    """Clear only statistics owned by one removed FITAGE config entry."""
    if not user_ids:
        return
    if DATA_INSTANCE not in hass.data:
        raise StatisticsCleanupError("FITAGE statistics cleanup could not complete")
    statistic_ids = [
        statistic_id(entry_id, user_id, metric)
        for user_id in sorted(user_ids)
        for metric in sorted(STATISTIC_METRICS)
    ]
    cleared = asyncio.Event()

    def clear_done() -> None:
        hass.loop.call_soon_threadsafe(cleared.set)

    try:
        get_instance(hass).async_clear_statistics(statistic_ids, on_done=clear_done)
        async with asyncio.timeout(_CLEAR_TIMEOUT):
            await cleared.wait()
    except Exception as err:
        raise StatisticsCleanupError(
            "FITAGE statistics cleanup could not complete"
        ) from err
