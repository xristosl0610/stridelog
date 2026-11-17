# Personal API discovery findings

Status: Phase 1 in progress; public-source checks and owner-reported authentication success.
Verified: 2026-11-17.
Milestone: [Phase 1 - Discovery spike](https://github.com/xristosl0610/stridelog/milestone/2).

## Evidence and scope

This document separates independently checked public facts from owner-reported
private checks. The assistant has not read any key, token cache, account
response or real FIT file.
Neither ADR-0002 nor ADR-0004 is ready for acceptance. Ingestion remains blocked
until the [Phase 1 checklist](../PLAN.md#13-phase-1-verification-checklist) is
resolved.

Sources:

- [Official Personal API overview](https://developer.garmin.com/gc-developer-program/personal/personal-api/):
  key creation and token exchange.
- [Official rendered Swagger page](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/):
  endpoint listings and documented range limits, checked in the browser.
  The HTML-only view does not expose the endpoint documentation.
- [Published client 1.0.0](https://pypi.org/project/garmin-connect-personal-api-python/1.0.0/):
  package metadata, installed Python source and CLI help.
- [Upstream client revision](https://github.com/garmin/connect-personal-api-python/tree/979e6e9fc58bcbf968611509b634ba734d6f8cdf):
  a separate source of newer interfaces, not the contents of the PyPI release.
- [Published FIT SDK 21.221.0](https://pypi.org/project/garmin-fit-sdk/21.221.0/)
  and [upstream revision](https://github.com/garmin/fit-python-sdk/tree/d413e1ccef7b56e59dbd84eb547fa73b5caee282):
  public package metadata, interface declarations and license only.

No Garmin documentation, SDK source or OpenAPI specification is copied into
the repository. Descriptions below are project research notes.

## Published client and reproducible checks

Client 1.0.0 requires Python >=3.12 and declares Apache-2.0 licensing. Its
runtime dependency is requests; interactive mode is optional and not needed.
These commands passed on Python 3.14.2 without authentication:

```powershell
python -m uv tool run --from garmin-connect-personal-api-python==1.0.0 gc-personal --help
python -m uv tool run --from garmin-connect-personal-api-python==1.0.0 gc-personal activities --help
python -m uv tool run --from garmin-connect-personal-api-python==1.0.0 gc-personal activity-download --help
```

The tool environment is separate from stridelog's dependencies. Neither
`pyproject.toml` nor `uv.lock` changed. These commands exercise help, not network
access to Garmin or Python 3.14 compatibility of authenticated operations.

Important release differences:

| Capability | Published 1.0.0 | Checked upstream revision |
| --- | --- | --- |
| Activity types convenience method / CLI command | Absent | Present |
| Daily VO2 max convenience method / CLI command | Absent | Present |
| Generic authenticated `get(path, params=...)` | Present | Present |
| Search, details, ZIP download and core wellness wrappers | Present | Present |

Do not invoke `activity-types` or `vo2-max` with the pinned 1.0.0 CLI. A later
approved discovery step can use its generic GET interface for documented paths;
there is no need to install an unpinned Git revision.

## Documented API behavior, not account observations

The official overview confirms the host `personal.connectapi.garmin.com` and
an API-key-to-token POST exchange. The plan's approximately 24-hour lifetime is
an earlier research expectation, not an account observation established here.
The account-issued expiry is still unverified; cache decisions must use the
issued `exp` claim, not a hard-coded 24 hours.

The current Swagger page lists both activity types and daily VO2 max. Earlier
plan notes describing them as missing from the specification are superseded.
Being documented does not establish account access, returned data or history.

| Dataset | Documented query / range information | Still to verify locally |
| --- | --- | --- |
| Activity search | `start` defaults to 0; `limit` defaults to 99; date filters use local activity start dates | Maximum accepted page size, pagination stability, running type selection and history coverage |
| Daily summaries | Up to 1 year | Inclusive boundaries, actual cap, earliest data and field completeness |
| Sleep summaries | Up to 31 days | Inclusive boundaries, actual cap, history and optional fields |
| HRV summaries | Date-range path is listed; no cap established in this review | Cap, history and whether the account returns data |
| Body Battery | Up to 31 days | Cap, history and whether daily summaries already suffice |
| Steps | Up to 28 days | Cap, history and whether daily summaries already suffice |
| Stress | Up to 28 days | Cap, history and whether daily summaries already suffice |
| Heart-rate zones | Endpoint listed | Per-sport structure and which profile settings are available |
| Daily VO2 max | Endpoint listed | Successful access, empty result or error; no assumed availability |

The search default of 99 is not a verified maximum. The CLI instead defaults
to 20. Do not turn either default into a pagination limit assumption.
Similarly, "1 year" is not evidence for a particular inclusive day count.

The released daily-summary wrapper documents an object containing a `data`
array, even for one day. Confirm this against a private response before writing
models; other wrapper return annotations allow arbitrary JSON.

## Credential, cache and error handling

Inspection of released client 1.0.0 establishes:

- Key precedence is explicit argument, explicit key file, environment variable
  `GARMIN_PERSONAL_API_KEY`, then the default key file. Invalid explicit sources
  fail instead of silently falling back.
- The default key file is under the user's profile at
  `.config\garmin\connect-personal-api-key`; the default bearer cache is
  `.config\garmin\connect-personal-api-bearer-token.json`.
- The cache contains a plain-text bearer token and cannot be disabled through
  the documented interface. Its location can be overridden. It is reused for
  the same key/base URL when more than an hour remains; otherwise a token
  exchange occurs. This refresh window is not the token's lifetime.
- The client allows a base-URL override through
  `GARMIN_PERSONAL_API_BASE_URL`. Before real requests, verify locally that it
  is unset or points to the exact official HTTPS origin; never send a real key
  to a test host.
- Windows file-permission protection needs an explicit local ACL review; the
  client's POSIX permission checks do not establish Windows protection.
- `--quiet` suppresses ordinary request logging, not JSON output or failures.
  Normal request logs include paths/query parameters; exceptions can include
  response bodies. Neither stream is safe to send to chat, CI or issue comments.
- The default requests session has no application-level request pacing or
  configured retry/backoff policy. A custom session can be supplied. Phase 2
  must implement the approved pacing and retry behavior rather than assume the
  client already provides it.

These are source observations, not live 401/404/429 observations. Never provoke
rate limiting or invalidate a working key just to fill the checklist.

## FIT SDK evaluation gate

The public package metadata declares Python >=3.6 and
`LicenseRef-FIT-Protocol-License-Agreement`, not MIT or Apache-2.0.
The upstream package exports Decoder, Stream and Encoder and declares
`py.typed` / stub package data. These declarations alone do not prove complete
strict typing, successful synthetic encoding or Python 3.14 runtime behavior.

Review the [FIT Protocol License](https://github.com/garmin/fit-python-sdk/blob/d413e1ccef7b56e59dbd84eb547fa73b5caee282/LICENSE.txt)
before installing/executing the SDK. It contains use, redistribution and
benchmarking restrictions. The project's intended approach remains normal
dependency installation without vendoring or bundling; this is not a legal
compatibility determination. No SDK installation, execution, parser comparison
or sample inspection was performed in this check.

The owner subsequently confirmed reviewing the Personal API and FIT SDK terms
and approved the planned local use. This records the owner's confirmation, not
an independent legal assessment. Private discovery will use owner-run commands;
only structural conclusions will be shared.

## Private verification remaining

The owner confirms terms review, private-folder permission setup and a
successful one-activity search command with released client 1.0.0. This verifies
the basic authentication/request path only: response contents, pagination,
history, other endpoints and token timing remain unverified. Keep personal
values and raw evidence outside Git and chat; publish structural conclusions
only.

| Checklist area | Required evidence |
| --- | --- |
| Search and history | Accepted page-size boundary; private count and oldest-date validation; type keys and activity-types access |
| Activity metadata | Race flag in search/details, update timestamp, summary metrics and whether details are necessary |
| Download | ZIP member structure, FIT member count and approximate file-size range without private filenames |
| Wellness | Observed range caps/history, available fields, HRV presence and VO2 max result |
| Zones | Response structure and per-sport settings; actual zone/HR values stay private |
| FIT messages | Four representative samples; message/field presence and sampling-interval conclusion |
| FIT sensors | Classification evidence without serial numbers; explicitly note absent or ambiguous sensor metadata |
| FIT timing and units | Cadence scaling, elevation source/precision, lap and pause events, and offset handling |
| HTTP behavior | Status/structure observations and any naturally encountered rate-limit headers under paced discovery |
| Token timing | Locally checked lifetime only; never publish tokens, payloads or exact expiry |
| Terms | Owner confirms review and approval of planned local use and private-folder permission setup; no copied terms. Private expiry reminder still needs confirmation |
| SDK feasibility | Terms approved; strict-typing evaluation and a synthetic encoding/decoding check remain pending |

### Next local session

1. Confirm the expiry reminder is managed privately. The owner has already
   confirmed reviewing the Personal API and FIT SDK terms for planned local use.
2. Keep using the protected folder outside the repository for the cache and
   responses. The owner selected an ignored local `.env` for credentials.
   Review that file's permissions locally too. Do not search the machine for
   credentials or use a key as a CLI argument.
3. Run only explicitly agreed discovery requests, no more than one per second,
   with all response/error output kept in that private location. Inspect locally,
   not through tools that would return raw data into the conversation.
4. Record field names, shapes, observed limits and unresolved items here.
   Keep account totals/dates, identifiers, actual measurements and locations private.
5. Prepare an output-free sample-inspection notebook when the SDK/local workflow
   is agreed. Accept the ADRs only after the remaining evidence supports them,
   then obtain a separate Phase 2 implementation-plan approval.

### Windows private-folder setup (owner-run)

Run this in your own PowerShell terminal, not through an assistant tool. It
creates a new folder outside the repository and restricts its inherited access.
No key is read and no request is made. Keep the same terminal for later steps.

```powershell
$ErrorActionPreference = 'Stop'
$root = Join-Path $HOME '.stridelog'
New-Item -ItemType Directory -Path $root -Force | Out-Null
$private = Join-Path $root ('discovery-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $private | Out-Null
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls $private /inheritance:r /grant:r "*${sid}:(OI)(CI)F"
if ($LASTEXITCODE -ne 0) { throw 'Private-folder permission setup failed; stop here.' }
icacls $private
if ($LASTEXITCODE -ne 0) { throw 'Private-folder permission verification failed.' }
```

Inspect the final ACL locally: the newly created directory should grant only
your current user's SID full control, inherited by files and subdirectories,
with no broad user/group access. If that is not the result, stop and resolve it
before saving credentials or responses. A unique fresh directory avoids
retaining explicit grants from an existing folder. These ACLs do not isolate
data from administrators, corporate monitoring or backups.

Check the key expiry privately in Garmin Connect and add a calendar reminder
to renew it at least 14 days before expiry. Do not share the date, ACL listing
or folder path; report only whether setup and the reminder are complete.

### Credential loading and the first private request (owner-run)

The local `.env` needs only `GARMIN_PERSONAL_API_KEY=your_actual_key_here`,
with the placeholder replaced privately. Never replace an existing key with the
empty value from `.env.example`. The local `.env` is ignored and untracked;
do not force-add it. File permissions still matter even when Git ignores it.

PowerShell does not automatically load `.env`. Therefore
`Test-Path Env:GARMIN_PERSONAL_API_KEY` can return `False` even when the file is
correct. Use uv's explicit `--env-file .env` option instead; no manual export or
new dotenv dependency is needed. The child process gets the variable without
changing the parent PowerShell environment.

Run from the repository root in the terminal that holds `$private`. The
explicit Python path below is the verified global installation on this Windows
setup; on another machine use the approved Python installation containing uv.
VS Code's activated project Python does not necessarily contain uv, and the
older uv executable on PATH is not the verified installation.

```powershell
& 'C:\Python314\python.exe' -m uv run --isolated --no-project --env-file .env `
  --with garmin-connect-personal-api-python==1.0.0 `
  gc-personal --quiet `
  --bearer-token-cache-file "$private\bearer-token.json" `
  activities --start 0 --limit 1 `
  1> "$private\activities.json" `
  2> "$private\request-errors.txt"

if ($LASTEXITCODE -eq 0) {
    Write-Output "API check succeeded."
} else {
    Write-Output "API check failed. Inspect request-errors.txt locally; do not paste it."
}
```

The owner reports success with this command. An earlier invocation failed
locally because the project Python could not import uv; that was not a Garmin
authentication failure. The assistant verified the global uv version (0.13.9)
and isolated client version (1.0.0) without loading `.env` or contacting Garmin.
No project dependencies changed. Further requests should remain explicitly
agreed, paced and private.
