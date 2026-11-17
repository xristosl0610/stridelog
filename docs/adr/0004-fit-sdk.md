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
