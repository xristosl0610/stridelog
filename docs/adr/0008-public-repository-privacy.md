# ADR-0008: Public MIT repository with privacy controls

Status: Accepted; publishing awaits explicit confirmation

## Context

This is a personal project developed on a managed device. Employer permission
for side-project/IP, personal health/location data, personal GitHub and Copilot
use was confirmed before implementation.

## Decision

Use a personal public MIT repository with repository-local no-reply commit
identity, privacy hooks and CI. Confirm owner and authentication before any push.
Keep real data and credentials outside Git and never change global work identity.

## Consequences

Repository visibility does not establish IP ownership or isolate device data.
Account security controls and protected main must be verified after publishing;
configuration files alone do not prove these controls are enabled.
