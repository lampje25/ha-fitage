# FITAGE v1.4.2

FITAGE v1.4.2 is a bug-fix release. It corrects local brand icon sizes and fixes three derived body-composition masses that could read as an incorrect `0` when the FITAGE cloud returned a zero sentinel for them.

## Fixes

- Corrects `icon.png` and `icon@2x.png` so the local FITAGE brand icons use their expected sizes. The existing `logo.png` and `logo@2x.png` assets remain unchanged and are covered by the brand-asset validation.
- Fixes `body_fat_mass`, `body_water_mass`, and `protein_mass`: a FITAGE cloud value of `0` for one of these three fields is now treated as a sentinel and, when a valid weight and the matching percentage are available, replaced by the derived mass (`weight × percentage / 100`) instead of being reported as a literal `0`.
- Applies this effective-value resolution consistently across current measurement sensors, websocket history queries, Recorder long-term statistics, statistics data detection, and statistics fingerprints.
- Raw history records stored in the private FITAGE Store are unchanged; only how the three affected masses are *read* for sensors, websocket responses, and statistics is corrected.
- Existing statistic IDs and profile hashes are preserved. A targeted, one-time v1-to-v2 statistics-projection migration marks only the three affected mass metrics for rebuild per profile, so previously stored incorrect `0.0` statistics are recomputed without touching unaffected metrics or statistic IDs.

## Compatibility

There are no breaking changes. Entity IDs, unique IDs, devices, custom names, the private history Store schema, and the websocket API remain unchanged. Heart rate, muscle mass/`sinew`, visceral fat, and the standalone FITAGE dashboard card are not part of this release.

## Upgrading with HACS

Open HACS, update FITAGE to v1.4.2, and restart Home Assistant. On first start after the upgrade, FITAGE automatically rebuilds only the `body_fat_mass`, `body_water_mass`, and `protein_mass` statistics for profiles that have them enabled; other statistics are left untouched.

## Validation

This release was verified with the targeted release-candidate tests, the full standalone FITAGE test suite, and a local Home Assistant practice test covering two profiles.
