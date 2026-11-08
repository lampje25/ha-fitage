# FITAGE v1.6.3

FITAGE v1.6.3 fixes dashboard graph compatibility with Home Assistant Core 2026.11.0.

## Dashboard graph compatibility

Home Assistant 2026.11's statistics graph card no longer exposes `hass` through the prototype accessor used by earlier frontend versions. FITAGE now accepts a valid `hass` instance delivered as either an accessor-backed property or a regular own property. The graph still must be upgraded, configured, and given the current Home Assistant instance before it is attached to the dashboard.

Support for earlier Home Assistant frontend behavior, including the 2026.10.x prototype-accessor model, is retained. Automated lifecycle regression tests cover both property models, lazy loading, an already-loaded graph card, period changes, reconfiguration, and stale asynchronous generations.

The bundled FITAGE Dashboard Card is updated to `v0.6.5`.

No FITAGE sensors, measurement calculations, or cloud API behavior changed.
