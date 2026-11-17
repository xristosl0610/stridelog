# ADR-0006: Backend-first API and web application

Status: Accepted

## Context

Python is available; local Node.js is not approved/available yet.

## Decision

Build the Python library and local FastAPI contract before React and TypeScript.
Use notebooks for visual checks, not a throwaway alternative application.
Revisit frontend tooling at Gate G1. Never bypass installation restrictions.

## Consequences

The installed app eventually serves prebuilt static assets without Node.js.
Select chart/UI/router libraries in the Phase 6 ADR. Resolve map privacy first.
