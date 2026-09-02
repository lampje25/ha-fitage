# FITAGE v1.4.0

FITAGE v1.4.0 adds durable historical body-composition measurements while preserving existing entity IDs, canonical unique IDs, devices, custom names, and dashboards.

## Highlights

- Synchronizes historical measurements from the official FITAGE/QNClouds cursor route.
- Stores independent history and cursors for every selected profile.
- Resumes cursors after Home Assistant restarts without repeating a full import.
- Applies incremental updates and server deletions to a private versioned raw Store.
- Selects the actual latest measurement deterministically rather than relying on response order.
- Adds admin-only `fitage/history/profiles` and `fitage/history/query` websocket commands for exact, paginated, privacy-filtered history.
- Adds optional external statistics for Home Assistant graphs and ApexCharts using one deterministic last-of-hour point in UTC, with readable profile and metric names while technical statistic IDs remain stable.
- Requires explicit opt-in before derived health measurements are written to Recorder.
- Rebuilds only affected statistic series after raw updates or deletes.
- Cleans up the config entry's own statistics before removing its private history Store when the complete entry is removed. If Recorder cleanup fails or cannot be confirmed, the Store and cleanup metadata are retained for a safe later retry.

## Upgrading with HACS

Open HACS, update FITAGE to v1.4.0, and restart Home Assistant. Existing entity IDs, unique IDs, devices, custom names, and dashboards are preserved. Historical statistics remain disabled by default and require explicit opt-in in the FITAGE integration options.

## Privacy

Historical body-composition data is health data. Raw history is private, statistics import is disabled by default, websocket history is admin-only, and websocket responses/statistic IDs do not expose FITAGE user IDs or measurement IDs. Disabling statistics stops future imports but leaves already imported Recorder data intact.

## Known limitations

- External-statistic clear and reimport are separate Recorder operations, so an affected graph can briefly be empty.
- Statistics use one last measurement per UTC hour; exact raw history retains every measurement.
- Deselecting a profile does not yet remove its stored raw history or statistics.
- Previously imported statistics remain after disabling the option; removal currently occurs only when the full config entry is deleted.
- Visceral fat, metabolic age, cardiac index, segment values, and categorical values are excluded until a compatible unit and semantic mapping is proven.
- Exact-history pagination cursors are invalidated by a full Home Assistant restart.

## Cleanup recovery

If entry removal reports an incomplete statistics cleanup, keep the retained private Store in `.storage`; it contains the profile identities and metadata needed for recovery. Restore the removed config entry from a Home Assistant backup, ensure Recorder is available, and remove that same entry again. Delete the retained Store manually only after the retry succeeds or after independently confirming that none of its FITAGE statistic IDs remain.
