# ADR-0003: Raw-first archive and rebuildable SQLite

Status: Accepted

## Context

Downloaded data must remain reproducible without a service or repeat downloads.

## Decision

Archive original responses before parsing and use one SQLite database. Keep
operational state and user entries separate from imported and derived tables.
Default storage is outside the repository.

## Consequences

Use checksums and atomic writes. Resolve raw JSON versioning in Phase 2; never
overwrite an archived original. Test that rebuilds preserve annotations in Phase 3.
