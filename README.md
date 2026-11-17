# stridelog

Local-first running analytics for Garmin data. Planned features include a
rebuildable local archive, transparent running metrics and an interactive web app.

**Status:** Phase 0 foundation. Only `stridelog --version` is implemented.
Sync, analytics and the web app are not available yet. See the [plan](docs/PLAN.md).

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

## Privacy

The application is designed for one user, on one machine. Planned storage defaults
to `~/.stridelog`, outside this repository. No telemetry or hosted services are
planned. Only Garmin requests are needed for sync. Future external map tiles
require an explicit privacy decision before implementation.

Never put API keys, tokens, health/location data or real activity files in Git,
issues, pull requests or chat. No Garmin key is required for Phase 0. On managed
devices, obtain employer permission for code ownership, personal data storage,
personal GitHub access and Copilot use first.

## Roadmap and license

See the [roadmap](docs/PLAN.md#10-phased-roadmap), [architecture](docs/architecture.md)
and [architecture decisions](docs/adr/0001-record-architecture-decisions.md).
MIT licensed; dependencies retain their own licenses.

stridelog is independent and is not affiliated with Garmin or Strava. Garmin,
Garmin Connect and Forerunner are trademarks of Garmin Ltd. or its subsidiaries.
Strava is a trademark of Strava, Inc.
