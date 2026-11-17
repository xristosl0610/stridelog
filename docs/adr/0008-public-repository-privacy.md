# ADR-0008: Public MIT repository with privacy controls

Status: Accepted; publishing awaits explicit confirmation

## Context

The project needs a public source-code workflow without publishing credentials,
real activity files or personal health and location data.

## Decision

Use a personal public MIT repository with repository-local no-reply commit
identity, privacy hooks and CI. Confirm owner and authentication before any push.
Keep real data and credentials outside Git and leave global commit identity unchanged.

## Consequences

Public source code does not make private local data suitable for publication.
Account security controls and protected main must be verified after publishing;
configuration files alone do not prove these controls are enabled.
