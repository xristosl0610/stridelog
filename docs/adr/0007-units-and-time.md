# ADR-0007: SI units and UTC storage

Status: Accepted

## Context

Metrics and daily aggregation must not depend on display units or machine timezone.

## Decision

Store SI units and UTC timestamps, plus original local offset and local date.
Include units in column names and convert only at input/display boundaries.

## Consequences

Explicitly test pauses, midnight, travel and daylight-saving transitions when
parsing and aggregating are implemented. Display metric units initially.
