# stridelog

Local-first running analytics for Garmin data. Planned features include a
rebuildable local archive, transparent running metrics and an interactive web app.

**Status:** Phase 2 foundations: automatic `.env` settings, operational database
migrations, `doctor` and `status`. Sync, analytics and the web app are not
available yet. See the [plan](docs/PLAN.md).

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

## Privacy

The application is designed for one user, on one machine. Storage defaults
to `~/.stridelog`, outside this repository. No telemetry or hosted services are
planned. Only Garmin requests are needed for sync. Future external map tiles
require an explicit privacy decision before implementation.

Never put API keys, tokens, health/location data or real activity files in Git,
issues, pull requests or chat. No Garmin key is required for tests. On managed
devices, obtain employer permission for code ownership, personal data storage,
personal GitHub access and Copilot use first.

## Roadmap and license

See the [roadmap](docs/PLAN.md#10-phased-roadmap), [architecture](docs/architecture.md)
and [architecture decisions](docs/adr/0001-record-architecture-decisions.md).
MIT licensed; dependencies retain their own licenses.

stridelog is independent and is not affiliated with Garmin or Strava. Garmin,
Garmin Connect and Forerunner are trademarks of Garmin Ltd. or its subsidiaries.
Strava is a trademark of Strava, Inc.
