# Analytics metrics

Phase 4 metrics are calculated locally from the rebuilt measurements. Tests use
invented streams only; no test contacts Garmin or reads the owner's archive.
`stridelog analyze` caches per-activity results by input signature and rebuilds
the daily series on every run.

`stridelog sync` runs the offline rebuild and analysis after a successful archive
sync. `stridelog analyze` can also be run independently. Use
`stridelog profile setup` for hidden interactive prompts, or set dated inputs
with `stridelog profile set YYYY-MM-DD --max-hr-bpm N
--resting-hr-bpm N --sex-for-trimp female|other [--threshold-hr-bpm N]
[--zone-floors N,N,N,N,N]`. Profile values are stored in the local database and
are not printed by the command. The five zone floors are optional and must be
strictly increasing. `female` selects the female Banister constants; `other`
selects the other constants from the project formula. Automatic Garmin profile
sourcing is deferred until a supported source is verified. Command-line values
may be retained in shell history or visible to other local processes; prefer
interactive setup. Age is not required by these metrics and is not collected.

## Stream preparation

- Records are ordered by UTC timestamp. For duplicate timestamps, the last
  record is used in the derived stream; stored FIT records remain unchanged.
- The timeline starts at the first record and advances in one-second steps.
  Numeric values are linearly interpolated only between two known values whose
  timestamps are at most 5 seconds apart. No endpoint extrapolation occurs;
  larger gaps and missing sensor values stay null.
- Splits and best efforts use a separate distance timeline that permits
  interpolation over gaps up to 10 seconds. Other metrics retain the 5-second
  limit; longer distance gaps still break segments. Interpolated distance is an
  estimate, not a reconstruction of actual movement within the gap.
- Elevation is smoothed with a centered 20 m moving mean. Grade is the
  difference in smoothed elevation divided by distance change, limited to
  [-0.45, 0.45]. It is null where distance or elevation is unavailable or
  distance is not monotonic.
- FIT timer start/stop events define active intervals for HR-based metrics.
  When no usable timer controls exist, the timeline is treated as active.
- Moving time uses FIT timer time when present. Otherwise it counts one-second
  intervals whose recorded speed is greater than 0.5 m/s.

## Activity metrics

| Metric | Definition | Limitations |
| --- | --- | --- |
| Splits | Time for each full kilometer, with distance/time interpolated at split edges, plus the final partial split for an uninterrupted stream | Stops at the first missing or discontinuous distance span; later splits and a truncated partial split are unavailable |
| Laps | FIT lap totals and average pace (`timer_time / distance`) | Preserves FIT lap boundaries; does not relabel auto-laps |
| Best efforts | Fastest continuous windows for 400 m, 1 km, 1 mile, 5 km, 10 km, 15 km, 10 miles, half marathon, 30 km and marathon | A window cannot bridge a record gap over 10 s, a distance reversal or a segment over 15 m/s; these deterministic metric limits do not diagnose why a sample looks unusual |
| Lap-estimated marathon | When no sampled marathon effort exists, estimate the fastest marathon window from consecutive lap distances and timer times, assuming constant speed within each lap | An estimate, not an official record; accuracy depends on lap length and pace variation. Timer time is checked against the FIT lap elapsed total, not the timestamp duration; timestamp disagreements leave accuracy uncertain. Missing or invalid lap totals, implausible average speed, nonconsecutive indices or lap-boundary gaps/overlaps over 1 s break the window. It does not contribute to personal-record progression or race predictions |
| Personal-record progression | Per-activity best efforts, stored as a dated progression whenever a faster time is achieved | Excluded activities do not contribute |
| Time in HR zones | Count of observed one-second HR values against dated, increasing zone floors | A zone profile applies only on or after its explicit `athlete_profile.effective_from`; a zone snapshot's observation time is not treated as an effective date. Missing profiles or the explicit `hr_invalid` annotation yield null |
| TRIMP | `sum((1/60) * HRr * k * exp(c * HRr))`, with `HRr = (HR - HR_rest) / (HR_max - HR_rest)` and `k,c = 0.64,1.92` (`other`) or `0.86,1.67` (`female`) | Requires dated maximum/resting HR and TRIMP selection. HRr is limited to [0,1]. Missing inputs or explicit `hr_invalid` yields null |
| Efficiency factor | Mean speed divided by mean HR | Compare similar runs; null for missing or explicitly invalid HR |
| Pace at HR | Per-run median pace during the inclusive 140–150 bpm band, then the weekly median across runs | Fixed example band from the plan; null for missing or explicitly invalid HR |
| Aerobic decoupling | `(EF_first_half - EF_second_half) / EF_first_half * 100`, split at half of duration | At least 60 minutes and explicitly marked as a steady run; otherwise unavailable |
| Grade-adjusted pace | Mean Minetti-adjusted speed converted to seconds/km, using `v_flat = v * C(i) / C(0)` and `C(i) = 155.4 i^5 - 30.4 i^4 - 43.3 i^3 + 46.3 i^2 + 19.5 i + 3.6` | Approximate because watch elevation can be GPS-derived |
| Elevation gain | Sum of positive changes in smoothed elevation | Approximate and null when elevation/distance is unavailable |
| Race predictions | Riegel, VDOT and critical-speed predictions for 5 km, 10 km, half marathon and marathon from a race result or entered official time | Predictions are estimates, not records; critical speed requires at least two best efforts lasting 3–20 minutes |

An annotation with `exclude_from_stats` excludes an activity from daily training
load. An annotation with `hr_invalid` excludes only HR-dependent metrics.
Phase 3 quality flags remain warnings: they neither identify a cause nor
automatically remove or repair samples.

The best-efforts notebook labels each target distance and shows its fastest
continuous segment per activity, with elapsed time and pace in min:sec/km.
Its selector offers 400 m, 1 km, 5 km, 10 km, half marathon and marathon;
select one distance to compare its pace across dates. A distance without a
qualifying effort is marked unavailable. Missing longer efforts can result
from the continuous-window limits above; they do not establish the cause of
any particular gap. Lap-estimated marathons are labelled and shown as diamond
markers; the table sorts elapsed times within each distance. The activity
explorer also displays pace in min:sec/km; stopped or missing speed has no
pace. Its calculated splits can be incomplete when the distance stream is
discontinuous. Stored measurements remain SI. Re-run `stridelog analyze`
after upgrading to recalculate cached analytics.

Aerobic decoupling requires the owner to mark a run steady with
`stridelog activity steady-run <activity-id> --steady`. Use
`--not-steady` to clear the eligibility. The command does not print activity
metrics and refreshes the cached analysis.
Race flags can be overridden and local race names/results recorded with
`stridelog activity race <activity-id> --race [--race-name NAME]
[--official-time-s SECONDS]`. `--not-race` excludes the activity and clears
local race details; `--from-garmin` clears local overrides and details.

## Daily series and wellness

- Daily load is the sum of available per-run TRIMP. A day without a run has load
  zero; a run with missing required profile inputs makes that day's load
  unavailable. CTL/ATL and dependent ratios remain unavailable after an unknown
  load rather than silently treating it as zero.
- Initialize CTL and ATL at zero on the first represented local date, then
  apply `CTL_t = CTL_(t-1) + (load_t - CTL_(t-1))/42` and
  `ATL_t = ATL_(t-1) + (load_t - ATL_(t-1))/7`. TSB is the previous day's
  `CTL - ATL`, following the plan's convention.
- ACWR is the mean daily load over the latest 7 calendar days divided by the
  latest 28-day mean; it is null until both windows are complete or when the
  chronic mean is zero.
- Weekly ramp rate is the percentage change in the latest 7-day load total
  versus the preceding 7-day total. It is null when either window has unknown
  load or the previous week's total is zero.
- Wellness rows retain their local-date values; resting HR also has a
  calendar-based 7-day mean over available readings. Sleep duration, steps,
  Body Battery high/low, stress and HRV remain null when absent.
- Weekly pace-at-HR is the median of per-run median paces for the fixed 140–150
  bpm band. Personal-record progression records each faster per-activity
  best-effort time, excluding only explicitly excluded activities.

TRIMP, ACWR and ramp rate are descriptive calculations, not medical advice or
injury-risk assessments. Quality warning causes have not been individually
verified.

## References

- Banister, E. W. (1991), *Modeling elite athletic performance* (TRIMP).
- Allen, H. and Coggan, A., *Training and Racing with a Power Meter* (CTL/ATL/TSB convention).
- Gabbett, T. J. (2016), *The training-injury prevention paradox* (ACWR); see also
  Impellizzeri et al. (2020) for limitations and debate.
- Minetti et al. (2002), *Energy cost of walking and running at extreme uphill and downhill slopes* (GAP).
- Riegel, P. S. (1981), *Athletic Records and Human Endurance* (race prediction).
- Daniels, J. and Gilbert, J. (1979), *Oxygen Power* (VDOT).
- Jones, A. M. and Vanhatalo, A. (2017), *The "Critical Power" concept: applications to sports performance with a focus on intermittent high-intensity exercise* (critical speed).

## Validation

Unit and integration tests compare formulas with known answers and synthetic
FIT/SQLite data. Real-account comparisons and visual plausibility checks are
owner-run locally; private reports and raw account data are not required or
shared for automated validation.
