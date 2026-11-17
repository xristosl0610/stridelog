# Personal API discovery findings

Status: Phase 1 timebox closed with owner-approved deferrals; Phase 2 approved.
Verified: 2026-11-17.
Milestone: [Phase 1 - Discovery spike](https://github.com/xristosl0610/stridelog/milestone/2).

## Evidence and scope

This document separates independently checked public facts from owner-reported
private checks. The assistant has not read any key, token cache, raw account
response or real FIT file.
ADR-0002 is accepted specifically for raw ingestion. ADR-0004 remains Proposed
until Phase 3 parser validation. The [approved closeout](#approved-discovery-closeout)
supersedes historical discovery gates below; unchecked observations remain
explicitly unverified, not retroactively passed.

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

Do not invoke `activity-types` or `vo2-max` with the pinned 1.0.0 CLI. The
approved discovery helper uses its generic GET interface for documented paths;
the owner-reported batch below confirms access without an unpinned Git revision.

## Published API behavior and verification limits

The official overview confirms the host `personal.connectapi.garmin.com` and
an API-key-to-token POST exchange. The plan's approximately 24-hour lifetime is
an earlier research expectation, not an account observation established here.
The owner-reported batch below establishes only a broad 1-48-hour band from
unverified timing claims. It does not establish exactly 24 hours; cache
decisions must use the issued `exp` claim, not a hard-coded lifetime.

The current Swagger page lists both activity types and daily VO2 max. Earlier
plan notes describing them as missing from the specification are superseded.
Being documented does not establish account access, returned data or history.

| Dataset | Documented query / range information and explicitly labelled owner observations | Still to verify locally |
| --- | --- | --- |
| Activity search | `start` defaults to 0; `limit` defaults to 99; date filters use local activity start dates | Maximum accepted page size, pagination stability, running type selection and history coverage |
| Daily summaries | Up to 1 year | Inclusive boundaries, actual cap, earliest data and field completeness |
| Sleep summaries | Up to 31 days | Inclusive boundaries, actual cap, history and optional fields |
| HRV summaries | Date-range path is listed; no cap established in this review | Cap, history and whether the account returns data |
| Body Battery | Up to 31 days | Cap, history and whether daily summaries already suffice |
| Steps | Up to 28 days | Cap, history and whether daily summaries already suffice |
| Stress | Up to 28 days | Cap, history and whether daily summaries already suffice |
| Heart-rate zones | Endpoint listed; owner batch returned a nonempty array with a string `sport` field | Zone/profile field mapping and per-sport semantics |
| Daily VO2 max | Endpoint listed; owner batch returned a nonempty array of objects, not 404 | Metric field names, units and optional values; omitted projection fields are not absent data |

The search default of 99 is not a verified maximum. The CLI instead defaults
to 20. Do not turn either default into a pagination limit assumption.
Similarly, "1 year" is not evidence for a particular inclusive day count.

The released daily-summary wrapper documents an object containing a `data`
array, even for one day. Owner-reported projections confirm that container;
they are not a complete schema. Other wrapper return annotations allow arbitrary
JSON.

## Owner-reported activity field inspection

The owner inspected a saved search item and its corresponding details response
locally and shared field names only. This is one sample, not a complete schema
or evidence that any particular value is populated. The top-level search
container label was not included in that initial report; the bounded batch
below subsequently confirms arrays, race-details behavior and marker format.

| Area | Observed field names / structure |
| --- | --- |
| Search metrics | `distance`, `duration`, `elapsedDuration`, `movingDuration`, `averageHR`, `maxHR`, `averageSpeed`, `elevationGain`, `elevationLoss`, `elevationCorrected` |
| Search timing | `startTimeGMT`, `startTimeLocal`, `beginTimestamp`, `endTimeGMT`; no obvious last-update field appeared |
| Search classification | `activityType`, `eventType`; nested schemas and race semantics not yet checked |
| Details containers | `summaryDTO`, `activityTypeDTO`, `eventTypeDTO`, `metadataDTO`, `timeZoneUnitDTO` |
| Activity type details | `activityTypeDTO` has `typeId`, `parentTypeId`, `typeKey` |
| Event type details | `eventTypeDTO` has `typeId`, `typeKey`; the later bounded batch confirms `race` for the privately selected known-race details |
| Additional details metrics | `minHR`, `averageMovingSpeed`, `directWorkoutFeel`, `directWorkoutRpe`; presence does not imply non-null values |
| Different metric names | Search uses `averageRunningCadenceInStepsPerMinute`, `maxRunningCadenceInStepsPerMinute`, `avgStrideLength`; details use `averageRunCadence`, `maxRunCadence`, `strideLength` |
| Details metadata | `lastUpdateDate`, `uploadedDate`, `elevationCorrected`, `lapCount`, `sensors` are present |
| Time-zone container | `timeZoneUnitDTO` has `timeZone`; the later bounded batch confirms a string kind, not its value or offset derivation |

Consequences for the next implementation plan:

- Keep details retrieval in scope. Search and details are not interchangeable
  schemas; units and nullability must be verified before mapping similarly named
  metrics.
- `metadataDTO.lastUpdateDate` is a candidate edit marker, found only in the
  details sample. The later batch confirms an ISO datetime string, but not
  whether every relevant edit updates it. Start/end/upload times are not
  substitutes.
- Do not assume summary comparison detects details-only changes. Phase 2 needs
  an explicit detail-refresh/reconciliation policy, including the limits of a
  recent-activity lookback for detecting edits to older activities.
- Search also exposes owner/profile and location fields. Keep them out of logs,
  issue evidence and synthetic fixtures; the owner shared no values.

## Owner-reported wellness field inspection

The owner requested one privately selected date for daily summaries, sleep
summaries and HRV summaries and shared shapes/field names only.

| Dataset | Observed structure |
| --- | --- |
| Daily summaries | Object with a `data` collection; inspected item has `heartRate`, `bodyBattery`, `stress`, `movement`, `intensityMinutes` and other containers |
| Resting heart rate | `heartRate.restingValue`, alongside `minValue` and `maxValue` |
| Body Battery | `chargedValue`, `drainedValue`, `latestValue`, `minValue`, `maxValue`, `featureVersion` |
| Stress | `avgLevel`, `maxLevel`, duration/proportion fields and `qualifier`; duration keys explicitly include `InMillis` |
| Movement | `steps`, `floorsAscended`, `floorsDescended`, `pushes` |
| Intensity minutes | `goal`, `moderate`, `vigorous` |
| Sleep summaries | Array; inspected item has `sleepTimeSeconds`, `deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`, `napTimeSeconds` and GMT/local start/end timestamps |
| HRV summaries | Successful request with JSON `null` for the one tested day |

These are field-presence observations, not measurements, non-null guarantees or
complete endpoint schemas. No sleep-score field appeared in this inspected
sleep-summary item. A single HRV `null` does not prove that the endpoint or device
lacks HRV support; history and response distinctions still need checking.

Daily summaries expose the core containers for resting HR, steps, Body Battery
and stress, so dedicated Body Battery/stress/steps requests are deferred unless
coverage or field validation shows a need. Actual field units, optional values,
date boundaries, range caps and earliest available data remain unverified.

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
The installed release exports Decoder, Stream and Encoder and includes
`py.typed` and `.pyi` files. Stub inspection confirms typed decoder output, but
encoder inputs and several callbacks use dictionaries containing `Any`.
Strict application boundaries still need validation; published stubs are not
proof that every operation is strictly typed.

Review the [FIT Protocol License](https://github.com/garmin/fit-python-sdk/blob/d413e1ccef7b56e59dbd84eb547fa73b5caee282/LICENSE.txt)
before installing/executing the SDK. It contains use, redistribution and
benchmarking restrictions. The project's intended approach remains normal
dependency installation without vendoring or bundling; this is not a legal
compatibility determination.

The owner subsequently confirmed reviewing the Personal API and FIT SDK terms
and approved the planned local use. This records the owner's confirmation, not
an independent legal assessment. Private discovery will use owner-run commands;
only structural conclusions will be shared.

After that approval, an isolated SDK 21.221.0 environment passed a synthetic
in-memory encode/decode probe on Python 3.14.2. The probe checked two record
timestamps, supplied distance/speed/elevation and HR/cadence values, one lap and
one session, and rejection of a deliberately corrupted CRC. No real files,
credentials or Garmin requests were used; no project dependencies changed.
This demonstrates basic synthetic encoding/decoding, not real-watch sensor
coverage, physical cadence conversion or parser completeness.

The first probe exposed an important stream-state detail: calling
`check_integrity()` and then `read()` on the same stream returned no record group
without decode errors. A focused reproduction showed `is_fit()` followed by
`read()` retained records, whereas `check_integrity()` followed by `read()` did
not. Recreating the stream for decoding made the full round-trip pass.
The future parser must rewind/recreate the stream after an integrity scan,
rather than mistake an exhausted stream for a valid empty activity.

Strict Pyright 1.1.414 now passes all notebook code cells and the standalone
synthetic check harness against SDK 21.221.0 on Python 3.14.2: zero errors,
warnings or informational diagnostics. The notebook cells were exported to
ignored scratch space for static analysis; the private-input cell was not run.
This checks the current decoder/projection boundary, not the completeness of
the SDK's annotations. Encoder/callback dictionaries still contain upstream
`Any`; future application models must retain their own typed boundaries.
The installed enum annotations also use camel-case labels such as
`heartRate`/`bluetoothLowEnergy`, while the synthetic decoder returns
`heart_rate`/`bluetooth_low_energy`. The current projection accepts scalar
strings instead of trusting those literal annotations. A future adapter must
validate/normalize runtime enums rather than treating a passing static check
as proof of SDK annotation accuracy. No third-party stubs or source were edited.

An owner-run failure also exposed mixed field-key types: a valid synthetic FIT
record with an unmapped field reproduced integer and string keys, despite
string-only keys implied by the SDK's annotations. Sorting the mixed keys
raised `TypeError`. The helper now accepts iterables of arbitrary keys and
explicitly projects only string field names, still excluding `developer_fields`.
Numeric field IDs are intentionally omitted from the report; originals are
unchanged. A decoder-backed regression covers this case without suppressing
type diagnostics or trusting the inaccurate key annotation.
The owner-run four-sample structural reports are recorded below; real-file
timing and unit semantics still require verification. No parser performance
comparison was performed.

## Synthetic FIT representation checks

A further SDK 21.221.0 probe encoded an entirely synthetic activity in memory:
records, lap/session summaries, timer events and paired activity timestamps.
CRC integrity and fresh-stream default/raw decodes passed. These checks verify
SDK representations, not real-watch recording behavior or measurement accuracy.
No original FIT file or notebook output was read for this probe.

| Area | Verified synthetic behavior and implementation consequence |
| --- | --- |
| Cadence | Default decoding preserves integer cadence and separately scales fractional cadence by 1/128. In the synthetic example, cadence 80 and fractional cadence 0.5 represent 80.5 cycles/min, or `2 * (80 + 0.5) = 161` steps/min under the running stride interpretation. Double the fractional contribution too; do not rescale an already decoded fraction |
| Running summary alias | With `sport=running`, lap/session `avg_running_cadence` aliases the base `avg_cadence` value; it is not already doubled to steps/min. The separate `avg_fractional_cadence` is preserved. Real-file/UI comparison remains pending |
| Altitude | The profile specifies metres with scale/offset handling; default decoding reconstructs the synthetic legacy and enhanced heights. Apply no second scale/offset to decoded values |
| Component expansion | Default decoding adds `enhanced_altitude` from a legacy `altitude` field even when enhanced altitude was not separately encoded. A projected enhanced field is not proof of an independently recorded sensor value, greater physical precision or corrected elevation |
| Laps and duration | A synthetic distance-triggered lap decodes as `lap_trigger=distance`; elapsed and timer durations decode to seconds and retain the intentionally different values. This does not verify the watch's auto-lap setting or actual pause handling |
| Timer events | Synthetic timer `start`/`stop_all` events retain their order and timestamps; data for a manual trigger expands to `timer_trigger=manual`. Auto-pause, missing/repeated events and real recordings remain unverified |
| UTC/local time | Default `timestamp` is a UTC-aware datetime, while activity `local_timestamp` remains an integer in FIT local-epoch seconds. The paired raw timestamps preserve the deliberately encoded offset. Do not treat the local integer as Unix time or obtain its offset from the computer timezone; real-file offset/DST behavior remains pending |

The raw comparison disabled scale/offset application, datetime/type conversion,
subfield/component expansion and heart-rate merging. The SDK rejects disabled
scaling or components while heart-rate merging remains enabled; this was a probe
configuration error, not corrupt FIT data. Default decoding was unaffected.

These are one-time, pinned-SDK feasibility observations, not a production parser
or a replacement for the four real-file timing/unit checks. No SDK source,
profile table or FIT fixture is added to the repository.

## Approved private date policies

The owner reports that the armband is not shown in Garmin's activity sensor
listing despite known use. This is an owner-reported UI observation, not an
independently verified forum finding or proof about the original FIT contents.
The owner has downloaded original sample ZIPs; inspect a run known to use the
armband even if it is not labelled as such in Garmin.

Approved on 2026-11-17:

- Optional `STRIDELOG_HR_ARMBAND_FROM=YYYY-MM-DD` applies inclusively to the
  activity's local date, only when HR exists and FIT cannot establish its source.
  Record `armband` with `user_date_rule` provenance, not sensor confirmation.
  Clear contrary source evidence takes precedence. Missing external-sensor
  metadata is not proof of wrist HR; otherwise retain `unknown`. A run without
  HR remains `none`. Do not infer measurement accuracy from the label.
- `STRIDELOG_API_KEY_EXPIRES_ON=YYYY-MM-DD` stores the actual key expiration
  shown by Garmin, not its creation date. No external calendar or reminder
  service is required. Phase 2 `doctor` warnings start 14 days before expiry
  when the command is run; no warning/notification is implemented yet.
- Keep both real dates in the private ignored `.env`; do not share or log them.
  Date parsing arrives in Phase 2 and HR classification in Phase 3. Discovery
  records the policy without pretending that runtime behavior already exists.

The owner confirms both settings were configured privately and all four
original ZIPs are ready, including a known-armband sample. No real dates were
supplied, and the assistant has not read `.env`. The owner subsequently ran
the notebook locally and shared only the projections below. No ADR is accepted
based on the user-assumed rule.

## Local FIT inspection notebook

[01_fit_discovery.ipynb](../../notebooks/01_fit_discovery.ipynb) is an output-free,
owner-run inspection tool, not the production parser. It prompts for each sample
path at runtime, requires real samples outside the repository, reads raw FIT or
a ZIP containing exactly one FIT member without extraction, and reports:

- Message/field names and whether HR values exist, not physiological values.
- Qualitative timestamp-interval labels, not timestamps, durations or dates.
- Sensor protocol/model metadata only; no serial numbers or private paths.
- An explicit `not_performed` source-classification status. Neither the armband
  date rule nor missing-sensor inference is applied to observed evidence.

The notebook uses a workspace-local ignored discovery kernel with SDK 21.221.0
and ipykernel 7.4.0 (the existing approved notebook dependency's locked version).
It does not load `.env`, contact Garmin, modify originals or change project
dependencies. Clear outputs before saving/committing.

Select the discovery environment by its interpreter path, not merely its Python
version. The application environment also uses Python 3.14 but has no SDK.

Synthetic-only validation passed raw/ZIP report parity, all four prompted
labels, variable/sparse timestamp handling, no-HR inputs, privacy sentinels, and
explicit failures for corruption, missing/unsupported/in-repository inputs and
zero/multiple FIT ZIP members. These synthetic checks are separate from the
owner-reported observations below.

### Synthetic checks and typing result

[check_fit_discovery.py](../../notebooks/check_fit_discovery.py) uses standard
library unittest so the optional SDK stays outside application/test
dependencies. It loads only notebook imports/helpers, never the private-input
cell. Its synthetic fixtures stay in an automatically cleaned subdirectory
under ignored `.tools`; a simulated repository tests the outside-repository
boundary without writing outside the workspace.

```powershell
& .tools\fit-discovery\Scripts\python.exe notebooks\check_fit_discovery.py
```

Five focused checks pass: protocol alias projection with raw ANT retained and
no source classification; raw/ZIP parity with private-value sentinels; explicit
CRC failure; in-repository input rejection; and valid FIT records containing
unmapped numeric field keys. CI runs the same checks on
Windows and Linux in an isolated SDK environment, without adding the SDK to the
application lockfile.

Local strict typing used the installed Pyright JavaScript entry point with
VS Code's existing runtime (`ELECTRON_RUN_AS_NODE=1`), not a newly installed
Node runtime. The check used a scratch strict-mode configuration, exported
notebook code and the discovery interpreter via `--pythonpath`. No SDK source
or generated third-party stubs are copied into the repository.

## Owner-run four-sample FIT structures

The owner supplied the notebook's projected reports for the wrist, strap,
armband and race samples. These are owner-run observations, not an independent
inspection of the originals. All four reports completed with HR values present
and `variable_intervals`; this describes decoded timestamp spacing, not a
verified watch recording setting. Source classification was `not_performed`.

| Sample label | Projected device evidence | Interpretation limit |
| --- | --- | --- |
| Wrist | Local device entries only | Missing external metadata does not prove wrist HR |
| Strap | Local entries plus an `antplus` entry with `device_type=120`, manufacturer `garmin`, product `3299` | Product identity and assignment of HR samples to that device remain unverified |
| Armband | Local entries plus a `bluetooth_low_energy` entry with `device_type=1`, without manufacturer/product in that entry | Unlike the wrist sample, there is a Bluetooth LE entry; it does not identify COROS or prove armband HR |
| Race | Local entries plus the same projected ANT+ type/manufacturer/product as the strap sample | Matching model metadata does not establish a unique physical device or HR-sample provenance |

The armband file therefore differs structurally from the wrist file despite
the owner-reported Garmin UI omission. The approved private date fallback
remains an assumption, not a substitute for missing model/source evidence.
Repeated projected model entries must not be counted as distinct sensors.

Common record fields are `timestamp`, `position_lat`, `position_long`,
`distance`, `heart_rate`, `cadence`, `fractional_cadence`, `speed`,
`enhanced_speed`, `altitude` and `enhanced_altitude`. Their presence does not
establish units, precision, elevation accuracy or cadence conversion.

All four include record, device-info, session, lap, event and activity message
groups, alongside other groups. Numeric-string group keys such as `"113"` and
`"22"` also occur; consumers must not assume every group has a named
`*_mesgs` key. No undocumented message contents were shared.

- Lap fields include `total_timer_time`, `total_elapsed_time`, `lap_trigger`,
  cadence/fractional-cadence fields and `total_strides`. Auto-lap behavior,
  numeric relationships and physical cadence conversion remain unverified.
- Event fields include `event`, `event_type`, `timer_trigger` and `timestamp`.
  Field presence alone does not verify actual pause/start/stop behavior.
- Activity fields include `local_timestamp`, `timestamp` and `total_timer_time`.
  UTC/local-offset handling and daylight-saving boundaries remain unverified.
- `hrv_mesgs` occurs in the strap and race projections, but not the wrist or
  armband projections. This does not establish usable HRV measurements or
  availability of the separate daily HRV API dataset.
- The armband projection includes `training_file_mesgs`, `workout_mesgs` and
  `workout_step_mesgs`; no workout contents were shared.

The original projections exposed a notebook limitation: device-field unions contain
`antplus_device_type` for strap/race and `ble_device_type` for armband, but the
model allowlist included only the raw ANT alias `ant_device_type`. The corrected
notebook preserves that field and also projects ANT+ and BLE aliases.
Synthetic SDK decoding confirms ANT+ type 120 and BLE type 1 both expand to
`heart_rate`, while raw ANT type 120 remains numeric. These aliases identify a
protocol device category, not manufacturer, model, wear location or HR-sample
assignment. A BLE heart-rate device can be a chest strap or an armband.
The original owner reports above did not include alias values. The owner has
now rerun the corrected notebook successfully and supplied the armband
projection with `source_type=bluetooth_low_energy`, `device_type=1` and
`ble_device_type=heart_rate`. That entry still has no manufacturer/product.
This confirms a BLE heart-rate device entry in the real-file projection, not
COROS identity or assignment of every HR sample to that device. Repeated
projected entries do not establish multiple physical sensors. No further
sensor-output rerun is needed for this category check. The private date fallback
is not removed or upgraded to FIT-confirmed classification.

No serial-number values, private paths, dates, locations or physiological
values were shared. No original files or local notebook outputs are added to
the repository. Structural inspection is complete, but these reports alone do
not satisfy the remaining FIT timing/units or ADR acceptance gates.

## Private verification remaining

The owner confirms terms review, private-folder permission setup and a
successful one-activity search command with released client 1.0.0, followed by
the approved ten-GET batch reported below. Search/details and one-day wellness
structures, disjoint search pages, known-race details, endpoint access and a
broad token-lifetime band are now observed. Full history, page/range maxima,
remaining field mappings, edit behavior and FIT timing/units remain unresolved.
Keep personal values and raw evidence outside Git and chat; publish structural
conclusions only.

| Checklist area | Required evidence |
| --- | --- |
| Search and history | Two requests using `limit=20` succeeded with disjoint IDs; limited historical sample and activity-types response were nonempty. Maximum, exact page lengths, complete history and type-key selection remain unverified |
| Activity metadata | Known-race details match `race`; update marker is an ISO datetime string. Search-side race value, edit-marker semantics, units and optional values remain unverified |
| Download | All four local notebook inspections completed; ZIP layout/member counts and approximate file-size range were not projected and remain unverified |
| Wellness | Core one-day shapes confirmed; HRV is null for the selected day and VO2 endpoint returns a nonempty array. Range caps/history, optional values, broader HRV availability and VO2 field mapping remain pending |
| Zones | Nonempty array with a string `sport` field; other fields were omitted by the allowlist. Zone/profile mapping and per-sport semantics remain pending; actual values stay private |
| FIT messages | Four owner-run projections received; common fields/groups and variable timestamp intervals recorded above; watch recording setting unverified |
| FIT sensors | Protocol aliases checked synthetically and owner armband BLE `heart_rate` projection confirmed; exact source/model identity and HR-sample provenance remain unresolved |
| FIT timing and units | Synthetic SDK scaling, altitude-component, lap/timer and timestamp representations are verified above. Real-file cadence comparison, elevation source/accuracy, pause/lap behavior and offset/DST handling remain pending |
| HTTP behavior | All ten helper-paced probes succeeded; no HTTP error was reported. Live error formats and rate-limit/header behavior remain unobserved, not synthetically established |
| Token timing | `exp` and `iat` present; unverified claims yield a 1-48-hour lifetime band. Exact lifetime, token/cache reuse and refresh behavior are not established by this report |
| Terms | Owner confirms terms, private-folder permissions and private expiry-date configuration; no copied terms or dates; no external reminder required |
| SDK feasibility | Terms approved, synthetic checks and strict notebook/harness typing pass; four local structural inspections complete; real-file timing/units remain pending |

### Historical discovery procedure (superseded by approved closeout)

1. Keep the actual key expiration in the already-configured private
   `STRIDELOG_API_KEY_EXPIRES_ON` setting; no calendar integration is required.
   The owner has confirmed reviewing the Personal API and FIT SDK terms.
2. Keep using the protected folder outside the repository for the cache and
   responses. The owner selected an ignored local `.env` for credentials.
   Review that file's permissions locally too. Do not search the machine for
   credentials or use a key as a CLI argument.
3. Run only explicitly agreed discovery requests, no more than one per second,
   with all response/error output kept in that private location. Inspect locally,
   not through tools that would return raw data into the conversation.
4. Record field names, shapes, observed limits and unresolved items here.
   Keep account totals/dates, identifiers, actual measurements and locations private.
5. The four projected FIT reports are now recorded above. Keep local notebook
   outputs private and clear them before committing. Use the corrected
   protocol-alias projection and the bounded checks below for the remaining
   evidence. Accept the ADRs only after the evidence supports them, then obtain
   a separate Phase 2 implementation-plan approval.

### Remaining owner-run checks

Use existing private files and settings first. This checklist does not run
requests or ask for raw responses. Any further API request batch needs exact
documented paths/ranges agreed in advance, pacing and private output/error
redirection; do not probe rate limits or edit an activity solely to
provoke a change marker.

| Area | Local action | Share only |
| --- | --- | --- |
| Armband device category | Complete: owner supplied the corrected BLE `heart_rate` projection | No further sensor-output rerun needed; exact identity/provenance remains unverified |
| Recording setting | Check the watch's recording configuration; distinguish the current setting from historical evidence | `smart`, `every_second` or `unknown`, and whether historical applicability is known |
| Cadence/elevation/timing | Privately compare FIT fields with the activity UI and inspect lap/timer/local-time relationships | Confirmed conversion/relationship or `unverified`; no measurements, timestamps or offsets |
| Known race and edit marker | Details `race` comparison and ISO datetime format are confirmed; inspect existing search evidence and any naturally observed edit evidence only | Search-side race comparison and a yes/no/unverified change conclusion; no IDs, titles or timestamp values |
| Search/history | Array shape, disjoint page IDs and a nonempty limited historical sample are confirmed; full coverage and type selection remain pending | Coverage/type-selection conclusions only; no counts, IDs or dates. No additional request batch is approved here |
| Wellness/zones/VO2 max | Access and response categories are confirmed; inspect existing private responses for omitted schema information first | Structural/units conclusions only. Empty projected `fields` does not mean the underlying object is empty |
| Token/error behavior | Timing-claim presence and broad lifetime band are recorded; no live errors were reported | Only naturally encountered sanitized status/shape conclusions; never tokens, claims payloads, exact expiry or response bodies |

Unknowns stay explicit. Completing the device-alias check alone does not close
Phase 1 or accept either ADR. Phase 2 ingestion and Phase 3 HR-source
classification remain separate implementation approvals.

### Approved bounded API discovery helper (owner-run)

The helper consolidates the agreed batch; the owner has now supplied its
structural report below. This does not complete Phase 1 or request a rerun.
For reference, the owner-run command below uses the repository root and a
PowerShell terminal. It loads the existing `.env`; no additional settings,
kernel changes or manual environment-variable exports are needed.

```powershell
& 'C:\Python314\python.exe' -m uv run --isolated --no-project --env-file .env --python 3.14 --with garmin-connect-personal-api-python==1.0.0 python notebooks\api_discovery.py --live
```

Enter the existing protected discovery directory outside the repository, a
private sample day in `YYYY-MM-DD` form, and a known-race activity's numeric ID.
Obtain that ID privately from the activity's Garmin Connect URL; do not share
the URL or ID. Choose a day with expected wellness data. The helper lists public
request names and requires literal `RUN` before contacting Garmin. Without
`--live`, it sends nothing. Folder containment is checked, but its ACL is not:
continue using the protected directory verified during the setup below.

The approved budget is at most ten GETs plus one token exchange if the protected
cache needs refreshing. Starts are spaced at least one second apart, including
authentication. Only the official HTTPS origin is allowed; redirects and retries
are disabled.

| Request name | Target and scope |
| --- | --- |
| `activity_types` | `/activity-service/activity/activityTypes/simple` |
| `search_first`, `search_second` | Activity search, `start=0` and `start=20`, each with `limit=20` |
| `history_sample` | Activity search, `start=0`, `limit=1`, January 2025 only (the public planned start month, not a completeness check) |
| `race_details` | `/activity-service/activity/{private_id}` |
| `daily_summary` | `/usersummary-service/v2/dailysummaries`, selected day only |
| `sleep` | `/sleep-service/sleep/dailySleepSummariesByDate`, selected day only |
| `hrv` | `/hrv-service/hrv/daily/{day}/{day}` |
| `zones` | `/biometric-service/heartRateZones/v2` |
| `vo2_max` | `/metrics-service/metrics/maxmet/daily/{day}/{day}` |

Search uses `/activitylist-service/activities/search/activities`; summary and
sleep pass equal `startDate`/`endDate`. The activity-types and VO2 paths were
cross-checked against the official client's
[upstream source at revision 979e6e9](https://github.com/garmin/connect-personal-api-python/blob/979e6e9fc58bcbf968611509b634ba734d6f8cdf/src/garmin_personal_api/client.py),
not assumed to be convenience methods in released client 1.0.0.

Successful parsed JSON responses go into a new, non-overwriting `api-check-*`
subdirectory; these are not original HTTP bytes or headers. The bearer cache
stays in the selected protected directory. Error bodies are not printed or
saved. HTTP 401/403/429 stops the batch immediately; other HTTP failures are
reported per probe and produce a nonzero exit. Transport, redirect, token and
JSON parsing failures also stop with sanitized diagnostics.

**Share only the final structural JSON**, not terminal inputs, raw files, cache,
error bodies, keys or tokens. The projection includes only hardcoded field names
and JSON kinds, takes only the first array item and limits nesting depth to four.
Unknown field names and all response scalar values are omitted. Paging compares
IDs privately and reports only disjoint/overlap/unavailable. Race metadata
reports a comparison and timestamp format, not values. Token timing reports
claim presence and a broad lifetime band from unverified claims; it does not
validate a JWT signature or disclose its payload or exact expiry.

Empty/null/failed probes remain distinct. A successful batch does not establish
page/range maxima, complete history, units, optional-field coverage, edit-marker
behavior or wider HRV availability. Existing FIT timing/unit gates and Proposed
ADRs are unchanged. The separate `check_api_discovery.py` harness uses only
synthetic responses with the real client's network transport mocked, and CI
runs it on Windows and Linux without loading `.env`.

### Owner-reported bounded API batch results

The owner supplied the helper's allowlisted report, not raw responses, private
inputs or credential files. It reports `completed=true`,
`has_http_errors=false` and successful results for all ten probes. No Garmin
requests were made by the assistant to review or record this evidence.

| Area | Observed result and limit |
| --- | --- |
| Activity types | Nonempty array of objects. The first item's projected `fields` is empty with `other_fields_omitted=true`; endpoint access is verified, not taxonomy field names or values |
| Search pages | Both are nonempty arrays; their privately compared ID sets are disjoint. Requests using `start=0/20` and `limit=20` succeeded; exact returned lengths, maximum size and stable ordering are not established |
| Historical sample | The fixed, limited historical query returned a nonempty array; this does not verify complete history, totals or the earliest activity |
| Search classification | `activityType` exposes numeric `typeId`/`parentTypeId` and string `typeKey`; `eventType` exposes numeric `typeId` and string `typeKey`. Values were not projected |
| Known-race details | `event_key_is_race=true`; `eventTypeDTO.typeKey` matches `race`. This does not verify the search-side event value |
| Change marker | `metadataDTO.lastUpdateDate` is a string parsed as an ISO datetime; actual edit behavior remains `not_tested`, and timezone/precision guarantees are not established |
| Daily summaries | Object with a nonempty `data` array. Projected heart-rate, Body Battery and stress fields are numeric; `movement.steps` is an object at the depth limit, not established here as a scalar count |
| Sleep | Nonempty array; projected duration/stage fields have numeric kinds. This does not establish units from names alone or optional sleep-score coverage |
| HRV | Successful response with JSON `null` for the selected day. It does not establish device support or absence of data on other days |
| VO2 max | Nonempty array of objects, not 404. First-item fields were all omitted by the allowlist; no particular VO2 metric field, value or unit is verified |
| Zones | Nonempty array; first item has a string `sport` field and omitted fields. Zone boundaries, profile HR fields and per-sport meaning remain unresolved |
| Token timing | `exp` and `iat` are present; their unverified claims yield `one_to_48_hours`. This is not exact 24-hour timing, signature validation, key expiration or evidence of a fresh token exchange |
| Errors and pacing | All probes succeeded through the helper's paced path. No live 401/403/404/429 or `Retry-After` behavior was observed in this batch |

Search/details metric-name differences are reconfirmed, including search
`averageRunningCadenceInStepsPerMinute`/`avgStrideLength` versus details
`averageRunCadence`/`strideLength`. Details `timeZoneUnitDTO.timeZone` is a string;
deriving the local offset remains unverified.

The report uses only allowlisted keys, the first array item and limited depth.
An empty projected field map with omitted fields is a projection limitation,
not an empty source object or evidence of absent metrics. Do not respond by
requesting raw files, echoing unknown dynamic keys or rerunning the live batch.
Any further local projection or request work requires a separately agreed plan.
The remaining checklist and both Proposed ADRs stay open; no ingestion is
authorized by this report.

### Offline review of the saved API responses

Phase 3 mapping correction: the public Swagger `MovementV2DTO.steps` property
references `MovementValueV2DTO`. Its `value` field is the actual daily count;
`goal` and `distanceInMeters` are distinct fields. The earlier owner projection
already established an object, not a scalar. Rechecked through the
[public schema UI](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/)
without authentication or API execution. Synthetic tests now use that nested
shape; no private document was read to establish this correction.

The public Swagger schemas were checked again, without authentication or
executing any API operation. The missing projections have documented field
names outside the original allowlist:

| Public schema | Allowlisted structural fields |
| --- | --- |
| `SimpleActivityTypeDTO` | `key`, `parent` |
| `MaxMetDTO` / `VO2MaxDTO` | `generic`, `cycling`, `rowing` wrappers; `calendarDate`, `vo2MaxValue`, `vo2MaxPreciseValue` |
| `HeartRateZonesDTO` | `sport`, `trainingMethod`, `restingHeartRateUsed`, `lactateThresholdHeartRateUsed`, `maxHeartRateUsed`, `restingHrAutoUpdateUsed`, `zone1Floor` through `zone5Floor` |

These are public schema facts, not confirmation that every field is populated
in the owner's saved responses. In particular, do not assume the VO2 `generic`
wrapper is a verified running-specific measurement. Zone fields describe a
sport configuration, not a history of zone/profile changes.

The existing helper now has an owner-run, read-only `--offline` mode. From the
repository root:

```powershell
& 'C:\Python314\python.exe' -m uv run --isolated --no-project --no-env-file --python 3.14 --with garmin-connect-personal-api-python==1.0.0 python notebooks\api_discovery.py --offline
```

Select the existing protected **`api-check-*` response subdirectory**, not its
parent containing the bearer cache. The mode reads only `activity_types.json`,
`vo2_max.json` and `zones.json`; it does not read `.env` or the token cache,
authenticate, make HTTP requests, or write/overwrite files. Directory
containment and each source path are checked; linked response files and targets
outside the selected directory are rejected. Keep using the protected directory:
the helper does not establish its ACLs.

Only the final structural JSON should be shared. The expanded allowlist still
omits scalar values and unknown keys, inspects only first array items and limits
depth to four. Offline output is explicitly labelled as saved-response
inspection and makes no live HTTP-status or freshness claim. Missing/malformed
files stop with a sanitized error rather than emitting a partial success report.
`--offline` and `--live` cannot be combined; no mode still sends no requests.

Five new synthetic checks cover the omitted wrapper projection, credential-free
fixed-file access and unchanged contents, invalid/missing/linked inputs,
sanitized errors and mode exclusivity. All 17 API checks and strict typing pass.
The existing live request budget, pacing, confirmation and error-stop behavior
remain covered. No additional Garmin batch or Phase 2 ingestion is authorized.
The owner-run offline report is recorded below. Real-file interpretation
conclusions remain deferred, not passed.

### Approved discovery closeout

The owner supplied the read-only saved-response projection and approved ending
the discovery timebox and implementing Phase 2 in two cohesive PRs. No further
discovery helper or live rerun is required.

| Saved response | Observed first-item structure |
| --- | --- |
| Activity types | Nonempty array; `key` is a string. No `parent` in that first item; this does not establish every item's hierarchy |
| VO2 max | Nonempty array; `generic` contains string `calendarDate`/`sport` and numeric `vo2MaxPreciseValue`/`vo2MaxValue`, with other fields omitted; `cycling` is null |
| Zones | Nonempty array; numeric `maxHeartRateUsed`, `restingHeartRateUsed` and `zone1Floor` through `zone5Floor`; string `sport`/`trainingMethod`; boolean `restingHrAutoUpdateUsed`; null `lactateThresholdHeartRateUsed` |

This is offline schema evidence only, not a live freshness/status check or full
schema/unit verification. No scalar values were supplied. The `generic` wrapper
does not prove a running-specific VO2 measurement. Zone configuration is not
historical profile data.

ADR-0002 is accepted for uninterpreted raw ingestion using page size 20, at least
one second between attempts and one-day wellness requests. Full-history
coverage, exact limits, natural HTTP/retry behavior, token reuse and edit-marker
semantics transfer to Phase 2 acceptance. Recent detail refreshes do not detect
arbitrary old edits; older reconciliation needs an explicit older `--since`.

ADR-0004 stays Proposed until Phase 3. Real-file cadence/elevation/timing,
offset/DST handling and HR identity/provenance checks transfer there. Original
ZIPs remain untouched and no SDK production dependency is added now.
The historical pending/gating statements above describe evidence at those
earlier checkpoints; they do not revoke this explicitly approved transition.

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
retaining explicit grants from an existing folder. Folder permissions do not
control backup or synchronization settings.

Check the actual key expiration privately in Garmin Connect and record it as
`STRIDELOG_API_KEY_EXPIRES_ON=YYYY-MM-DD` in `.env`. No external reminder is
required. Do not share the date, ACL listing or folder path. Until Phase 2
implements `doctor`, this setting does not produce a warning.

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
