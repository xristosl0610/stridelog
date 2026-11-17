# ADR-0002: Garmin Connect Personal API

Status: Proposed; requires Phase 1 verification

## Context

The project needs running and wellness data without storing a Garmin password.

## Decision

Prefer the official Personal API behind a GarminSource interface. Verify terms,
authentication, available endpoints, history and date limits using official
documentation and the user's account before implementing the adapter.

## Consequences

No unofficial sign-in fallback. Keep keys outside Git and logs; never request a
key in chat. Account data remains local and is not part of the findings document.
