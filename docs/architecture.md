# Architecture

Status: foundation only. This document distinguishes intended architecture from
implemented behavior; the [project plan](PLAN.md) is the detailed roadmap.

## Implemented

- Installable `src/stridelog` package and version-only Typer entry point.
- Privacy checks, synthetic tests and development/CI configuration.

## Planned data flow

Garmin source interface -> immutable raw archive -> typed parsers -> SQLite ->
Polars analytics -> local FastAPI -> React/TypeScript.

The archive must allow offline rebuilding. Imported/calculated tables must remain
separate from user annotations, which rebuilds never delete. Save data in SI units
and UTC with its local offset and date. The API binds only to 127.0.0.1.
Notebooks and the CLI stay thin clients of the library.

Phase 1 must verify Personal API behavior, FIT fields and licensing before the
corresponding adapters or schema are implemented. Do not infer sensor identity
with certainty from incomplete FIT metadata.

## Open decisions

- Versioned JSON refreshes must preserve old raw responses; the fixed paths in the
  draft plan cannot both be overwritten and remain immutable. Resolve in Phase 2.
- External map tiles conflict with Garmin-only outgoing requests and can reveal
  viewed locations. Resolve explicitly before Phase 6; no external maps yet.
- Database relationships must permit rebuilds without cascading into annotations.
  Decide and test the rebuild transaction strategy in Phase 3.

See [ADRs](adr/0001-record-architecture-decisions.md) for accepted and provisional
decisions. Detailed schema and metrics documentation arrive in Phases 3 and 4.
