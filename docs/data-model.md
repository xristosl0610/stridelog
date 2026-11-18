# Typed storage

Phase 3 measurements share the operational SQLite database. Migration
`0002_measurements` preserves sync cursors, runs and the checksum manifest.
Phase 4 migration `0003_analytics` adds dated athlete inputs and derived metric
caches; analytics rows are never treated as source data.

## Tables and provenance

| Table | Key | Contents |
| --- | --- | --- |
| `activity` | Garmin activity ID | Name, type/event/race flag, FIT start and totals, start/end offsets, local start date, HR source/origin, quality flags, input-path/checksum mapping, parser version, allowlisted Garmin metrics |
| `activity_record` | Activity ID, record index | UTC timestamp, distance, coordinates, altitude, speed, HR and cadence |
| `activity_lap` | Activity ID, lap index | UTC start/end, distance, elapsed/timer durations, average HR/cadence, intensity and trigger |
| `activity_sensor` | Activity ID, sensor index | Deduplicated protocol/type/manufacturer/product/name metadata, never serial numbers |
| `timer_event` | Activity ID, event index | UTC timestamp, timer event type and trigger |
| `activity_annotation` | Activity ID | Race override/name/time, exclusion, invalid-HR flag, explicit steady-run flag and notes |
| `daily_wellness` | Local date | Resting HR, steps, stress average and Body Battery high/low |
| `sleep_night` | Local date | Total/deep/light/REM/awake seconds and optional score |
| `hrv_night` | Local date | Optional last-night average in milliseconds |
| `zone_snapshot` | Input checksum, sport | Training method, five HR floors, max/resting/threshold HR, raw path and observation timestamp |
| `quality_issue` | Dataset, source key, code | Fixed-code private import failures and quality warnings |
| `athlete_profile` | Effective local date | Optional heart-rate inputs, TRIMP constant selection and explicitly dated zone floors |
| `activity_analytics` | Activity ID | Derived metrics and source/profile signature used to invalidate cached per-run results |
| `daily_analytics` | Local date | Recomputed load and wellness time series |

Wellness rows carry raw path and SHA-256. Activity provenance covers summary,
details and original ZIP. Zone snapshots retain content history, not an invented
historical effective date. User annotations deliberately have no foreign key to
rebuildable activities: an unavailable/corrupt activity must not delete user input.
Do not treat absence of a parsed activity as permission to remove its annotation.
Athlete profiles are also user-owned. Per-activity analytics deliberately survive
the measurement-table replacement so source signatures can avoid recomputing
unchanged runs; `analyze` removes cache rows for activities no longer present.

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
Named Garmin HRM product enums from the SDK are recognized alongside explicit
product names; numeric model IDs are not independently guessed.
Conflicting model evidence remains unknown and blocks the date fallback.
Missing external metadata never establishes `wrist`.

The optional inclusive local-date rule yields `armband` with origin
`user_date_rule` only when HR exists and FIT cannot establish the source.
It never overrides contrary or conflicting recognized-model evidence. Exact
identity and real-watch normalization remain subject to owner spot checks.

## Import and quality contract

`rebuild` verifies manifest paths, sizes and checksums, and uses current activity
and wellness JSON, not superseded content versions. All zone versions become
content-addressed snapshots. A single transaction replaces measurements and
quality findings; operational tables and annotations are never cleared. Original
ZIPs remain immutable. Invalid/unsupported FIT produces a byte-identical quarantine
copy rather than moving the archived original. Storage/SQL failures and interruption
roll back the measurement transaction. Per-input schema/parse failures are stored
as explicit findings and valid inputs still import; the CLI then exits nonzero.

The private quality report lists every imported or rejected activity. The rebuild
report records elapsed time and a deterministic digest of ordered rows in every
rebuildable table, excluding operational history, annotations and report timing.
Repeat comparisons therefore check actual normalized query results.

Mappings use the observed daily `data` array, sleep array, null/empty HRV and
per-sport zones array. Daily steps come from `movement.steps.value`, the actual
count in the public `MovementValueV2DTO` schema, not its goal or distance.
Missing/null counts remain null; an actual zero stays zero. Scalar step containers
and invalid nested values fail explicitly.
A one-day response containing multiple rows or a conflicting
calendar date is rejected rather than arbitrarily selecting a row. Unknown populated
HRV schemas are explicit failures; no guessed HRV field or sleep-score mapping is
introduced. Ambiguous cadence/stride fields in Garmin JSON are not converted;
the normalized cadence comes from FIT. Allowlisted Garmin metrics retain their API
field names in `garmin_metrics`, separate from normalized FIT totals.

Quality flags are screening heuristics, not medical judgments, and never remove
or repair samples automatically:

- HR outside 30-240 bpm; missing/zero HR; changes over 15 bpm/s within five seconds.
- Identical HR for at least 60 seconds with gaps no longer than five seconds.
- Possible cadence lock: HR within 3 bpm of cadence for at least 60 seconds and
  12 successive comparisons, with gaps no longer than five seconds.
- GPS jumps implying over 15 m/s, non-increasing record times, and gaps over 30 s.
- FIT/API distance mismatch over max(10 m, 2%); timer/elapsed mismatch over
  max(2 s, 2%); complete lap-distance sums compared with FIT total distance.
- Missing sensor metadata, unknown HR source and missing paired start offset.

Flags can be false positives, especially during pauses, intentional steady HR
or sparse recording. Review locally; no diagnostic or training recommendation
is inferred.
