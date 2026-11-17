# ADR-0002: Garmin Connect Personal API

Status: Accepted for Phase 2 raw ingestion

## Context

The project needs running and wellness data without storing a Garmin password.

## Decision

Use the official Personal API behind a GarminSource interface. The owner
confirmed terms review and authentication; bounded search/details/wellness
requests and saved-response projections establish enough structure for raw
archival. The owner approved ending the discovery timebox and starting Phase 2.

Use activity pages of 20, at least one second between requests, one-day wellness
chunks and recent-lookback detail refreshes. An explicit older `--since`
reconciles older edits; a recent lookback cannot detect arbitrary old edits.
Full-history coverage, live retry/error behavior, exact limits and marker
semantics remain unverified and transfer to Phase 2 acceptance, not claimed as
passed. Preserve original FIT ZIPs without interpretation.

## Consequences

No unofficial sign-in fallback. Keep keys outside Git and logs; never request a
key in chat. Account data remains local and is not part of the findings document.
See the [findings closeout](../research/personal-api-findings.md#approved-discovery-closeout)
for evidence and deferrals. FIT decoding remains a separate Proposed decision.
