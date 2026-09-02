"""Release invariants for FITAGE v1.4.1."""

from __future__ import annotations

import asyncio
import json
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.fitage import async_update_options
from custom_components.fitage.const import DOMAIN

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / DOMAIN


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def test_manifest_is_valid_v141_hacs_candidate() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["version"] == "1.4.1"
    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["after_dependencies"] == ["recorder"]
    assert "recorder" not in manifest["dependencies"]
    assert json.loads((ROOT / "hacs.json").read_text())["render_readme"] is True


def test_temporary_actions_and_services_are_absent() -> None:
    probe_module = "history_" + "probe"
    assert not (COMPONENT / f"{probe_module}.py").exists()
    assert not (COMPONENT / ("services" + ".yaml")).exists()
    assert not (ROOT / "tests" / f"test_{probe_module}.py").exists()
    rendered = "".join(
        path.read_text() for path in (*COMPONENT.glob("*.py"), *ROOT.glob("tests/*.py"))
    )
    for temporary in (
        "run_" + "history_" + "probe",
        "inspect_" + "history_" + "status",
        probe_module,
    ):
        assert temporary not in rendered


@run_async
async def test_profile_deselection_does_not_clear_history_or_statistics() -> None:
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=AsyncMock()))
    entry = SimpleNamespace(
        entry_id="entry",
        options={"selected_profiles": []},
        data={"selected_profiles": ["profile"]},
    )
    device_registry = MagicMock()
    device_registry.devices = {}
    entity_registry = MagicMock()
    entity_registry.entities = {}
    with (
        patch(
            "homeassistant.helpers.device_registry.async_get",
            return_value=device_registry,
        ),
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=entity_registry,
        ),
        patch("custom_components.fitage.async_clear_entry_statistics") as clear,
    ):
        await async_update_options(hass, entry)
    clear.assert_not_called()
    hass.config_entries.async_reload.assert_awaited_once_with("entry")
