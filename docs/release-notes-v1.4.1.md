# FITAGE v1.4.1

FITAGE v1.4.1 is a publication and documentation release that prepares the integration for submission to the HACS default catalog.

## Changes

- Adds dedicated HACS and Hassfest validation workflows.
- Improves the README and repository discoverability for FITAGE/QNClouds smart scales, multiple profiles, body-composition sensors, historical measurements, and long-term statistics.
- Adds a standard Home Assistant weight statistics dashboard example.
- Adds reviewable screenshot, announcement, and HACS/default submission plans.
- Sets the minimum Home Assistant version to 2025.12.0, the first stable Core release containing all public Store and Recorder metadata APIs used by FITAGE history and external statistics.
- Updates the Hassfest workflow to the current Node.js 24-based checkout action.

## Compatibility

There are no breaking changes and no new functional history or statistics logic. The FITAGE v1.4.0 behavior, entity identities, statistic IDs, private history Store, websocket API, and optional Recorder statistics remain unchanged.
