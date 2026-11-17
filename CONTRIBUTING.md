# Contributing

## Setup

Use Python 3.14 and uv 0.13+. The dependency lockfile is committed.

```powershell
uv sync --locked
uv tool install pre-commit
pre-commit install
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Install the official [Gitleaks](https://github.com/gitleaks/gitleaks#installing)
executable through an approved route and ensure `gitleaks` is on PATH before
committing. The hook uses the system executable to avoid implicitly installing
Go or Docker. It fails closed if Gitleaks is missing. CI scans using the pinned
Gitleaks action independently of the local hook.

If tool executables are not on PATH, use `python -m uv` and the executable
at `%USERPROFILE%\.local\bin\pre-commit.exe`, or add those directories to the
current terminal PATH. Do not change global corporate tooling or credentials.

For the approved workspace-local Gitleaks installation, prepare each PowerShell
terminal before running hooks or committing:

```powershell
$env:PATH = "$PWD\.tools\gitleaks;$env:USERPROFILE\.local\bin;$env:PATH"
```

The ignored executable is local tooling, not part of a clone. Fresh clones need
their own approved Gitleaks installation.

Run `uv run pyright` only when Node.js is already installed through an approved
route. The Python wrapper can otherwise download Node automatically; do not use
that as an installation workaround. Pylance reads the strict settings from
`pyproject.toml`; CI runs Pyright using the hosted runners' Node.js.

Optional notebooks: `uv sync --locked --group notebooks`. Commit no notebook
outputs; the nbstripout hook removes them. All tests must use synthetic data and
must not call Garmin. Real raw data belongs outside the repository.

## Workflow

Get the phase implementation plan approved before multi-file changes. Use a
short-lived branch and a pull request with a Conventional Commit title, then
squash merge after Windows/Linux CI and the secrets check pass.

Before the first commit, configure identity **for this repository only**:

```powershell
git config --local user.name "Your public author name"
git config --local user.email "EXACT_ADDRESS_FROM_GITHUB_SETTINGS"
```

Find the exact no-reply address at GitHub Settings > Emails after enabling
"Keep my email addresses private". Do not guess its numeric account prefix.
Commit identity does not choose authentication: verify your personal account and
the destination owner separately before publishing. See the
[GitHub runbook](docs/PLAN.md#11-git-and-github-runbook).

## Checks

```powershell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pytest
pre-commit run --all-files
```

Strict Pyright is also required in CI. Core package coverage must be at least
85%. Test only newly introduced behavior and relevant edge cases.

The private-file hook blocks data extensions, SQLite sidecars, raw/data/export
folders and credential paths even when force-added. Use Python factories instead
of committed binary fixtures. These guards are not proof that arbitrary JSON,
CSV, text or images are free of personal data: inspect every staged diff.

## Dependency changes

Add only approved dependencies when their phase needs them; run `uv lock` and
include its diff. Phase 0 uses Typer, the development/notebook groups and uv's
standard build backend. The remaining approved runtime stack is deferred.
Third-party actions and hooks are commit-pinned. Keep Ruff's hook version aligned
with the exact project dependency when upgrading it.
