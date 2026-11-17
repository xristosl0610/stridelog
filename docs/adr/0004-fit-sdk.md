# ADR-0004: FIT decoding with Garmin's SDK

Status: Proposed; requires Phase 1 verification

## Context

Laps, timer events, samples and sensor metadata come from original FIT files.

## Decision

Evaluate garmin-fit-sdk against representative files, its typing, current license
and synthetic encoding support before accepting it as the parser dependency.

## Consequences

Keep decoding behind a small parser boundary. Do not vendor or redistribute SDK
source or real activity fixtures. Do not assume every file identifies its HR sensor.
