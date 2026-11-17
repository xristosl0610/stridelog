# Typed storage

Phase 3 measurements share the operational SQLite database. Migration
`0002_measurements` preserves sync cursors, runs and the checksum manifest.
No analytics/derived-load tables are introduced before Phase 4.

## Tables and provenance

| Table | Key | Contents |
| --- | --- | --- |
| `activity` | Garmin activity ID | Name, type/event/race flag, FIT start and totals, start/end offsets, local start date, HR source/origin, quality flags, input-path/checksum mapping, parser version, allowlisted Garmin metrics |
| `activity_record` | Activity ID, record index | UTC timestamp, distance, coordinates, altitude, speed, HR and cadence |
| `activity_lap` | Activity ID, lap index | UTC start/end, distance, elapsed/timer durations, average HR/cadence, intensity and trigger |
| `activity_sensor` | Activity ID, sensor index | Deduplicated protocol/type/manufacturer/product/name metadata, never serial numbers |
| `timer_event` | Activity ID, event index | UTC timestamp, timer event type and trigger |
| `activity_annotation` | Activity ID | Race override/name/time, exclusion, invalid-HR flag and notes |
| `daily_wellness` | Local date | Resting HR, steps, stress average and Body Battery high/low |
| `sleep_night` | Local date | Total/deep/light/REM/awake seconds and optional score |
| `hrv_night` | Local date | Optional last-night average in milliseconds |
| `zone_snapshot` | Input checksum, sport | Training method, five HR floors, max/resting/threshold HR, raw path and observation timestamp |
| `quality_issue` | Dataset, source key, code | Fixed-code private import failures and quality warnings |

Wellness rows carry raw path and SHA-256. Activity provenance covers summary,
details and original ZIP. Zone snapshots retain content history, not an invented
historical effective date. User annotations deliberately have no foreign key to
rebuildable activities: an unavailable/corrupt activity must not delete user input.
Do not treat absence of a parsed activity as permission to remove its annotation.

## Normalization

- Distances and elevation: metres; speed: metres/second; durations: seconds.
- Coordinates: FIT semicircles converted to degrees. Missing GPS stays null.
- UTC instants: explicit ISO-8601 text with `+00:00`, not naive SQLite datetimes.
- Start offset/date come from paired API local/UTC start times; FIT's paired
  activity-end timestamps establish only the end offset. Never copy an end
  offset to the start, particularly across daylight-saving transitions.
- Cadence: `2 * (cadence + fractional_cadence)` steps/min for running records
  and lap/session averages. SDK-decoded values are not scaled twice.
- Prefer explicitly decoded `enhanced_*` fields. Component expansion and HR
  merging are disabled because SDK expansion can overwrite an explicitly encoded
  enhanced value with its legacy counterpart. Compressed-only fields and separate
  HR streams are not synthesized; absence remains explicit.
- Preserve original record/event order and duplicate timestamps using sequence
  keys. Do not resample or invent moving time here.
- Reject unsupported multi-session/non-running FIT rather than assigning all
  records to one running session. Corrupt/unsupported inputs must be reported.

## HR provenance

`none` means no positive recorded HR. Protocol categories alone do not identify
wear location: generic BLE and ANT+ HR remain `unknown`. A single recognized
external model can support `chest_strap` or `armband` with origin `fit`, which
means model evidence in the file, not proof of every sample's physical source.
Conflicting model evidence remains unknown and blocks the date fallback.
Missing external metadata never establishes `wrist`.

The optional inclusive local-date rule yields `armband` with origin
`user_date_rule` only when HR exists and FIT cannot establish the source.
It never overrides contrary or conflicting recognized-model evidence. Exact
identity and real-watch normalization remain subject to owner spot checks.
