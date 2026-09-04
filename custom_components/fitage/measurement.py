"""Shared effective FITAGE measurement values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MASS_PERCENTAGE_KEYS = {
    "body_fat_mass": "bodyfat",
    "body_water_mass": "water",
    "protein_mass": "protein",
}


def _finite_float(value: Any) -> float | None:
    """Return a finite float without accepting booleans."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def effective_mass_value(record: Mapping[str, Any], metric: str) -> float | None:
    """Resolve a reliable cloud mass or derive it from weight and percentage."""
    percentage_key = MASS_PERCENTAGE_KEYS.get(metric)
    if percentage_key is None:
        raise ValueError(f"Unsupported FITAGE mass metric: {metric}")

    cloud_mass = _finite_float(record.get(metric))
    if cloud_mass is not None and cloud_mass > 0:
        return cloud_mass

    weight = _finite_float(record.get("weight"))
    percentage = _finite_float(record.get(percentage_key))
    if weight is None or weight <= 0 or percentage is None or percentage <= 0:
        return None
    return weight * percentage / 100
