# FITAGE v1.4 external statistics design

The private FITAGE history Store remains canonical. Recorder statistics are an optional, rebuildable dashboard cache. Exact records and timestamps remain available through `fitage/history/query`.

## Consent and lifecycle

`import_history_statistics` defaults to `false`. Enabling it stores derived health measurements in Recorder. Disabling it stops all future import and rebuild work, including already-pending work. Existing Recorder statistics are retained; they are never silently deleted. Re-enabling resumes persisted pending work.
Deselecting a profile also retains its raw history and existing statistics. Removing the complete config entry clears all statistic IDs derived for that entry through Recorder's public full-clear API, then removes the private Store through `Store.async_remove()`. If Recorder is unavailable, the clear times out or fails, or completion is uncertain, the Store and cleanup metadata are retained. An entry whose Store proves that statistics were never imported skips Recorder cleanup and removes the Store directly.

## Hourly projection

Timestamps are converted to UTC and floored to the UTC hour. DST therefore cannot merge or duplicate UTC buckets. Within an hour the maximum `(float(time_stamp), str(measurement_id))` wins. Only `state` is written; `sum` is never populated. Raw history retains every exact timestamp and record.

## Rebuilds and consistency

Each profile bucket contains version-1 statistics metadata with projection fingerprints and pending metric names. It adds no display names, user IDs or measurement values beyond the existing bucket identity and raw records.

A changed raw projection is persisted as pending in the same Store transaction as the raw update/delete, before Recorder is touched. For each pending profile/metric pair:

1. the public full-clear API queues removal of exactly one stable statistic ID;
2. the integration waits for its thread-safe completion callback;
3. the complete current projection is queued through `async_add_external_statistics`;
4. the fingerprint is stored and pending is removed only after validation and enqueue succeed.

Recorder uses one FIFO `SimpleQueue`, so the import is queued after the completed clear. Clear and import are not one atomic Recorder transaction: the graph can temporarily be empty. The raw Store and websocket history remain correct. Clear timeout, clear failure, validation failure, or enqueue failure leaves pending intact for retry on a later update or restart. Once an import job is accepted, Recorder owns its retry behavior.

Unknown delete IDs do not change the raw projection and schedule no rebuild. Only changed metrics within the exact config-entry/profile bucket are affected.

## Metrics

| Metric | Unit | Unit class |
| --- | --- | --- |
| weight | kg | mass |
| bmi | none | unitless |
| bodyfat | % | unitless |
| water | % | unitless |
| muscle | % | unitless |
| bone | kg | mass |
| protein | % | unitless |
| subfat | % | unitless |
| fat_free_weight | kg | mass |
| body_fat_mass | kg | mass |
| body_water_mass | kg | mass |
| protein_mass | kg | mass |
| bmr | kcal | energy |
| score | none | unitless |
| heart_rate | bpm | none |

`visfat`, `bodyage`, `cardiac_index`, segment values and categorical values are excluded because the existing integration does not prove a Recorder-compatible unit/semantic mapping. Home Assistant exposes external `state` columns only for metadata declaring the state/sum capability. FITAGE therefore sets `has_sum` as technical metadata required by the current Core API, writes values only to `state`, and always leaves `sum` empty.

## Cleanup recovery

After an incomplete removal, restore the config entry from a Home Assistant backup while leaving its retained private Store intact. Once Recorder is available, remove the same entry again so FITAGE can retry the idempotent clear with the preserved profile/statistic identities. Manually delete the Store only after that cleanup succeeds or after independently confirming that no derived statistic IDs remain.
