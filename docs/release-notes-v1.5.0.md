# FITAGE v1.5.0

FITAGE v1.5.0 introduces the FITAGE Dashboard Card and corrects how automatic profile/statistic linking selects the right weight statistic.

## New: FITAGE Dashboard Card

FITAGE v1.5.0 introduces the FITAGE Dashboard Card. The card is bundled with the integration and registered with Home Assistant automatically as a Lovelace resource; you do not need to install a separate JavaScript file or add a resource by hand.

After installing or updating FITAGE and restarting Home Assistant, the card appears in the card picker as **FITAGE Card**.

Capabilities:

- Graph view (one card per measurement with its own history graph), or a compact overview without graphs.
- Individual measurements can be turned on or off.
- Periods `7d`, `14d`, `1m`, `3m`, and `1j` (one year).
- Adjustable text size.
- Optional custom colors.
- The current value and, where available, the minimum and maximum of the normal range.
- Decimal precision tuned per measurement.
- Automatic profile/statistic linking, with a clear error shown instead of a guess whenever a profile cannot be linked reliably.

See [FITAGE Dashboard Card](../README.md#fitage-dashboard-card) in the README for setup and the full configuration reference.

## Fixes

- **Corrected statistic-prefix detection.** The card's automatic profile linking matched any statistic ID ending in `_weight`, which incorrectly also matched `_fat_free_weight` (a separate FITAGE metric). Matching is now done structurally against the known FITAGE metric list, so only the actual `weight` metric is ever selected.
- **More reliable automatic linking.** Before comparing weight values, the card now checks the profile metadata Home Assistant's own statistics already carry (the profile name FITAGE recorded when it created that statistic). This resolves the correct profile deterministically in the common case, without depending on today's weight reading at all. Value comparison is only used as a fallback, and if two candidates are equally plausible - whether by matching profile name or by weight value - the card shows its existing clear error instead of guessing.

## Internal

- The previously reported `hui-graph-header-footer` crash was a Home Assistant frontend bug, fixed upstream in Home Assistant Frontend 20260826.6 by checking that `this.hass` exists before reading `this.hass.config`. It was never a FITAGE defect. The dashboard card's graph-creation guard no longer checks a private, non-public property of Home Assistant's own graph card component to defend against it; the card's own lifecycle guarantees - safe DOM attachment, no property loss across a custom-element upgrade, and generation tokens that discard stale async results - are unchanged and remain covered by tests.

## Compatibility

There are no breaking changes. Entity IDs, unique IDs, devices, custom names, statistic IDs, the private history Store schema, and the websocket API are unchanged. FITAGE now declares a dependency on Home Assistant's `frontend` and `lovelace` components to register the card; both are core components enabled by default. The minimum supported Home Assistant version is unchanged.

## Upgrading with HACS

Open HACS, update FITAGE to v1.5.0, and restart Home Assistant. Open a dashboard, click **Add card**, and search for **FITAGE Card**.

## Validation

This release was verified with a JavaScript syntax check under Node.js, the targeted frontend tests, the setup tests, the release-candidate tests, and the full standalone FITAGE test suite, alongside `ruff check`, `ruff format --check`, and a repository-wide privacy search. The dashboard card was also manually tested against Home Assistant Core 2026.10.0.dev0 and Home Assistant Frontend 20260826.6, covering the card picker, the card editor, the stub profile, a real FITAGE profile, graph view, compact view, period switching, and removing and re-adding the card.
