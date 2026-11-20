# Changelog

All notable changes are recorded here, following Keep a Changelog and Semantic
Versioning.

## [Unreleased]

### Added

- Phase 5 local FastAPI endpoints, synthetic coverage, offline Swagger UI,
  OpenAPI contract export and the `stridelog serve` command.

## [0.2.0] - 2026-11-18

### Added

- Phase 4 local running analytics, dated athlete profiles, annotations,
  cached activity metrics, daily fitness and recovery series, and automatic
  post-sync analysis, with synthetic tests and documented metric limits.
- Output-free validation notebooks with pace displays, per-activity
  best-effort comparisons, and separately labelled lap-based marathon
  estimates when sampled efforts are unavailable.

### Changed

- Distance interpolation for splits and best efforts permits gaps up to ten
  seconds; other metrics retain the five-second limit. Incomplete streams no
  longer produce misleading final partial splits.

## [0.1.0] - 2026-11-18

### Added

- Phase 3 typed measurement/user-annotation migration and FIT parser boundary,
  synthetic Encoder fixtures, normalized units and conservative HR provenance.
  Owner-reported real-archive rebuild and spot-check acceptance is complete.
- Offline transactional `rebuild` with annotation/operations/raw preservation,
  checksum provenance, repeat-result fingerprints and recorded runtime.
- Private `dq-report`, per-input failure reasons, immutable-original-preserving
  quarantine copies and heuristic HR/GPS/total/sensor checks. Unverified populated
  JSON schemas fail explicitly rather than producing fabricated measurements.
- Phase 2 official Personal API adapter with paced attempts, bounded retries,
  `Retry-After`, one-refresh authentication recovery and atomic bearer caching.
- Running-only raw activity sync, one-day daily/sleep/HRV requests, current
  profiles, recent lookbacks and explicit older-history reconciliation.
- Atomic/checksummed archival, immutable original ZIPs and JSON content versions,
  durable progress, process locking, interruption recovery and no-I/O dry-run.
- Fake-source and real-client/mocked-transport acceptance checks; tests do not
  access live accounts or real FIT data.
- Phase 2 automatic `.env` settings, strict private-date and storage validation,
  local `doctor`/`status` commands and expiry warnings without authentication.
- SQLAlchemy operations tables and packaged Alembic initialization, SQLite WAL,
  foreign keys and synthetic migration/persistence/privacy checks.
- Final saved-response schema evidence and approved timeboxed discovery closeout:
  Personal API accepted for raw ingestion; FIT parsing accepted in Phase 3.
- Python 3.14 package with a version-only CLI and synthetic smoke/privacy tests.
- Locked development environment, strict typing configuration, linting and coverage.
- Privacy hooks, Windows/Linux CI configuration and dependency update automation.
- Foundation documentation and initial architecture decisions.
- Phase 1 discovery findings separating published client behavior, documented
  API limits and pending private verification; verified workspace rename.
- Owner-reported activity API field structures and their implications for metric
  mapping, time zones and incremental edit detection.
- One-day wellness response structures and synthetic FIT SDK feasibility
  findings, including integrity-scan stream handling.
- Approved private expiry-date configuration and provenance-labelled armband
  fallback policy for future settings/classification, without external reminders.
- Output-free local FIT discovery notebook with synthetic validation and
  structural/model-only reporting for owner-run sample inspection.
- Owner-run four-sample FIT structural findings, including ANT+/Bluetooth LE
  distinctions, variable timestamp intervals and explicit source/typing/unit
  verification limits.
- Repeatable isolated FIT discovery checks, strict SDK-boundary typing
  verification and a bounded checklist for remaining owner-run evidence.
- Confirmed, owner-run API discovery helper with `.env` loading, protected local
  response storage, allowlisted structural reporting and offline transport/privacy
  checks; no ingestion or application dependencies.
- Owner-reported successful ten-probe API batch, disjoint search pages,
  known-race details and marker format, endpoint response categories and broad
  token-timing band, with projection limits and remaining Phase 1 gates explicit.
- Read-only offline projection of three saved API responses, using verified
  public catalog/VO2/zones field names without credential access or HTTP calls.
- Synthetic FIT scaling, altitude-component, lap/timer and UTC/local timestamp
  findings, kept separate from unresolved real-file validation.

### Fixed

- Daily-summary steps now map the documented nested `movement.steps.value`
  count rather than treating the entire object as numeric and rejecting the day.
  Synthetic rebuild regressions cover real-shaped steps, missing/null counts,
  zero and invalid nested values; raw archives need no re-download.
- FIT notebook projection now includes ANT+ and Bluetooth LE device-type aliases
  while retaining raw ANT metadata, without inferring armband identity.
- FIT notebook field-name projection handles unmapped numeric keys without
  mixing them into string sorting; a synthetic decoder regression covers it.
- Cadence normalization guidance now doubles the fractional contribution too,
  without adding a parser or changing the owner's executed notebook.
