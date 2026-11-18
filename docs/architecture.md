# Architecture

Status: raw ingestion and typed storage implemented; real-archive acceptance
reported by the owner. This document distinguishes intended architecture from
implemented behavior; the [project plan](PLAN.md) is the detailed roadmap.

## Implemented

- Installable `src/stridelog` package and thin `--version`, `doctor`, `status` CLI.
- Automatic `.env` configuration and exact-format private date validation.
- SQLite operations tables, WAL/foreign keys and packaged Alembic upgrades;
  `doctor --initialize` prepares storage explicitly without network access.
- Official-client adapter with a shared paced/retrying session, bounded auth
  refresh, official-origin/no-redirect enforcement and atomically promoted cache.
- Incremental running/daily/sleep/HRV ingestion, recent lookbacks, explicit older
  reconciliation, per-dataset progress and process-owned synchronization lock.
- Checksum manifest, immutable originals and content-versioned JSON with atomic
  current views; no-write/no-network dry-run and synthetic failure/resume tests.
- Privacy checks, synthetic tests and development/CI configuration.
- Typed FIT/JSON interpretation, conservative HR provenance, measurement migrations,
  offline transactional `rebuild` and private `dq-report`; see the
  [data model](data-model.md) for units, supported shapes and screening thresholds.
- Output-free owner-run FIT discovery notebook, validated with synthetic inputs;
  this is not the application parser or HR-source classification implementation.

## Data flow (analytics, API and web remain planned)

Garmin source interface -> immutable raw archive -> typed parsers -> SQLite ->
Polars analytics -> local FastAPI -> React/TypeScript.

The archive must allow offline rebuilding. Imported/calculated tables must remain
separate from user annotations, which rebuilds never delete. Save data in SI units
and UTC with its local offset and date. The API binds only to 127.0.0.1.
Notebooks and the CLI stay thin clients of the library.

Phase 1's approved timeboxed evaluation supports raw Personal API ingestion;
remaining history/error checks transfer to Phase 2 acceptance and real-file
FIT interpretation checks to Phase 3. Do not infer sensor identity with
certainty from incomplete FIT metadata.

The approved Phase 3 HR-source policy preserves provenance: a private
`STRIDELOG_HR_ARMBAND_FROM` date can supply a user-assumed armband fallback for
activities with HR and insufficient source evidence, never replacing clear
contrary evidence. Apply it inclusively to the activity's local date. Unknown
source is distinct from wrist HR; no HR is distinct from unknown source.
Rebuild applies this policy and records whether the label came from FIT model
evidence or a user assumption.

The private `STRIDELOG_API_KEY_EXPIRES_ON` setting records actual expiration in
`YYYY-MM-DD` format. `doctor` warns within 14 days of expiry when run;
no external calendar service or unattended notification is implied.

## Raw archive policy

JSON is canonicalized without metric interpretation. Each unique payload is
preserved under `<filename>.versions/<sha256>.json`; fixed filenames are mutable
atomic current views, not the immutable history. Reverting to an earlier payload
updates the current manifest without losing either version. Original ZIPs are
never overwritten or extracted. Status file counts include JSON version copies.

Manifest/progress transactions commit only after file writes. JSON heads left
ahead of the manifest by an interruption can be reconciled against their durable
version; unknown checksum mismatches stop rather than silently overwrite data.
File contents are flushed/fsynced before atomic replacement; POSIX directories
are fsynced afterwards. Hardware/power-loss guarantees are not asserted.
Abrupt process termination may leave ignored temporary files, never manifest
entries or progress for incomplete writes.

Activity cursors advance after all pages, wellness cursors after each complete
day; neither is evidence of full historical coverage until owner acceptance.
An interrupted activity pass may repeat searches while reusing durable originals.
Last completed dates minus configured lookbacks are inclusive; zero still
rechecks the last completed day. Recent lookbacks do not find arbitrary old edits.
Full older reconciliation requires the same explicit `--since` on each retry.

The SDK sees only a disposable bearer-cache staging file; complete cache updates
are promoted atomically through the same file-writing helper used by archival.
Malformed caches fail explicitly, rather than silently treating corruption as a
cache miss. POSIX key/cache files must be owner-only; Windows ACLs remain an
owner setup responsibility. Key/cache presence in doctor is not authentication.

Retry accounting uses urllib3 with at most four retries for transient connection
errors, HTTP 429 and 5xx; backoff and `Retry-After` are honored.
Every attempt shares the configured pacing clock, including token exchange and
one permitted 401 refresh. Redirects and nonofficial origins are rejected;
POST is allowed only for token exchange. Raw upstream errors and request paths
are withheld, and dependency logging is suppressed only during source use.

## Open decisions

- Optional `import-fit` remains a Should task, not part of completed core sync.
- FIT SDK ADR-0004 is accepted for offline parsing with documented limitations;
  individual quality warnings and untested real-watch edge cases remain open.
- External map tiles conflict with Garmin-only outgoing requests and can reveal
  viewed locations. Resolve explicitly before Phase 6; no external maps yet.
- User annotations intentionally have no foreign key into rebuildable activity
  rows. Measurement replacement is transactional and shares the sync lock; storage
  failures/interruption roll back measurements without changing operations or raw
  inputs. Invalid FIT is copied to quarantine, never moved out of the archive.

See [ADRs](adr/0001-record-architecture-decisions.md) for accepted and provisional
decisions. Detailed schema is documented now; metrics documentation remains Phase 4.
