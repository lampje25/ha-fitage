"""Serve the bundled FITAGE dashboard card and register it as a Lovelace
module resource.

Registration happens once per Home Assistant runtime from the domain-level
``async_setup`` in ``__init__.py`` - not per config entry - so multiple
FITAGE profiles/entries and config-entry reloads never register the static
path or the Lovelace resource more than once. There is deliberately no
teardown on unload: the registration is not tied to any single config entry,
so removing one entry must not affect the card while another entry is still
active.

Why a Lovelace resource instead of ``add_extra_js_url``:

``homeassistant.components.frontend.add_extra_js_url`` bakes its URL into
``index.html`` at the moment that page is rendered (see
``homeassistant.components.frontend.IndexView.get()``). Custom, config-entry
integrations such as FITAGE only run in Home Assistant's bootstrap "stage 2"
(``homeassistant/bootstrap.py``, the ``domains`` stage), strictly after
"frontend" has already finished its own "stage 0" setup and started serving
pages. A browser tab that (re)loads in that window renders without the
FITAGE module and never retroactively picks it up - confirmed against a real
Home Assistant runtime. A Lovelace resource does not have this problem: the
dashboard frontend fetches the current resource list over the
``lovelace/resources`` websocket command when a dashboard is opened, long
after the app has booted, not once at initial page render.

Lovelace resources are managed through ``hass.data[LOVELACE_DATA].resources``
(``homeassistant.components.lovelace.resources.ResourceStorageCollection``),
the same collection object Home Assistant's own resource editor uses - there
is no dedicated public helper for this (unlike ``add_extra_js_url``, which
exists specifically for this purpose but cannot avoid the race above). Only
its public, non-underscored surface is used here (``loaded``, ``async_load``,
``async_items``, ``async_create_item``, ``async_update_item``); no
``.storage`` file is ever read or written directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    LOVELACE_DATA,
    MODE_STORAGE,
)
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.const import CONF_ID, CONF_URL
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "fitage-card.js"
STATIC_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"

# Kept in sync with the `const VERSION = "..."` at the top of
# www/fitage-card.js; see tests/test_frontend.py for the check that enforces
# this. Reading the version out of the JS file at runtime would require a
# blocking file read during async_setup, which Home Assistant flags and
# custom integrations must not do.
CARD_VERSION = "0.5.1"

MODULE_URL = f"{STATIC_URL_PATH}?v={CARD_VERSION}"

# An internal development prototype of the card was, at times, manually
# installed under Lovelace's /local/ path; it was never part of a public
# FITAGE release. Any leftover resource at that path is never touched or
# removed here - only flagged - so whoever has one can clean it up themselves.
LEGACY_PROTOTYPE_URL_PATH = "/local/fitage-card/fitage-card.js"

_DATA_FRONTEND_REGISTERED = "frontend_registered"

_RESOURCE_TYPE_MODULE = "module"


def _card_path() -> Path:
    """Return the on-disk path of the bundled card, resolved from this file."""
    return Path(__file__).parent / "www" / CARD_FILENAME


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve fitage-card.js as a static path and register it as a Lovelace
    module resource. Safe to call more than once; only the first call has
    any effect for the lifetime of this Home Assistant runtime.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_FRONTEND_REGISTERED):
        return
    domain_data[_DATA_FRONTEND_REGISTERED] = True

    card_path = _card_path()
    if not card_path.is_file():
        _LOGGER.warning(
            "FITAGE dashboard card not found at %s; the bundled 'fitage-card' "
            "Lovelace card will not be available until FITAGE is reinstalled "
            "or updated",
            card_path,
        )
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, str(card_path), cache_headers=True)]
    )

    try:
        await _async_register_lovelace_resource(hass)
    except Exception:  # noqa: BLE001 -- a resource-registration failure must
        # never block FITAGE's sensors, history or cloud integration from
        # setting up; the card is still reachable at STATIC_URL_PATH and can
        # be added as a manual resource.
        _LOGGER.error(
            "Could not automatically register the FITAGE dashboard card as "
            "a Lovelace resource; add %s manually as a 'module' resource if "
            "it does not appear in the card picker",
            MODULE_URL,
        )


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Idempotently create or update the FITAGE Lovelace module resource."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.warning(
            "Lovelace is not set up; add %s manually as a 'module' resource "
            "if you use dashboards",
            MODULE_URL,
        )
        return

    if lovelace_data.resource_mode != MODE_STORAGE:
        _LOGGER.warning(
            "Lovelace is running in YAML mode; FITAGE cannot register its "
            "dashboard card resource automatically. Add this resource to "
            "your Lovelace YAML configuration manually: url: %s, type: module",
            MODULE_URL,
        )
        return

    resources = lovelace_data.resources
    # LovelaceData's own contract: resource_mode selects which of the two
    # resources types is present, so this is guaranteed by the MODE_STORAGE
    # check above, not an assumption about non-public internals.
    assert isinstance(resources, ResourceStorageCollection)

    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    managed_item: dict | None = None
    legacy_prototype_found = False
    for item in resources.async_items():
        item_path = urlsplit(item.get(CONF_URL, "")).path
        if item_path == STATIC_URL_PATH:
            managed_item = item
        elif item_path == LEGACY_PROTOTYPE_URL_PATH:
            legacy_prototype_found = True

    if managed_item is None:
        await resources.async_create_item(
            {CONF_RESOURCE_TYPE_WS: _RESOURCE_TYPE_MODULE, CONF_URL: MODULE_URL}
        )
        _LOGGER.debug("Created FITAGE dashboard card Lovelace resource %s", MODULE_URL)
    elif managed_item[CONF_URL] != MODULE_URL:
        await resources.async_update_item(managed_item[CONF_ID], {CONF_URL: MODULE_URL})
        _LOGGER.debug(
            "Updated FITAGE dashboard card Lovelace resource to %s", MODULE_URL
        )

    if legacy_prototype_found:
        _LOGGER.warning(
            "Found an old, manually added FITAGE dashboard card resource at "
            "%s. FITAGE now manages its own resource automatically; you can "
            "remove the old one from Settings > Dashboards > Resources",
            LEGACY_PROTOTYPE_URL_PATH,
        )
