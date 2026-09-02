# FITAGE v1.4 history research

## Proven live API behavior

A manually invoked, read-only probe used the authentication of an existing
Home Assistant FITAGE config entry. It called only
`GET /api/v4/measurements/list_measurement`, starting each profile at cursor
`(0, "0")`.

The two configured profiles completed in one page each:

| Observation | profile-A | profile-B |
| --- | ---: | ---: |
| Records | 21 | 2 |
| Deletes | 9 | 0 |
| Observed period | 2026-08 through 2026-09 | 2026-08 |
| `finish_flag` | 1 | 1 |
| `last_updated_at` type | `int` | `int` |
| `last_measurement_id` type | `str` | `str` |
| Observed order | ascending | descending |

The observed batch sizes are not a proven server limit. Record user IDs were
present and matched the requested profile. Measurement IDs were unique within
each profile. No records were mixed between profiles. All observed measurement
fields were non-null in this sample.

The populated measurement fields observed for both profiles were: `bmi`, `bmr`,
`body_fat_mass`, `body_shape`, `body_water_mass`, `bodyage`, `bodyfat`,
`bodyfat_left_arm`, `bodyfat_left_leg`, `bodyfat_right_arm`,
`bodyfat_right_leg`, `bodyfat_trunk`, `bone`, `cardiac_index`,
`fat_free_weight`, `heart_rate`, `muscle`, `protein`, `protein_mass`, `score`,
`sinew`, `subfat`, `time_stamp`, `visfat`, `water`, and `weight`.

This sample had a null-value count of zero for both profiles. That observation
does not change the parser rule that optional raw fields may be null or absent;
only identity, profile isolation, timestamp, and cursor contract fields are
required.

The sample proves that deletes occur in production and that response ordering
cannot be used to identify the newest measurement. The newest record must be
selected by `time_stamp`, followed by a stable measurement-ID tie-breaker.

## Implemented first-phase architecture

Each config entry owns one private Home Assistant Store:

```text
version: 1
key: fitage.history_<config_entry_id>
private: true
atomic_writes: true
serialize_in_event_loop: false
```

The Store data has this shape:

```json
{
  "profiles": {
    "<user_id>": {
      "cursor": {
        "last_updated_at": 0,
        "last_measurement_id": "0"
      },
      "measurements": {
        "<measurement_id>": {}
      },
      "sync": {
        "complete": false
      }
    }
  }
}
```

Profiles are addressed only by their server user ID. There are no display-name,
timestamp, primary-profile, or cross-profile fallbacks. Records are upserted by
the composite scope `(user_id, measurement_id)`. Deletes are idempotent and are
applied only to the currently requested profile.

Each response is fully parsed and validated before state changes. Processing a
page creates a copy of the current Store snapshot, applies upserts, applies
deletes, and finally installs the returned cursor. That complete snapshot is
written once. In-memory state is replaced only after `async_save` returns.

The cursor loop starts at the profile's persisted cursor. Only a profile with no
stored cursor starts at `(0, "0")`. It never uses a profile timestamp. Each cycle
is limited to ten pages and stops on `finish_flag`, a stalled cursor, a repeated
cursor, a repeated page, a schema error, or an API error.

The coordinator still publishes only one latest measurement per profile.
Historical records are not exposed as entities and are not written to Recorder
or statistics. The temporary manual probe remains isolated and is not invoked by
the coordinator.

## Remaining uncertainty

The live accounts did not require multiple pages, so real multi-page batch-limit
behavior remains covered by deterministic tests rather than live observation.
The maximum long-term Store size and an optional retention policy remain to be
evaluated after measuring larger histories. Websocket history access and
external statistics are intentionally outside this implementation phase.
