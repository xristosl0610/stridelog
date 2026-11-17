# ADR-0004: FIT decoding with Garmin's SDK

Status: Proposed; acceptance deferred to Phase 3 parser validation

## Context

Laps, timer events, samples and sensor metadata come from original FIT files.

## Decision

Evaluate garmin-fit-sdk against representative files, its typing, current license
and synthetic encoding support before accepting it as the parser dependency.
License review, four owner-run structural reports and synthetic representation
checks are complete. Real-file cadence/elevation/timing and offset/DST behavior
remain unverified. The owner approved transferring those checks to Phase 3
rather than blocking uninterpreted raw ingestion; no production SDK dependency
or HR-source classification is introduced in Phase 2.

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

This is implementation evidence, not final real-file acceptance. Status stays
Proposed until the owner completes rebuild/spot checks and confirms remaining
real-watch unit/timing interpretations. No real files or SDK source are committed.
