# FITAGE dashboard example

FITAGE can optionally import historical measurements as external long-term statistics. This is disabled by default because body-composition history is health data. Enable **Historical FITAGE statistics import** in the integration options only if you consent to storing the selected profiles and metrics in Home Assistant Recorder.

## Weight statistics graph

The standard Home Assistant `statistics-graph` card accepts an external statistic ID directly:

```yaml
type: statistics-graph
title: FITAGE weight
entities:
  - "fitage:<entry-hash>_<profile-hash>_weight"
stat_types:
  - state
period: day
days_to_show: 30
chart_type: line
```

Replace the placeholder with your own FITAGE weight statistic ID. In Home Assistant, open **Developer Tools → Statistics**, locate the readable FITAGE weight entry for the intended profile, and copy its statistic ID. Do not publish that ID together with account details or diagnostic data.

The graph appears after the optional statistics import has run and Recorder contains data for the selected profile. Change `days_to_show` or `period` to suit the view.

For more advanced period selection and chart styling, the third-party ApexCharts Card can display Home Assistant statistics too. It is optional and is not a FITAGE dependency; consult its own documentation for installation and configuration.
