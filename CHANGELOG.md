# Changelog

All notable changes are recorded here, following Keep a Changelog and Semantic
Versioning. No release has been published.

## [Unreleased]

### Added

- Phase 3 typed measurement/user-annotation migration and FIT parser boundary,
  synthetic Encoder fixtures, normalized units and conservative HR provenance.
  Final real-archive parser acceptance remains pending.
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
- Fake-source and real-client/mocked-transport acceptance checks; no live account
  ingestion or FIT interpretation is included.
- Phase 2 automatic `.env` settings, strict private-date and storage validation,
  local `doctor`/`status` commands and expiry warnings without authentication.
- SQLAlchemy operations tables and packaged Alembic initialization, SQLite WAL,
  foreign keys and synthetic migration/persistence/privacy checks.
- Final saved-response schema evidence and approved timeboxed discovery closeout:
  Personal API accepted for raw ingestion; FIT parser decision remains Phase 3.
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

- FIT notebook projection now includes ANT+ and Bluetooth LE device-type aliases
  while retaining raw ANT metadata, without inferring armband identity.
- FIT notebook field-name projection handles unmapped numeric keys without
  mixing them into string sorting; a synthetic decoder regression covers it.
- Cadence normalization guidance now doubles the fractional contribution too,
  without adding a parser or changing the owner's executed notebook.
