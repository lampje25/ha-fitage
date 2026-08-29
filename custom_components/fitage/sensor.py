"""Sensor platform for FITAGE — coordinator-backed entities (auto-refresh)."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER, SCAN_INTERVAL

_LOGGER = logging.getLogger(LOGGER)

try:
    from homeassistant.const import UnitOfMass

    KG_UNIT = UnitOfMass.KILOGRAMS
except ImportError:
    KG_UNIT = "kg"

PERCENT = "%"
KCAL = "kcal"
BPM = "bpm"

_BODY_SHAPES = {
    1: "invisible_obesity",
    2: "hypokinetic",
    3: "lean",
    4: "normal",
    5: "lean_muscular",
    6: "obese_type",
    7: "overweight",
    8: "standard_muscular",
    9: "very_muscular",
}
_ASIA_AREA_CODES = {"CN", "JP", "HK", "TW", "MO", "KR"}
_CALCULATED_MEASUREMENT_KEYS = {
    "muscle_ratio",
    "bone_ratio",
    "muscle_storage_capacity",
    "body_shape",
    "muscle_control",
    "fat_control",
    "weight_control",
    "recommended_weight",
}


def _as_finite_float(value: Any) -> float | None:
    """Convert a numeric value to a finite float."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_int(value: Any) -> int | None:
    """Convert a finite integral number without accepting booleans."""
    number = _as_finite_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _fitage_round(value: float, digits: int = 2) -> float:
    """Round like the FITAGE report calculator."""
    factor = 10**digits
    rounded = math.floor(abs(value) * factor + 0.5) / factor
    return -rounded if value < 0 and rounded else rounded


def _fitage_standard_type(
    measurement: dict[str, Any], user_info: dict[str, Any]
) -> str:
    """Select the FITAGE body-composition standard from the account region."""
    area_code = next(
        (
            value
            for value in (
                measurement.get("register_area_code"),
                measurement.get("area_code"),
                user_info.get("register_area_code"),
                user_info.get("area_code"),
                user_info.get("country"),
            )
            if isinstance(value, str) and value.strip()
        ),
        "NL",
    )
    return "asia" if area_code.strip().upper() in _ASIA_AREA_CODES else "occident"


def _fitage_bodyfat_target(gender: int, standard_type: str) -> float:
    """Return the FITAGE target body-fat percentage for normal measurements."""
    if standard_type == "asia":
        boundaries = (11.0, 21.0) if gender == 1 else (21.0, 31.0)
    else:
        boundaries = (13.0, 17.0) if gender == 1 else (21.0, 25.0)
    return sum(boundaries) / 2


def _fitage_lean_target_ratio(gender: int, weight: float, standard_type: str) -> float:
    """Return the FITAGE target lean-component ratio for normal measurements."""
    protein = (16.0, 18.0) if gender == 1 else (14.0, 16.0)
    if standard_type == "asia":
        water = (55.0, 65.0) if gender == 1 else (45.0, 60.0)
        if gender == 1:
            bone = (
                (2.3, 2.7)
                if weight <= 60
                else ((2.7, 3.1) if weight < 75 else (3.0, 3.4))
            )
        else:
            bone = (
                (1.6, 2.0)
                if weight <= 45
                else ((2.0, 2.4) if weight < 60 else (2.3, 2.7))
            )
    else:
        water = (50.0, 65.0) if gender == 1 else (45.0, 60.0)
        bone = (3.0, 5.0) if gender == 1 else (2.5, 4.0)
    return sum((*bone, *protein, *water)) / 2


def _calculate_fitage_metrics(
    measurement: dict[str, Any], user_info: dict[str, Any] | None = None
) -> dict[str, int | float | str | None]:
    """Calculate the report values reproduced from the FITAGE Android app."""
    result: dict[str, int | float | str | None] = {
        key: None for key in _CALCULATED_MEASUREMENT_KEYS
    }
    user_info = user_info or {}
    weight = _as_finite_float(measurement.get("weight"))
    gender = _as_int(measurement.get("gender"))
    if gender not in (0, 1):
        gender = _as_int(user_info.get("gender"))

    if weight is not None and weight > 0:
        sinew = _as_finite_float(measurement.get("sinew"))
        if sinew is not None and sinew >= 0:
            muscle_ratio = sinew / weight * 100
            result["muscle_ratio"] = _fitage_round(muscle_ratio, 1)
            if sinew > 0 and gender in (0, 1):
                limits = (59, 64, 69, 74) if gender == 1 else (52, 57, 62, 67)
                result["muscle_storage_capacity"] = next(
                    (
                        index
                        for index, limit in enumerate(limits, 1)
                        if muscle_ratio < limit
                    ),
                    5,
                )

        bone = _as_finite_float(measurement.get("bone"))
        if bone is not None and bone >= 0:
            result["bone_ratio"] = _fitage_round(bone / weight * 100, 1)

    body_shape = _as_int(measurement.get("body_shape"))
    if body_shape in _BODY_SHAPES:
        result["body_shape"] = _BODY_SHAPES[body_shape]

    if _as_int(measurement.get("mea_category")) != 0:
        return result
    if weight is None or weight <= 0 or gender not in (0, 1):
        return result

    bodyfat = _as_finite_float(measurement.get("bodyfat"))
    fat_free_weight = _as_finite_float(measurement.get("fat_free_weight"))
    if (
        bodyfat is None
        or not 0 <= bodyfat <= 100
        or fat_free_weight is None
        or fat_free_weight < 0
    ):
        return result

    standard_type = _fitage_standard_type(measurement, user_info)
    lean_target_ratio = _fitage_lean_target_ratio(gender, weight, standard_type)
    muscle_control = max(weight * lean_target_ratio / 100 - fat_free_weight, 0.0)
    target_fat_fraction = _fitage_bodyfat_target(gender, standard_type) / 100
    current_fat_mass = weight * bodyfat / 100
    fat_control = (
        (weight + muscle_control) * target_fat_fraction - current_fat_mass
    ) / (1 - target_fat_fraction)
    weight_control = muscle_control + fat_control
    recommended_weight = weight + weight_control

    result.update(
        {
            "muscle_control": _fitage_round(muscle_control),
            "fat_control": _fitage_round(fat_control),
            "weight_control": _fitage_round(weight_control),
            "recommended_weight": _fitage_round(recommended_weight),
        }
    )
    return result


def _map_date_format(fmt: str) -> str:
    """Map FITAGE date format to Python strftime format."""
    if not fmt:
        return "%Y-%m-%d"
    mapping = {"dd": "%d", "MM": "%m", "yyyy": "%Y", "yy": "%y"}
    out = fmt
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


def _format_birthday(raw_birthday: Any, date_format: str | None) -> str | None:
    """Format birthday from various input formats."""
    if not raw_birthday:
        return None

    try:
        if isinstance(raw_birthday, int):
            dt = datetime.fromtimestamp(raw_birthday)
            fmt = _map_date_format(date_format or "")
            return dt.strftime(fmt)
        if isinstance(raw_birthday, str) and raw_birthday.isdigit():
            ts = int(raw_birthday)
            dt = datetime.fromtimestamp(ts)
            fmt = _map_date_format(date_format or "")
            return dt.strftime(fmt)
    except (ValueError, OSError):
        pass

    try:
        dt = datetime.strptime(str(raw_birthday), "%Y-%m-%d")
        fmt = _map_date_format(date_format or "")
        return dt.strftime(fmt)
    except ValueError:
        return str(raw_birthday)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for FITAGE - multi-profile support."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    selected_profiles = data.get("selected_profiles") or []
    initial_user_info = data.get("user_info") or {}
    user_id = initial_user_info.get("user_id") or entry.unique_id or entry.entry_id

    async def async_update_data() -> dict[str, Any]:
        """Coordinator update method."""
        try:
            payload = await api.async_fetch_all(
                str(user_id),
                selected_profiles=selected_profiles if selected_profiles else None,
            )
            _LOGGER.debug("FITAGE coordinator fetched keys: %s", list(payload.keys()))
            return payload
        except Exception as err:
            _LOGGER.debug("FITAGE coordinator update failed: %s", err)
            raise UpdateFailed(f"FITAGE fetch failed: {err}") from err

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="fitage",
        update_method=async_update_data,
        update_interval=SCAN_INTERVAL,
    )

    await coordinator.async_refresh()
    data_fetched = coordinator.data or {}

    profiles = data_fetched.get("profiles") or []
    device_binds_payload = data_fetched.get("device_binds") or {}

    entities: list[SensorEntity] = []

    for profile_data in profiles:
        user_info = profile_data.get("user_info") or {}
        profile_user_id = str(user_info.get("user_id", ""))
        account_name = user_info.get("account_name") or "Unknown"
        is_primary = user_info.get("is_primary", True)

        prefix = "" if is_primary else f"{account_name.lower().replace(' ', '_')}_"
        display_prefix = "" if is_primary else f"{account_name} - "

        _LOGGER.debug(
            "Creating sensors for profile: %s (user_id=%s, is_primary=%s, prefix=%s)",
            account_name,
            profile_user_id,
            is_primary,
            prefix,
        )

        if user_info:
            entities.append(
                FeelfitUserSensor(
                    coordinator,
                    entry.entry_id,
                    f"{prefix}account_name",
                    "account_name",
                    f"{display_prefix}Account Name",
                    None,
                    profile_user_id,
                )
            )
            if user_info.get("weight") is not None:
                entities.append(
                    FeelfitUserSensor(
                        coordinator,
                        entry.entry_id,
                        f"{prefix}weight",
                        "weight",
                        f"{display_prefix}Weight",
                        KG_UNIT,
                        profile_user_id,
                    )
                )
            if user_info.get("height") is not None:
                entities.append(
                    FeelfitUserSensor(
                        coordinator,
                        entry.entry_id,
                        f"{prefix}height",
                        "height",
                        f"{display_prefix}Height",
                        "cm",
                        profile_user_id,
                    )
                )
            if "birthday" in user_info:
                entities.append(
                    FeelfitBirthdaySensor(
                        coordinator,
                        entry.entry_id,
                        f"{prefix}birthday",
                        "birthday",
                        f"{display_prefix}Birthday",
                        profile_user_id,
                    )
                )
            if user_info.get("email"):
                entities.append(
                    FeelfitUserSensor(
                        coordinator,
                        entry.entry_id,
                        f"{prefix}email",
                        "email",
                        f"{display_prefix}Email",
                        None,
                        profile_user_id,
                    )
                )

        goals_payload = profile_data.get("goals") or {}
        goals_list = goals_payload.get("goals") or []
        _LOGGER.debug(
            "Profile %s: Processing %d goals",
            user_info.get("account_name"),
            len(goals_list),
        )
        for g in goals_list:
            g_type = g.get("goal_type")
            _LOGGER.debug(
                "Profile %s goal: type=%s, value=%s, full_data=%s",
                user_info.get("account_name"),
                g_type,
                g.get("goal_value"),
                g,
            )
            if not g_type:
                _LOGGER.warning(
                    "Skipping goal with missing goal_type for profile %s: %s",
                    user_info.get("account_name"),
                    g,
                )
                continue
            unique_key = f"{prefix}goal_{g_type}"
            translation_key = f"goal_{g_type}"
            unit: str | None = None
            if g_type == "weight":
                unit = KG_UNIT
            elif g_type == "bodyfat":
                unit = PERCENT
            elif g_type == "water":
                unit = "ml"
            entities.append(
                FeelfitGoalSensor(
                    coordinator,
                    entry.entry_id,
                    unique_key,
                    translation_key,
                    g_type,
                    unit,
                    profile_user_id,
                )
            )

        measurements_payload = profile_data.get("measurements") or {}
        last_measurement = measurements_payload.get("last_measurement")

        if last_measurement:
            measurement_keys: list[tuple[str, str, str | None]] = [
                ("weight", "Weight", KG_UNIT),
                ("bodyfat", "Bodyfat", PERCENT),
                ("bmi", "BMI", None),
                ("bmr", "BMR", KCAL),
                ("bodyage", "Metabolic Age", "y"),
                ("fat_free_weight", "Fat Free Weight", KG_UNIT),
                ("muscle", "Muscle (%)", PERCENT),
                ("protein", "Protein (%)", PERCENT),
                ("sinew", "Sinew", KG_UNIT),
                ("subfat", "Subcutaneous Fat (%)", PERCENT),
                ("visfat", "Visceral Fat", None),
                ("water", "Hydration (%)", PERCENT),
                ("bone", "Bone Mass", KG_UNIT),
                ("heart_rate", "Heart Rate", BPM),
                ("score", "Score", None),
                ("time_stamp", "Measurement Timestamp", None),
                ("body_water_mass", "Body Water Mass", KG_UNIT),
                ("protein_mass", "Protein Mass", KG_UNIT),
                ("body_fat_mass", "Body Fat Mass", KG_UNIT),
                ("muscle_ratio", "Muscle Ratio", PERCENT),
                ("bone_ratio", "Bone Ratio", PERCENT),
                ("muscle_storage_capacity", "Muscle Storage Capacity", None),
                ("body_shape", "Body Shape", None),
                ("muscle_control", "Muscle Control", KG_UNIT),
                ("fat_control", "Fat Control", KG_UNIT),
                ("weight_control", "Weight Control", KG_UNIT),
                ("recommended_weight", "Recommended Weight", KG_UNIT),
            ]

            seen: set[str] = set()
            for key, label, unit in measurement_keys:
                if key in seen:
                    continue
                seen.add(key)
                unique = f"{prefix}measurement_{key}"
                name = f"{display_prefix}{label}"
                entities.append(
                    FeelfitMeasurementSensor(
                        coordinator,
                        entry.entry_id,
                        unique,
                        name,
                        unit,
                        measurement_key=key,
                        profile_user_id=profile_user_id,
                    )
                )

    device_binds = (device_binds_payload or {}).get("device_binds") or []
    for idx, d in enumerate(device_binds):
        scale_name = d.get("scale_name") or d.get("internal_model") or f"device_{idx}"
        unique = f"device_{idx}_{d.get('mac') or idx}"
        label = f"FITAGE {scale_name}"
        entities.append(
            FeelfitDeviceSensor(
                coordinator, entry.entry_id, unique, label, None, device_index=idx
            )
        )

    async_add_entities(entities, True)


class FeelfitUserSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """Sensor for user info attributes."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry_id: str,
        unique_key: str,
        attr_key: str,
        name: str,
        unit: str | None,
        profile_user_id: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_key = attr_key
        self._name = name
        self._unit = unit
        self._profile_user_id = profile_user_id

        self._unique_id = f"{entry_id}_{unique_key}_{profile_user_id or 'primary'}"
        self._attr_translation_key = attr_key
        self._attr_has_entity_name = True

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement."""
        return self._unit

    @property
    def native_value(self) -> Any:
        """Return sensor value."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}

        if not user_info:
            return None

        return user_info.get(self._attr_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {"source": "fitage", "attribute": self._attr_key}

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}

        if not user_info:
            user_info = {}

        user_id = user_info.get("user_id") or self._entry_id
        return {
            "identifiers": {(DOMAIN, f"user_{user_id}")},
            "name": user_info.get("account_name") or f"FITAGE User {user_id}",
            "manufacturer": "FITAGE",
            "model": "FITAGE Account",
        }


class FeelfitBirthdaySensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """Sensor for birthday with date formatting."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry_id: str,
        unique_key: str,
        attr_key: str,
        name: str,
        profile_user_id: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_key = attr_key
        self._name = name
        self._profile_user_id = profile_user_id

        self._unique_id = f"{entry_id}_{unique_key}_{profile_user_id or 'primary'}"
        self._attr_translation_key = attr_key
        self._attr_has_entity_name = True

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def native_value(self) -> str | None:
        """Return formatted birthday."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                user_settings = profile_data.get("user_settings") or {}
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}
            user_settings = profiles[0].get("user_settings") or {}
        elif not user_info:
            return None

        raw = user_info.get("birthday")
        fmt = user_settings.get("date_format")
        return _format_birthday(raw, fmt)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_settings = {}
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_settings = profile_data.get("user_settings") or {}
                break

        return {
            "source": "fitage",
            "attribute": self._attr_key,
            "date_format": user_settings.get("date_format"),
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}

        if not user_info:
            user_info = {}
        user_id = user_info.get("user_id") or self._entry_id
        return {
            "identifiers": {(DOMAIN, f"user_{user_id}")},
            "name": user_info.get("account_name") or f"FITAGE User {user_id}",
            "manufacturer": "FITAGE",
            "model": "FITAGE Account",
        }


class FeelfitGoalSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """Sensor for goal values."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry_id: str,
        unique_key: str,
        translation_key: str,
        goal_type: str,
        unit: str | None,
        profile_user_id: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id

        self._unique_id = f"{entry_id}_{unique_key}_{profile_user_id or 'primary'}"
        self._unit = unit
        self._goal_type = goal_type
        self._profile_user_id = profile_user_id
        self._attr_translation_key = translation_key
        self._attr_has_entity_name = True

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement."""
        return self._unit

    @property
    def native_value(self) -> Any:
        """Return goal value."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        goals_list = []
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                goals_payload = profile_data.get("goals") or {}
                goals_list = goals_payload.get("goals") or []
                break

        if not goals_list and profiles:
            goals_payload = profiles[0].get("goals") or {}
            goals_list = goals_payload.get("goals") or []

        for g in goals_list:
            if g.get("goal_type") == self._goal_type:
                return g.get("goal_value")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {"source": "fitage", "goal_type": self._goal_type}

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}

        if not user_info:
            user_info = {}

        user_id = user_info.get("user_id") or self._entry_id
        return {
            "identifiers": {(DOMAIN, f"user_{user_id}")},
            "name": user_info.get("account_name") or f"FITAGE User {user_id}",
            "manufacturer": "FITAGE",
            "model": "FITAGE Account",
        }


class FeelfitDeviceSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """Sensor for bound device info."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry_id: str,
        unique_key: str,
        name: str,
        unit: str | None,
        device_index: int = 0,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._device_index = device_index
        self._unique_id = f"{entry_id}_device_{unique_key}"
        self._name = name
        self._unit = unit

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return sensor name."""
        return self._name

    @property
    def native_value(self) -> str | None:
        """Return device name."""
        device_binds = (self.coordinator.data or {}).get("device_binds", {}).get(
            "device_binds"
        ) or []
        if len(device_binds) > self._device_index:
            d = device_binds[self._device_index]
            return d.get("scale_name") or d.get("internal_model") or d.get("mac")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        device_binds = (self.coordinator.data or {}).get("device_binds", {}).get(
            "device_binds"
        ) or []
        attrs: dict[str, Any] = {}
        if len(device_binds) > self._device_index:
            d = device_binds[self._device_index]
            for key in (
                "user_id",
                "mac",
                "scale_name",
                "internal_model",
                "created_at",
                "wifi_name",
                "functure_type",
                "device_name",
                "switch_states",
                "blood_standard",
                "light_strip_status",
                "sn",
                "scale_setting",
            ):
                if key in d:
                    attrs[key] = d.get(key)

            model_info = d.get("model_info")
            if isinstance(model_info, dict):
                for mk, mv in model_info.items():
                    if mk == "brand_info" and isinstance(mv, dict):
                        for bk, bv in mv.items():
                            attrs[f"model_brand_{bk}"] = bv
                        brand_name = mv.get("brand_name")
                        if brand_name:
                            attrs["brand_name"] = brand_name
                    else:
                        attrs[f"model_{mk}"] = mv
            if d.get("model_info") is None and d.get("internal_model"):
                attrs["model_internal_model"] = d.get("internal_model")
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        device_binds = (self.coordinator.data or {}).get("device_binds", {}).get(
            "device_binds"
        ) or []
        user_info = (self.coordinator.data or {}).get("user_info") or {}

        if len(device_binds) > self._device_index:
            d = device_binds[self._device_index]
            scale_name = (
                d.get("scale_name")
                or d.get("internal_model")
                or f"Device {self._device_index}"
            )
            model_info = d.get("model_info") or {}
            brand_info = model_info.get("brand_info") or {}
            brand = d.get("brand_name") or brand_info.get("brand_name")
            friendly_name = f"FITAGE {scale_name}"
            if brand:
                friendly_name = f"{friendly_name} ({brand})"
            identifier = (
                d.get("mac")
                or f"{user_info.get('user_id')}_device_{self._device_index}"
            )
            return {
                "identifiers": {(DOMAIN, identifier)},
                "name": friendly_name,
                "manufacturer": brand or "FITAGE",
                "model": model_info.get("model")
                or d.get("internal_model")
                or "FITAGE Device",
            }

        user_id = user_info.get("user_id")
        return {
            "identifiers": {(DOMAIN, f"{user_id}_device_{self._device_index}")},
            "name": f"{user_info.get('account_name', 'FITAGE User')} device {self._device_index}",
            "manufacturer": "FITAGE",
            "model": "FITAGE Device",
        }


class FeelfitMeasurementSensor(
    CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity
):
    """Sensor for measurement values."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry_id: str,
        unique_key: str,
        name: str,
        unit: str | None,
        measurement_key: str,
        profile_user_id: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id

        self._unique_id = f"{entry_id}_{unique_key}_{profile_user_id or 'primary'}"
        self._name = name
        self._unit = unit
        self._measurement_key = measurement_key
        self._profile_user_id = profile_user_id
        self._attr_translation_key = f"measurement_{measurement_key}"
        self._attr_has_entity_name = True

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._unique_id

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement."""
        return self._unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the sensor device class."""
        if self._measurement_key == "body_shape":
            return SensorDeviceClass.ENUM
        return None

    @property
    def options(self) -> list[str] | None:
        """Return the valid body-shape states."""
        if self._measurement_key == "body_shape":
            return list(_BODY_SHAPES.values())
        return None

    @property
    def native_value(self) -> Any:
        """Return measurement value."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        measurement = None
        measurement_user_info: dict[str, Any] = {}
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                measurements_payload = profile_data.get("measurements") or {}
                measurement = measurements_payload.get("last_measurement")
                measurement_user_info = profile_info
                break

        if not measurement and profiles:
            measurements_payload = profiles[0].get("measurements") or {}
            measurement = measurements_payload.get("last_measurement")
            measurement_user_info = profiles[0].get("user_info") or {}

        if not measurement:
            _LOGGER.debug(
                "FITAGE measurement sensor: no measurement for key %s",
                self._measurement_key,
            )
            return None

        if self._measurement_key in _CALCULATED_MEASUREMENT_KEYS:
            return _calculate_fitage_metrics(measurement, measurement_user_info).get(
                self._measurement_key
            )

        raw_val = measurement.get(self._measurement_key)
        mass_percentage_keys = {
            "body_fat_mass": "bodyfat",
            "body_water_mass": "water",
            "protein_mass": "protein",
        }
        if percentage_key := mass_percentage_keys.get(self._measurement_key):
            mass = _as_finite_float(raw_val)
            if mass is not None and mass > 0:
                raw_val = mass
            else:
                weight = _as_finite_float(measurement.get("weight"))
                percentage = _as_finite_float(measurement.get(percentage_key))
                if (
                    weight is None
                    or weight <= 0
                    or percentage is None
                    or percentage < 0
                ):
                    return None
                raw_val = weight * percentage / 100

        if self._measurement_key == "time_stamp" and raw_val:
            try:
                ts = int(raw_val)
                dt = datetime.fromtimestamp(ts)
                return dt.isoformat()
            except (ValueError, OSError):
                return str(raw_val)

        if isinstance(raw_val, (int, float)):
            if self._measurement_key in ("bodyage", "measurement_id", "user_id"):
                try:
                    return int(raw_val)
                except (ValueError, TypeError):
                    return raw_val
            try:
                fval = float(raw_val)
                if fval.is_integer():
                    return int(fval)
                return round(fval, 2)
            except (ValueError, TypeError):
                return raw_val

        if isinstance(raw_val, str):
            cleaned = raw_val.replace(".", "", 1)
            if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
                try:
                    if "." in raw_val:
                        fval = float(raw_val)
                        if fval.is_integer():
                            return int(fval)
                        return round(fval, 2)
                    return int(raw_val)
                except (ValueError, TypeError):
                    pass
            return raw_val

        return raw_val

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        measurement = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                measurements_payload = profile_data.get("measurements") or {}
                measurement = measurements_payload.get("last_measurement")
                break

        if not measurement and profiles:
            measurements_payload = profiles[0].get("measurements") or {}
            measurement = measurements_payload.get("last_measurement")

        attrs: dict[str, Any] = {}
        if measurement:
            for k in (
                "measurement_id",
                "user_id",
                "scale_name",
                "internal_model",
                "mac",
                "parameter",
                "accuracy_flag",
                "measure_mode_flags",
            ):
                if k in measurement:
                    attrs[k] = measurement.get(k)
        return attrs

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        profiles = (self.coordinator.data or {}).get("profiles") or []

        user_info = None
        for profile_data in profiles:
            profile_info = profile_data.get("user_info") or {}
            if self._profile_user_id and str(profile_info.get("user_id")) == str(
                self._profile_user_id
            ):
                user_info = profile_info
                break

        if not user_info and profiles:
            user_info = profiles[0].get("user_info") or {}

        if not user_info:
            user_info = {}

        user_id = user_info.get("user_id") or self._entry_id
        return {
            "identifiers": {(DOMAIN, f"user_{user_id}")},
            "name": user_info.get("account_name") or f"FITAGE User {user_id}",
            "manufacturer": "FITAGE",
            "model": "FITAGE Account",
        }
