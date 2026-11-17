# stridelog

Local-first running analytics for Garmin data. Planned features include a
rebuildable local archive, transparent running metrics and an interactive web app.

**Status:** Phase 2 core raw ingestion implemented: `.env` settings, migrations,
`doctor`, `status` and resumable `sync`. Full private archive acceptance remains
owner-run. FIT parsing, analytics, `import-fit` and the web app are not available
yet. See the [plan](docs/PLAN.md).

## Development quickstart

Requirements: Python 3.14 and [uv](https://docs.astral.sh/uv/) 0.13 or newer.

```powershell
uv sync --locked
uv run stridelog --version
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

If uv was installed with pip and is not on PATH, use `python -m uv` in place of `uv`.
Strict Pyright runs in CI on Windows and Linux. Local Pyright requires an approved
Node.js installation; do not let its wrapper download Node to bypass device policy.
Pylance uses the same strict settings in VS Code.

For hooks, contributor setup and optional notebooks, see [CONTRIBUTING](CONTRIBUTING.md).

## Local setup

Copy `.env.example` to the ignored `.env` and set `GARMIN_PERSONAL_API_KEY`.
No PowerShell environment exports or extra `--env-file` switches are needed by
application commands. Existing process variables take precedence over `.env`.
Optionally set the actual expiration as
`STRIDELOG_API_KEY_EXPIRES_ON=YYYY-MM-DD`; do not use the creation date.

```powershell
uv run stridelog doctor
uv run stridelog doctor --initialize
uv run stridelog status
```

`doctor` checks local configuration, key/cache presence, schema and disk space;
it never contacts Garmin or authenticates the key. It warns within 14 days of
expiration, including the expiration day; expired keys fail readiness.
Missing keys or an uninitialized database return a nonzero exit code.
`--initialize` explicitly creates storage and applies migrations, without
downloading account data. Repeating it preserves operational records.
`status` reports archived-file/run counts and the last run state, not metrics.
It fails rather than reporting empty success when no current database exists.

The default data folder is `~/.stridelog`; `STRIDELOG_DATA_DIR` must resolve
outside the checkout. Restrict its permissions and those of `.env` yourself,
especially Windows ACLs; directory creation mode alone does not establish a
Windows ACL. Diagnostics never print the key, private dates or storage paths.
The optional armband date is validated now but classification remains Phase 3.

## Raw sync

Your existing `.env` key and private dates are sufficient; no additional
credentials or PowerShell exports are needed.

```powershell
uv run stridelog sync --dry-run
uv run stridelog sync
uv run stridelog status
```

`sync` initializes storage and resumes saved progress automatically. The first
run starts at the plan's January 2025 baseline. Repeat the same command after
an interruption. Use `--since YYYY-MM-DD` to reconcile explicit older history;
repeat that option too when resuming an explicit reconciliation.

- Running keys and their catalog descendants are included. Override defaults
  with `STRIDELOG_RUNNING_ACTIVITY_TYPES` as a JSON array if needed.
- Daily summaries, sleep and HRV use one-day requests; null HRV is preserved.
  Current zones and the type catalog are also archived.
- Defaults look back seven activity days and three wellness days before the last
  completed day, inclusively. Only recent known details are refreshed; arbitrary
  old edits require an explicit older `--since`. Original ZIPs are never replaced.
- HTTP attempts are paced by at least one second, including retries. The initial
  archive can take substantial time: three wellness requests per calendar day,
  plus activity requests. No fixed completion-time estimate is guaranteed.
- `--dry-run` describes scope without opening stored cursors, creating storage,
  loading the credential file, authenticating or making requests. It does not
  predict exact request counts.

Only aggregate completion counts are printed. On checksum/cache corruption,
inspect and repair locally; never share files or raw errors. See the
[archive and recovery contract](docs/architecture.md#raw-archive-policy).
Run an initial sync, a repeat sync and an interruption/resume locally before
Phase 2 acceptance. No assistant-run account ingestion is claimed.

## Privacy

The application is designed for one user, on one machine. Storage defaults
to `~/.stridelog`, outside this repository. No telemetry or hosted services are
planned. Only Garmin requests are needed for sync. Future external map tiles
require an explicit privacy decision before implementation.

Never put API keys, tokens, health/location data or real activity files in Git,
issues, pull requests or chat. No Garmin key is required for tests.

## Roadmap and license

See the [roadmap](docs/PLAN.md#10-phased-roadmap), [architecture](docs/architecture.md)
and [architecture decisions](docs/adr/0001-record-architecture-decisions.md).
MIT licensed; dependencies retain their own licenses.

stridelog is independent and is not affiliated with Garmin or Strava. Garmin,
Garmin Connect and Forerunner are trademarks of Garmin Ltd. or its subsidiaries.
Strava is a trademark of Strava, Inc.
