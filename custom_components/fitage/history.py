"""Durable, profile-isolated FITAGE measurement history."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .measurement import MASS_PERCENTAGE_KEYS, effective_mass_value

HISTORY_STORE_VERSION = 1
HISTORY_STORE_KEY_PREFIX = "fitage.history"
MAX_HISTORY_PAGES = 10
STATISTICS_PROJECTION_VERSION = 2


class HistorySchemaError(ValueError):
    """A history response did not match the proven server contract."""


class HistorySyncError(RuntimeError):
    """A history request failed without exposing server details."""


@dataclass(frozen=True, slots=True)
class HistoryPage:
    """One fully validated server history page."""

    measurements: tuple[dict[str, Any], ...]
    delete_measurement_ids: tuple[str, ...]
    last_updated_at: int
    last_measurement_id: str
    finish: bool
    fingerprint: str

    @property
    def cursor(self) -> tuple[int, str]:
        """Return the page cursor."""
        return self.last_updated_at, self.last_measurement_id

    @property
    def upserts(self) -> dict[str, dict[str, Any]]:
        """Deduplicate records by measurement ID; the last occurrence wins."""
        return {
            str(record["measurement_id"]): deepcopy(record)
            for record in self.measurements
        }

    @classmethod
    def parse(cls, raw: Any, requested_user_id: str) -> HistoryPage:
        """Parse and validate a page without exposing identifiers in errors."""
        if not isinstance(raw, dict):
            raise HistorySchemaError("Unexpected FITAGE history response shape")

        measurements = raw.get("measurements")
        deletes = raw.get("delete_measurement_ids")
        updated = raw.get("last_updated_at")
        measurement_cursor = raw.get("last_measurement_id")
        finish_flag = raw.get("finish_flag")
        if (
            not isinstance(measurements, list)
            or not isinstance(deletes, list)
            or isinstance(updated, bool)
            or not isinstance(updated, int)
            or not isinstance(measurement_cursor, str)
            or not measurement_cursor
            or isinstance(finish_flag, bool)
            or not isinstance(finish_flag, int)
            or finish_flag not in (0, 1)
            or any(not isinstance(item, str) or not item for item in deletes)
        ):
            raise HistorySchemaError("Unexpected FITAGE history response shape")

        validated: list[dict[str, Any]] = []
        for record in measurements:
            if not isinstance(record, dict):
                raise HistorySchemaError("Unexpected FITAGE history record shape")
            measurement_id = record.get("measurement_id")
            record_user_id = record.get("user_id")
            timestamp = record.get("time_stamp")
            if (
                not isinstance(measurement_id, str)
                or not measurement_id
                or not isinstance(record_user_id, str)
                or record_user_id != requested_user_id
                or not _valid_timestamp(timestamp)
            ):
                raise HistorySchemaError("Unexpected FITAGE history record shape")
            validated.append(deepcopy(record))

        fingerprint_payload = {
            "measurements": validated,
            "delete_measurement_ids": deletes,
        }
        try:
            encoded = json.dumps(
                fingerprint_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        except (TypeError, ValueError) as err:
            raise HistorySchemaError("Unexpected FITAGE history record value") from err

        return cls(
            measurements=tuple(validated),
            delete_measurement_ids=tuple(deletes),
            last_updated_at=updated,
            last_measurement_id=measurement_cursor,
            finish=finish_flag == 1,
            fingerprint=hashlib.sha256(encoded).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class HistorySyncResult:
    """Non-sensitive result of one profile sync cycle."""

    pages_processed: int
    end_reason: str


def _valid_timestamp(value: Any) -> bool:
    """Return whether a timestamp can be ordered deterministically."""
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _empty_data() -> dict[str, Any]:
    """Return a new empty Store payload."""
    return {"profiles": {}}


def _empty_profile() -> dict[str, Any]:
    """Return a new profile history payload."""
    return {
        "cursor": {"last_updated_at": 0, "last_measurement_id": "0"},
        "measurements": {},
        "sync": {"complete": False},
        "statistics": {
            "version": STATISTICS_PROJECTION_VERSION,
            "fingerprints": {},
            "pending_rebuilds": [],
            "imported_metrics": [],
        },
    }


class FitageHistoryManager:
    """Own one private versioned history Store for a config entry."""

    def __init__(
        self,
        hass: HomeAssistant | None,
        entry_id: str,
        *,
        store: Any | None = None,
    ) -> None:
        """Initialize the manager without doing I/O."""
        self.store_key = f"{HISTORY_STORE_KEY_PREFIX}_{entry_id}"
        self._store = store or Store(
            hass,
            HISTORY_STORE_VERSION,
            self.store_key,
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        self._data: dict[str, Any] = _empty_data()
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._loaded = False
        self._sync_status: dict[str, dict[str, Any]] = {}
        self._statistics_metrics: frozenset[str] = frozenset()

    @property
    def is_loaded(self) -> bool:
        """Return whether Store loading completed successfully."""
        return self._loaded

    @property
    def data(self) -> dict[str, Any]:
        """Return a defensive snapshot for diagnostics and tests."""
        return deepcopy(self._data)

    async def async_load(self) -> None:
        """Load and validate the Store payload."""
        stored = await self._store.async_load()
        if stored is None:
            self._data = _empty_data()
            self._loaded = True
            return
        self._data = _validate_stored_data(stored)
        self._loaded = True

    def load_for_test(self, data: dict[str, Any]) -> None:
        """Load validated data synchronously for pure selection tests."""
        self._data = _validate_stored_data(deepcopy(data))
        self._loaded = True

    def configure_statistics(self, metrics: frozenset[str]) -> None:
        """Configure metrics whose raw projection changes must be reconciled."""
        self._statistics_metrics = metrics

    def pending_statistics_rebuilds(self) -> list[tuple[str, str]]:
        """Return pending profile/metric pairs without exposing them externally."""
        return [
            (user_id, metric)
            for user_id, profile in self._data["profiles"].items()
            for metric in profile["statistics"]["pending_rebuilds"]
        ]

    def statistics_may_exist(self) -> bool:
        """Return whether Recorder may contain statistics derived from this Store."""
        return any(
            profile["statistics"]["imported_metrics"]
            for profile in self._data["profiles"].values()
        )

    def imported_statistics(self) -> list[tuple[str, str]]:
        """Return profile/metric pairs whose Recorder series may contain data."""
        return [
            (user_id, metric)
            for user_id, profile in self._data["profiles"].items()
            for metric in profile["statistics"]["imported_metrics"]
        ]

    async def async_prepare_statistics(self) -> None:
        """Persist missing or changed projection work before Recorder writes."""
        next_data = deepcopy(self._data)
        changed = False
        for profile in next_data["profiles"].values():
            statistics = profile["statistics"]
            pending = set(statistics["pending_rebuilds"])
            for metric in self._statistics_metrics:
                fingerprint = _statistics_fingerprint(profile["measurements"], metric)
                if fingerprint != statistics["fingerprints"].get(metric):
                    pending.add(metric)
            ordered = sorted(pending)
            changed |= ordered != statistics["pending_rebuilds"]
            statistics["pending_rebuilds"] = ordered
        if changed:
            await self._store.async_save(next_data)
            self._data = next_data

    async def async_mark_statistics_scheduled(
        self, user_id: str, metric: str, fingerprint: str
    ) -> None:
        """Persist completion only after clear completed and import was queued."""
        next_data = deepcopy(self._data)
        profile = next_data["profiles"].get(user_id)
        if profile is None:
            return
        statistics = profile["statistics"]
        statistics["fingerprints"][metric] = fingerprint
        imported_metrics = set(statistics["imported_metrics"])
        if _statistics_has_data(profile["measurements"], metric):
            imported_metrics.add(metric)
        else:
            imported_metrics.discard(metric)
        statistics["imported_metrics"] = sorted(imported_metrics)
        statistics["pending_rebuilds"] = [
            item for item in statistics["pending_rebuilds"] if item != metric
        ]
        await self._store.async_save(next_data)
        self._data = next_data

    def statistics_fingerprint(self, user_id: str, metric: str) -> str:
        """Return the current deterministic derived-projection fingerprint."""
        return _statistics_fingerprint(self.measurements(user_id), metric)

    def sync_status(self, user_id: str) -> dict[str, Any]:
        """Return privacy-safe transient metadata for the last sync attempt."""
        return deepcopy(
            self._sync_status.get(
                user_id,
                {
                    "end_reason": "not_run",
                    "pages_processed": 0,
                    "started_from_stored_cursor": False,
                    "delete_ids_received": 0,
                    "delete_ids_applied": 0,
                    "delete_ids_unknown": 0,
                },
            )
        )

    def cursor(self, user_id: str) -> tuple[int, str]:
        """Return only this profile's stored cursor, or the initial cursor."""
        profile = self._data["profiles"].get(user_id)
        if not profile:
            return 0, "0"
        cursor = profile["cursor"]
        return cursor["last_updated_at"], cursor["last_measurement_id"]

    def profile_ids(self) -> tuple[str, ...]:
        """Return internal profile bucket identities for lifecycle cleanup."""
        return tuple(self._data["profiles"])

    async def async_remove_store(self) -> None:
        """Remove this config entry's private Store through the Store API."""
        await self._store.async_remove()
        self._data = _empty_data()
        self._loaded = False

    def measurements(self, user_id: str) -> dict[str, dict[str, Any]]:
        """Return a defensive copy of one profile's records."""
        profile = self._data["profiles"].get(user_id)
        if not profile:
            return {}
        return deepcopy(profile["measurements"])

    def latest_measurement(self, user_id: str) -> dict[str, Any] | None:
        """Select newest by timestamp and measurement ID, never response order."""
        records = self.measurements(user_id)
        if not records:
            return None
        return max(
            records.values(),
            key=lambda record: (
                float(record["time_stamp"]),
                str(record["measurement_id"]),
            ),
        )

    async def async_sync_profile(self, api: Any, user_id: str) -> HistorySyncResult:
        """Synchronize at most ten pages for exactly one profile."""
        lock = self._profile_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            started_from_stored_cursor = user_id in self._data["profiles"]
            cursor = self.cursor(user_id)
            seen_cursors = {cursor}
            seen_pages: set[str] = set()
            pages_processed = 0
            delete_ids_received = 0
            delete_ids_applied = 0
            delete_ids_unknown = 0

            def finish(end_reason: str) -> HistorySyncResult:
                self._sync_status[user_id] = {
                    "end_reason": end_reason,
                    "pages_processed": pages_processed,
                    "started_from_stored_cursor": started_from_stored_cursor,
                    "delete_ids_received": delete_ids_received,
                    "delete_ids_applied": delete_ids_applied,
                    "delete_ids_unknown": delete_ids_unknown,
                }
                return HistorySyncResult(pages_processed, end_reason)

            for page_number in range(1, MAX_HISTORY_PAGES + 1):
                try:
                    raw = await api.async_get_measurements_history_page(
                        user_id,
                        last_updated_at=cursor[0],
                        last_measurement_id=cursor[1],
                    )
                except Exception:  # noqa: BLE001 -- redact every API failure.
                    finish("api_error")
                    raise HistorySyncError(
                        "FITAGE history synchronization request failed"
                    ) from None

                try:
                    page = HistoryPage.parse(raw, user_id)
                except HistorySchemaError:
                    finish("schema_error")
                    raise
                del raw
                if page.fingerprint in seen_pages:
                    return finish("repeated_page")
                if not page.finish and page.cursor == cursor:
                    return finish("stalled_cursor")
                if not page.finish and page.cursor in seen_cursors:
                    return finish("repeated_cursor")

                applied, unknown = await self._async_commit_page(user_id, page)
                pages_processed += 1
                delete_ids_received += len(page.delete_measurement_ids)
                delete_ids_applied += applied
                delete_ids_unknown += unknown
                cursor = page.cursor
                if page.finish:
                    return finish("finish_flag")
                if page_number == MAX_HISTORY_PAGES:
                    return finish("page_limit")
                seen_pages.add(page.fingerprint)
                seen_cursors.add(cursor)

            return finish("page_limit")

    async def _async_commit_page(
        self, user_id: str, page: HistoryPage
    ) -> tuple[int, int]:
        """Persist records, deletes and cursor as one Store snapshot."""
        next_data = deepcopy(self._data)
        profile = next_data["profiles"].setdefault(user_id, _empty_profile())
        records = profile["measurements"]
        before_fingerprints = {
            metric: _statistics_fingerprint(records, metric)
            for metric in self._statistics_metrics
        }
        records.update(page.upserts)
        delete_ids = set(page.delete_measurement_ids)
        applied = sum(measurement_id in records for measurement_id in delete_ids)
        for measurement_id in delete_ids:
            records.pop(measurement_id, None)
        profile["cursor"] = {
            "last_updated_at": page.last_updated_at,
            "last_measurement_id": page.last_measurement_id,
        }
        profile["sync"] = {"complete": page.finish}
        pending = set(profile["statistics"]["pending_rebuilds"])
        for metric, before in before_fingerprints.items():
            if _statistics_fingerprint(records, metric) != before:
                pending.add(metric)
        profile["statistics"]["pending_rebuilds"] = sorted(pending)
        await self._store.async_save(next_data)
        self._data = next_data
        return applied, len(delete_ids) - applied


def _validate_stored_data(stored: Any) -> dict[str, Any]:
    """Validate the version-1 payload before it becomes runtime state."""
    if not isinstance(stored, dict) or not isinstance(stored.get("profiles"), dict):
        raise HistorySchemaError("Invalid FITAGE history Store payload")
    result = _empty_data()
    for user_id, profile in stored["profiles"].items():
        if not isinstance(user_id, str) or not isinstance(profile, dict):
            raise HistorySchemaError("Invalid FITAGE history Store profile")
        cursor = profile.get("cursor")
        measurements = profile.get("measurements")
        sync = profile.get("sync")
        if (
            not isinstance(cursor, dict)
            or isinstance(cursor.get("last_updated_at"), bool)
            or not isinstance(cursor.get("last_updated_at"), int)
            or not isinstance(cursor.get("last_measurement_id"), str)
            or not isinstance(measurements, dict)
            or not isinstance(sync, dict)
            or not isinstance(sync.get("complete"), bool)
        ):
            raise HistorySchemaError("Invalid FITAGE history Store profile")
        validated_records: dict[str, dict[str, Any]] = {}
        for measurement_id, record in measurements.items():
            if (
                not isinstance(measurement_id, str)
                or not isinstance(record, dict)
                or str(record.get("measurement_id")) != measurement_id
                or str(record.get("user_id")) != user_id
                or not _valid_timestamp(record.get("time_stamp"))
            ):
                raise HistorySchemaError("Invalid FITAGE history Store record")
            validated_records[measurement_id] = deepcopy(record)
        stored_statistics = profile.get("statistics")
        statistics = stored_statistics or {
            "version": STATISTICS_PROJECTION_VERSION,
            "fingerprints": {},
            "pending_rebuilds": [],
            "imported_metrics": [],
        }
        imported_metrics = statistics.get("imported_metrics")
        if imported_metrics is None:
            # Stores written by an earlier v1.4 release candidate did not track
            # this explicitly. Successful fingerprints mean statistics may exist.
            imported_metrics = list(statistics.get("fingerprints", {}))
        if (
            not isinstance(statistics, dict)
            or statistics.get("version") not in (1, STATISTICS_PROJECTION_VERSION)
            or not isinstance(statistics.get("fingerprints"), dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in statistics["fingerprints"].items()
            )
            or not isinstance(statistics.get("pending_rebuilds"), list)
            or not all(isinstance(item, str) for item in statistics["pending_rebuilds"])
            or not isinstance(imported_metrics, list)
            or not all(isinstance(item, str) for item in imported_metrics)
        ):
            raise HistorySchemaError("Invalid FITAGE history statistics metadata")
        statistics = deepcopy(statistics)
        statistics["imported_metrics"] = sorted(set(imported_metrics))
        if stored_statistics is not None and statistics["version"] == 1:
            # Projection v2 resolves FITAGE zero sentinels for these masses.
            statistics["version"] = STATISTICS_PROJECTION_VERSION
            statistics["pending_rebuilds"] = sorted(
                set(statistics["pending_rebuilds"]) | set(MASS_PERCENTAGE_KEYS)
            )
        result["profiles"][user_id] = {
            "cursor": deepcopy(cursor),
            "measurements": validated_records,
            "sync": {"complete": sync["complete"]},
            "statistics": deepcopy(statistics),
        }
    return result


def _statistics_fingerprint(records: dict[str, dict[str, Any]], metric: str) -> str:
    """Hash only the deterministic hourly projection for one metric."""
    projected: list[tuple[int, float, str, float]] = []
    for record in records.values():
        try:
            timestamp = float(record["time_stamp"])
        except (TypeError, ValueError):
            continue
        if metric in MASS_PERCENTAGE_KEYS:
            value = effective_mass_value(record, metric)
            if value is None:
                continue
        else:
            if metric not in record or isinstance(record[metric], bool):
                continue
            try:
                value = float(record[metric])
            except (TypeError, ValueError):
                continue
        if not math.isfinite(value):
            continue
        projected.append(
            (int(timestamp // 3600), timestamp, str(record["measurement_id"]), value)
        )
    return hashlib.sha256(
        json.dumps(sorted(projected), separators=(",", ":")).encode()
    ).hexdigest()


def _statistics_has_data(records: dict[str, dict[str, Any]], metric: str) -> bool:
    """Return whether a metric has at least one valid projected value."""
    for record in records.values():
        try:
            timestamp = float(record["time_stamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if metric in MASS_PERCENTAGE_KEYS:
            value = effective_mass_value(record, metric)
            if value is None:
                continue
        else:
            if metric not in record or isinstance(record[metric], bool):
                continue
            try:
                value = float(record[metric])
            except (TypeError, ValueError):
                continue
        if math.isfinite(timestamp) and math.isfinite(value):
            return True
    return False
