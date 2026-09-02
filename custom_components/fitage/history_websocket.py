"""Read-only websocket presentation for stored FITAGE history."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .history import FitageHistoryManager

COMMAND_PROFILES = "fitage/history/profiles"
COMMAND_QUERY = "fitage/history/query"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
_DATA_REGISTERED = "history_websocket_registered"
_DATA_CURSOR_KEY = "history_websocket_cursor_key"

ALLOWED_METRICS = frozenset(
    {
        "weight",
        "bmi",
        "bodyfat",
        "water",
        "muscle",
        "sinew",
        "bone",
        "protein",
        "subfat",
        "visfat",
        "fat_free_weight",
        "body_fat_mass",
        "body_water_mass",
        "protein_mass",
        "bmr",
        "bodyage",
        "score",
        "body_shape",
        "heart_rate",
        "cardiac_index",
        "bodyfat_left_arm",
        "bodyfat_right_arm",
        "bodyfat_trunk",
        "bodyfat_left_leg",
        "bodyfat_right_leg",
    }
)


def _unique_metrics(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise vol.Invalid("metrics must be unique")
    return value


PROFILES_SCHEMA = {
    vol.Required("type"): COMMAND_PROFILES,
    vol.Required("config_entry_id"): cv.string,
}
QUERY_SCHEMA = {
    vol.Required("type"): COMMAND_QUERY,
    vol.Required("config_entry_id"): cv.string,
    vol.Required("profile_ref"): cv.string,
    vol.Optional("start_time"): vol.Coerce(float),
    vol.Optional("end_time"): vol.Coerce(float),
    vol.Required("metrics"): vol.All([vol.In(ALLOWED_METRICS)], _unique_metrics),
    vol.Optional("limit", default=DEFAULT_LIMIT): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
    ),
    vol.Optional("cursor"): cv.string,
    vol.Optional("sort", default="ascending"): vol.In(("ascending", "descending")),
}


class HistoryWebsocketError(ValueError):
    """Safe client-facing history query error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    data = (hass.data.get(DOMAIN) or {}).get(entry_id)
    if not isinstance(data, dict):
        raise HistoryWebsocketError("entry_not_found", "FITAGE entry is not loaded")
    manager = data.get("history")
    if not isinstance(manager, FitageHistoryManager) or not manager.is_loaded:
        raise HistoryWebsocketError(
            "history_unavailable", "FITAGE history is unavailable"
        )
    return data


def _profile_ref(entry_id: str, user_id: str) -> str:
    digest = hashlib.sha256(f"{entry_id}\0{user_id}".encode()).hexdigest()
    return f"profile_{digest[:24]}"


def _profile_names(entry_data: Mapping[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for profile in entry_data.get("profiles") or []:
        if not isinstance(profile, Mapping):
            continue
        user_info = profile.get("user_info")
        if not isinstance(user_info, Mapping) or user_info.get("user_id") in (None, ""):
            continue
        name = user_info.get("account_name") or user_info.get("nickname")
        if name not in (None, ""):
            names[str(user_info["user_id"])] = str(name)
    return names


def list_profiles(entry_id: str, entry_data: dict[str, Any]) -> dict[str, Any]:
    """Return privacy-filtered descriptors from an in-memory snapshot."""
    manager = entry_data["history"]
    profiles = manager.data["profiles"]
    names = _profile_names(entry_data)
    result: list[dict[str, Any]] = []
    for index, (user_id, bucket) in enumerate(profiles.items(), 1):
        records = list(bucket["measurements"].values())
        ordered = sorted(records, key=lambda record: float(record["time_stamp"]))
        metrics = sorted(
            metric
            for metric in ALLOWED_METRICS
            if any(metric in record for record in records)
        )
        result.append(
            {
                "profile_ref": _profile_ref(entry_id, user_id),
                "display_name": names.get(user_id, f"FITAGE profile {index}"),
                "record_count": len(records),
                "oldest_timestamp": ordered[0]["time_stamp"] if ordered else None,
                "newest_timestamp": ordered[-1]["time_stamp"] if ordered else None,
                "available_metrics": metrics,
            }
        )
    return {"profiles": result}


def _query_binding(msg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry": msg["config_entry_id"],
        "profile": msg["profile_ref"],
        "start": msg.get("start_time"),
        "end": msg.get("end_time"),
        "metrics": sorted(msg["metrics"]),
        "sort": msg["sort"],
    }


def _encode_cursor(key: bytes, binding: Mapping[str, Any], offset: int) -> str:
    payload = json.dumps(
        {"query": binding, "offset": offset}, separators=(",", ":"), sort_keys=True
    ).encode()
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")


def _decode_cursor(key: bytes, cursor: str, binding: Mapping[str, Any]) -> int:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4)
        value = base64.urlsafe_b64decode(encoded.encode())
        signature, payload = value[:32], value[32:]
        if len(signature) != 32 or not hmac.compare_digest(
            signature, hmac.new(key, payload, hashlib.sha256).digest()
        ):
            raise ValueError
        decoded = json.loads(payload)
        if decoded.get("query") != binding:
            raise ValueError
        offset = decoded.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as err:
        raise HistoryWebsocketError(
            "invalid_cursor", "Pagination cursor is invalid"
        ) from err


def query_history(
    entry_data: dict[str, Any], msg: Mapping[str, Any], cursor_key: bytes
) -> dict[str, Any]:
    """Query exactly one profile without exposing its internal identity."""
    binding = _query_binding(msg)
    offset = (
        _decode_cursor(cursor_key, msg["cursor"], binding)
        if msg.get("cursor") is not None
        else 0
    )
    manager = entry_data["history"]
    profiles = manager.data["profiles"]
    matches = [
        (user_id, bucket)
        for user_id, bucket in profiles.items()
        if _profile_ref(msg["config_entry_id"], user_id) == msg["profile_ref"]
    ]
    if len(matches) != 1:
        raise HistoryWebsocketError(
            "profile_not_found", "FITAGE profile is unavailable"
        )
    _, bucket = matches[0]
    records = list(bucket["measurements"].values())
    start = msg.get("start_time")
    end = msg.get("end_time")
    if start is not None and end is not None and start > end:
        raise HistoryWebsocketError(
            "invalid_range", "start_time must not exceed end_time"
        )
    filtered = [
        record
        for record in records
        if (start is None or float(record["time_stamp"]) >= start)
        and (end is None or float(record["time_stamp"]) <= end)
    ]
    reverse = msg["sort"] == "descending"
    filtered.sort(
        key=lambda record: (float(record["time_stamp"]), str(record["measurement_id"])),
        reverse=reverse,
    )
    if offset > len(filtered):
        raise HistoryWebsocketError("invalid_cursor", "Pagination cursor is invalid")
    page = filtered[offset : offset + msg["limit"]]
    metrics = msg["metrics"]
    response_records = [
        {
            "timestamp": record["time_stamp"],
            "metrics": {
                metric: record[metric] for metric in metrics if metric in record
            },
        }
        for record in page
    ]
    next_offset = offset + len(page)
    next_cursor = (
        _encode_cursor(cursor_key, binding, next_offset)
        if next_offset < len(filtered)
        else None
    )
    return {"records": response_records, "next_cursor": next_cursor}


def _send_error(
    connection: websocket_api.ActiveConnection, msg_id: int, err: HistoryWebsocketError
) -> None:
    connection.send_error(msg_id, err.code, str(err))


@callback
@websocket_api.require_admin
@websocket_api.websocket_command(PROFILES_SCHEMA)
def websocket_history_profiles(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List locally addressable profiles for one loaded config entry."""
    try:
        result = list_profiles(
            msg["config_entry_id"], _entry_data(hass, msg["config_entry_id"])
        )
    except HistoryWebsocketError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@callback
@websocket_api.require_admin
@websocket_api.websocket_command(QUERY_SCHEMA)
def websocket_history_query(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one bounded page from one local profile."""
    try:
        entry_data = _entry_data(hass, msg["config_entry_id"])
        result = query_history(entry_data, msg, hass.data[DOMAIN][_DATA_CURSOR_KEY])
    except HistoryWebsocketError as err:
        _send_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@callback
def async_register_history_websocket(hass: HomeAssistant) -> None:
    """Register domain commands once; handlers resolve live entries per call."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_REGISTERED):
        return
    domain_data[_DATA_CURSOR_KEY] = secrets.token_bytes(32)
    websocket_api.async_register_command(hass, websocket_history_profiles)
    websocket_api.async_register_command(hass, websocket_history_query)
    domain_data[_DATA_REGISTERED] = True
