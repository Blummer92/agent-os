# Native GitHub Actions timing (#3694)

This optional, read-only command provides historical run/job/step evidence to #520.
It complements the existing #1359 `validate-all.sh` check/suite timing; it changes
no tests, coverage, workflows, checks, settings, or validation authority. Raw API
responses alone lack the attempt deduplication, missing-data classification and
SHA-separated distributions required by #520, so this small extractor normalizes
native data rather than creating another measurement service.

## Capture and report

Requires Python 3.10+ and an already authenticated `gh` with repository/Actions
read access. No token is read by this script, and no credential or permission
change is performed. All subprocess API requests explicitly use GET, no shell.
Choose a timezone-aware comparable window of at most 30 days, exact workflow path,
and the exact checked-out implementation SHA:

```bash
python scripts/ci_perf/github_actions_timing.py --repository Blummer92/agent-os --start 2026-09-22T01:30:00Z --end 2026-10-22T01:30:00Z --workflow .github/workflows/agent-os-validation.yml --implementation-head "$(git rev-parse HEAD)" --max-pages 10 --max-runs 20 --output /tmp/agent-os-timing
```

The two local outputs are `timing.json` and `timing.md`. Reports are advisory and
must never substitute for authoritative exact-head aggregate validation. No
automatic upload, persistent database or CI job is installed.

The window filters original run creation, not attempt execution. Reruns of older
runs created before the start are excluded, while included attempts can execute
outside the window. A complete inventory therefore means only this bounded
creation-window query, never a representative execution-window population.

The inventory uses native `/actions/runs` pagination, then explicit
`/actions/runs/{id}/attempts/{attempt}/jobs` pagination. Previous attempt metadata
comes from `/actions/runs/{id}/attempts/{attempt}`. Identity is workflow path + run
ID + attempt, not SHA alone. Repeated attempts stay separate; duplicate captures
are omitted. Fetched attempt id, attempt number, SHA and workflow path must match
the requested inventory lineage; supplied job run/attempt/SHA metadata must match
its run both live and offline. A mismatch is refused, never relabeled. Boundaries are 10 inventory pages, 100 attempts, 10 pages/1,000 jobs
per attempt, 200 steps per job and a 60-second timeout per native request. API
search caps can make a saturated inventory incomplete; split the window into
smaller disjoint intervals and reconcile identities before population analysis.

A saved connector capture can be normalized without `gh` or network access:

```bash
python scripts/ci_perf/github_actions_timing.py --input /tmp/capture.json --implementation-head "$(git rev-parse HEAD)" --output /tmp/agent-os-timing
```

The capture object has `repository`, `window: {start, end}`, `collection: {status,
reason_codes}`, and `runs`. Each native run retains its positive integer `id`,
`run_attempt`, exact `head_sha`, workflow `path`, `event`, `status`, `conclusion`,
`created_at`, `run_started_at` and `html_url`; `jobs` contains only jobs fetched
for that exact attempt, retaining native timestamps, identities and `steps`.
Offline input is capped at 10 MB. Preserve the original capture and API URLs for
independent provenance review. Only the caller can prove a supplied capture came
from the claimed native endpoint. Do not manually splice latest-attempt jobs into
an earlier attempt.

Exit 0 means report generation completed with a collection status other than
partial/error. Exit 2 accompanies partial/error collections and malformed inputs;
it does not mean successful representative measurement. Missing `gh`, timeout,
invalid JSON, schema/provider failure, access denied and rate limiting remain
explicit errors, with safe bounded reason codes; provider stderr is never echoed.
No automatic retry is performed, including on rate limiting. Reacquire privately
with the existing API route when access or rate limits permit, preserving the
original partial evidence. A failed live capture cannot become an empty success.

## Meaning of timings

- Initial dispatch delay: first-attempt `created_at` to `run_started_at`. This
  is not every job's queue time. For reruns the queue origin is unavailable.
- Job queue delay: job `created_at` to `started_at` where present.
- Job and step duration: `started_at` to `completed_at`, only for completed,
  non-skipped entries with nonnegative timestamps. Cancelled durations are kept
  as cancelled observations, separate from successful distributions.
- Workflow completion is not exposed by these payloads. `updated_at` can change
  for metadata reasons, so it is never used as completion time. Workflow wall
  duration is explicitly missing. First-attempt created-to-last-completed-job
  elapsed time is only a lower bound, not the workflow wall-clock baseline.
- Raw step names are retained. Setup, install, test/validation and reporting
  labels are heuristics. No heuristic identifies pytest fixtures, CPU usage or
  true cache hits. Parallel job/step durations must not be summed into wall time.
- `--expected-head <exact SHA>` optionally marks different heads as stale relative
  to that supplied comparison. It never proves supersession. A replacement-run
  lineage is required to call a cancelled or old attempt superseded.

Each distribution reports actual n, median and nearest-rank p90. Groups retain
workflow path, event, head SHA and conclusion; unlike configurations cannot be
silently averaged into one speedup. Even identical SHA groups can differ by
workflow inputs, permissions or run type, so inspect configuration before
combining them. n < 20 is low confidence; n >= 20 alone does not establish
representativeness. The full comparable 30-day baseline remains #520's work.

## Pilot evidence and limitations

Read-only connector capture on 2026-10-22 used a bounded latest PR-event inventory
and selected 20 latest `.github/workflows/agent-os-validation.yml` run attempts:
67 jobs and 547 steps, split into 17 workflow/event/SHA/conclusion groups. The
sample spans only part of 2026-10-21/22 and is **not** a representative 30-day
baseline. The source inventory reported 2,500 results; only one 100-item page was
read. Capture status is partial, with explicit latest-subset and unverified-
configuration reasons. The report's requested window is 2026-09-22T01:30:00Z to
2026-10-22T01:30:00Z, not a claim that every run in that window was collected.

Examples of real successful aggregate-job elapsed times: run 39702437307 at SHA
`188020d37620c71cc0b5a8675601d353865dee56` took 688 seconds; run 39697634925 at
SHA `d5e40823c50090bdffced79dff69fe037949d5bf` took 326 seconds. These are separate
configurations and establish no improvement. Other jobs were skipped, cancelled
or still running at capture time. Skipped jobs sometimes have reversed timestamps;
they are missing measurements, never negative or zero successes. Twenty workflow
completion values remain missing because no exact completion timestamp was
provided. No baseline, optimization or savings claim follows from this pilot.

Focused regression command (standard library only):

```bash
python -m unittest discover -s tests/ci_perf -p test_github_actions_timing.py
```

Tests cover attempts/deduplication, stale-vs-superseded evidence, SHA/conclusion
boundaries, skipped/inflight/reversed timestamps, actual n/median/p90, pagination,
GET-only transport, access vs rate-limit errors, and partial-result exit semantics.

Rollback: remove this script, its directly corresponding test and this document.
No canonical validation commands, dependencies or external state need rollback.
Future AI Navigation may consume the bounded JSON with its exact implementation
head, source run SHAs and missing-data reasons. Such integration is outside #3694.
