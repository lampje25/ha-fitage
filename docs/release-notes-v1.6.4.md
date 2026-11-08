# FITAGE v1.6.4

FITAGE v1.6.4 improves dashboard metric consistency and classification presentation.

## Dashboard metric consistency

The Spierverhouding card now uses the same `muscle` measurement for its current value, FITAGE assessment, and historical graph. The separate `muscle_ratio` sensor remains distinct and unchanged.

Values without a valid classification use a neutral theme-dependent text color. Invalid current values no longer display stale classifications.

The dashboard no longer invents fallback bone-mass reference bounds when the backend does not provide them.

Regression tests now exercise all 14 dashboard metrics, including live and historical mappings, units, assessments, limits, colors, labels, display modes, and invalid values.

No database or historical-statistics migration is required.
