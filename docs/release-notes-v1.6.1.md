# Fitage v1.6.1

FITAGE v1.6.1 makes the dashboard card's own fixed texts multilingual - metric titles, the "current value" label, minimum/maximum, the graph loading placeholder, and the editor's "None" button - and makes its number and period-label formatting follow Home Assistant's own locale settings.

## New: multilingual dashboard card texts

The FITAGE Dashboard Card (`v0.6.4`) now shows all of its fixed texts in the user's own Home Assistant language, using verified official text only - never invented or machine-translated strings.

- **Metric titles.** All 14 dashboard metric titles are now available in the same 21 officially verified FITAGE languages already used for assessment labels (English, Dutch, German, Spanish, Italian, Arabic, Portuguese, Turkish, Hungarian, Polish, Romanian, Slovak, Thai, Vietnamese, Korean, Japanese, Russian, Czech, Simplified Chinese, Traditional Chinese, and French), sourced from the official FITAGE app's own translation files (with `appSpecialTranslation` overrides applied where the app itself applies them). Any other Home Assistant language, or a metric missing a translation, falls back to English rather than showing a blank or internal value.
- **"Current value" label.** Uses the FITAGE app's own official `current` translation key for all 21 languages, with one deliberate exception (see below).
- **Minimum / Maximum.** Uses Home Assistant's own official, generic frontend translation keys (`ui.panel.lovelace.editor.card.generic.minimum` / `.maximum`) instead of a FITAGE key - the candidate FITAGE keys for this concept were checked and found to be false friends in several languages (for example, meaning "minutes" or a scale's maximum load capacity). Falls back to the English `Minimum` / `Maximum` text if Home Assistant does not supply a translation.
- **Loading placeholder and the editor's "None" button.** Use Home Assistant's own official `ui.common.loading` and `ui.common.none` translation keys, with an English fallback, for the two places where the concept is an exact match. Every other editor label, hint, and error message is deliberately left in Dutch, as there is no reliable official translation source for that specific wording.

### Six deliberately kept Dutch metric names

Six existing Dutch metric names are intentionally *not* replaced by the literal official FITAGE app text, because the current card text is already clearer (or, in one case, the official text is outright incorrect):

| Metric key | Kept Dutch text | Official app text (not used) |
| --- | --- | --- |
| `protein` | Eiwit | Eiwitgehalte |
| `protein_mass` | Eiwitmassa | Eiwitmolecuul (literally "protein molecule" - not a mass) |
| `bmr` | Basaal metabolisme | BMR |
| `fat_free_weight` | Vetvrij gewicht | Vetvrij lichaamsgewicht |
| `body_fat_mass` | Vetmassa | Lichaamsvetmassa |
| `body_water_mass` | Watermassa | Lichaamswatermassa |

All other Dutch metric names already matched the official FITAGE app text exactly and are unchanged.

### Thai "current value" fallback

The official FITAGE app text for the `current` translation key in Thai is "กระแสน้ำ", which means "water current" or "tide" - not "current value" - and would mislabel every metric's present-day reading (weight, BMI, etc.). This is a deliberate correctness fallback, not a translation gap: Thai uses the English "Current" label for this one text, while every other Thai metric title keeps its own correct official translation.

## New: locale-aware number and period-label formatting

- **Numbers.** The card's number formatting now follows Home Assistant's own `hass.locale.number_format` and `hass.locale.language` settings (comma-decimal, decimal-comma, space-comma, quote-decimal, or the browser/system default), using the same resolution Home Assistant's own frontend uses, instead of a hardcoded Dutch (`nl-NL`) format. Units are always appended separately and are never affected by the number formatting itself. An invalid or unrecognized locale safely falls back to an English-style format instead of crashing.
- **Period buttons.** The visible period button labels ("7 days", "1 month", etc.) are now generated per Home Assistant language using the same narrow unit style Home Assistant's own frontend uses, with a verified exception for Japanese (where the narrow style does not actually localize and the short style is used instead). The internal range keys and the day counts used to fetch and group graph data (`7d`, `14d`, `1m`, `3m`, `1j` → 7/14/30/90/365 days) are completely unchanged by this - only the visible label differs by language.

## New: minimal right-to-left support

The card now adopts Home Assistant's own text direction (`document.dir`) for right-to-left languages such as Arabic, the same approach Home Assistant's own frontend components use, instead of maintaining a separate RTL language list. The one physical CSS property affected by text direction (the divider between adjacent value cells) now uses the logical `border-inline-start` instead of `border-left`, so it mirrors correctly under RTL. No other layout, graphs, axes, numbers, or units are mirrored.

## Compatibility

This release changes only how the dashboard card *displays* existing data. It does not change any entity ID, unique ID, device, measurement value, assessment key, or configuration option. No action is required after upgrading beyond restarting Home Assistant.

## Upgrading with HACS

Open HACS, update FITAGE to v1.6.1, and restart Home Assistant. The dashboard card updates to `v0.6.4` automatically as part of the same update.

## Validation

This release was verified with the full standalone FITAGE test suite, including `tests/runtime/`, run as `python -m pytest` from a Home Assistant Core checkout with Home Assistant Core's own pytest configuration and conftest fixtures explicitly loaded:

```bash
cd /workspaces/core
PYTHONPATH=/workspaces/ha-fitage python -m pytest -q \
  -c /workspaces/core/pyproject.toml \
  -p tests.conftest \
  /workspaces/ha-fitage/tests
```

339 passed - covering all assessment, sensor, frontend/card, release-candidate, and runtime (v1.2-to-v1.3 upgrade and end-to-end statistics rebuild) tests.

The Python files changed since v1.6.0 (`custom_components/fitage/frontend.py`, `tests/test_frontend.py`, `tests/test_release_candidate.py`) were also verified with `ruff format --check` and `ruff check` (both clean, no changes needed). The bundled dashboard card was checked for valid JavaScript syntax under Node.js, `manifest.json` and `hacs.json` were checked for valid JSON, and `git diff --check` reported no whitespace issues.
