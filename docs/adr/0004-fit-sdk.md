# ADR-0004: FIT decoding with Garmin's SDK

Status: Accepted for Phase 3 offline FIT parsing

## Context

Laps, timer events, samples and sensor metadata come from original FIT files.

## Decision

Use `garmin-fit-sdk==21.221.0` behind a typed parser boundary for offline FIT
decoding. The owner approved the SDK terms and the runtime dependency.
License review, four owner-run structural reports and synthetic representation
checks are complete. The owner reports successful repeated real-archive rebuilds
and matching Garmin Connect totals for ten selected runs. These are owner-reported
checks, not independent inspection of private files or proof of all real-watch
cadence, elevation, sensor attribution, timing or daylight-saving cases.

## Consequences

Keep decoding behind a small parser boundary. Do not vendor or redistribute SDK
source or real activity fixtures. Do not assume every file identifies its HR sensor.

## Phase 3 implementation evidence

The owner approved SDK 21.221.0 as a runtime dependency. The typed parser,
synthetic Encoder inputs and offline rebuild now exercise SI/cadence conversion,
enhanced-field preference, missing GPS/HR, laps, pauses, paired offsets and
conservative sensor provenance. A synthetic regression showed component expansion
overwriting explicitly encoded enhanced fields; the parser disables expansion
and HR merging rather than silently changing those values. Compressed-only and
separate HR streams are not synthesized.

Owner-reported rebuild and ten-run comparisons complete Phase 3 acceptance.
The checks do not establish compressed-only fields, separate HR streams,
sample-level sensor attribution or all DST boundaries. Those limitations remain
explicit; no real files or SDK source are committed.
