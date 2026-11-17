# ADR-0005: Polars analytics

Status: Accepted

## Context

Transparent running metrics need efficient, testable time-series transformations.

## Decision

Use Polars in the analytics library; document formulas and validate known answers
and relevant properties. Add the dependency when analytics implementation begins.

## Consequences

Keep calculations independent of CLI, API and notebook code. No second analytical
storage engine unless measurements justify it.
