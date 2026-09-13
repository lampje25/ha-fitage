# FITAGE v1.6.0

FITAGE v1.6.0 adds official FITAGE category colors and labels to the dashboard card, makes the card multilingual, and corrects the bone mass, bone ratio, and BMR assessment logic to match the official FITAGE app.

## New: official colors, labels, and languages on the dashboard card

The FITAGE Dashboard Card (`v0.6.3`) now shows each assessed measurement's category using FITAGE's own official colors and text, reverse-engineered from the official FITAGE app rather than guessed from zone position or a gradient.

- The card automatically follows Home Assistant's own user language.
- 21 officially verified FITAGE languages are supported: English, Dutch, German, Spanish, Italian, Arabic, Portuguese, Turkish, Hungarian, Polish, Romanian, Slovak, Thai, Vietnamese, Korean, Japanese, Russian, Czech, Simplified Chinese, Traditional Chinese, and French.
- Any other Home Assistant language falls back to English.
- If an assessment category is ever unrecognized, the card shows no label at all and keeps its existing default (orange) color, instead of guessing or fabricating text.

## Fixes

- **Corrected bone mass.** Bone mass (`bone`) is now judged against the official kilogram bounds derived from the profile's *current* weight (3%-5% of body weight for a male profile, 2.5%-4% for a female profile), instead of an incorrect fixed kilogram range that ignored weight entirely.
- **Corrected bone ratio.** Bone ratio (`bone_ratio`) is now judged directly against the fixed official percentage bounds (3%-5% male, 2.5%-4% female), instead of a value that was incorrectly derived by dividing the (already incorrect) bone mass bounds by weight.
- **Corrected BMR categories.** BMR now reports the official `not_standard` (below the calculated reference) or `standard` (at or above the reference) assessment category. The unchanged reference formula itself was already correct; only the category keys were wrong.

## Compatibility

**The BMR sensor's `assessment` attribute value has changed**, from `below_average` / `above_average` to the official `not_standard` / `standard`. Automations or dashboards that filter or display logic based on the literal BMR `assessment` value should be checked and updated after upgrading. No other entity IDs, unique IDs, devices, custom names, statistic IDs, the private history Store schema, or the websocket API are affected.

## Upgrading with HACS

Open HACS, update FITAGE to v1.6.0, and restart Home Assistant. The dashboard card updates to `v0.6.3` automatically as part of the same update.

## Validation

This release was verified with the full standalone FITAGE test suite, including `tests/runtime/`, run as `python -m pytest` from a Home Assistant Core checkout with Home Assistant Core's own pytest configuration and conftest fixtures explicitly loaded:

```bash
cd /workspaces/core
PYTHONPATH=/workspaces/ha-fitage python -m pytest -q \
  -c /workspaces/core/pyproject.toml \
  -p tests.conftest \
  /workspaces/ha-fitage/tests
```

331 passed - covering all assessment, sensor, frontend/card, release-candidate, and runtime (v1.2-to-v1.3 upgrade and end-to-end statistics rebuild) tests.

The Python files touched by this release were also verified with `ruff format --check` and `ruff check` (both clean), and the bundled dashboard card was checked for valid JavaScript syntax under Node.js.
