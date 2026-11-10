# Optional Hyperfine local benchmark pilot (#3696)

Parent measurement owner: #520. Existing aggregate/suite timing: completed #1359.

## Disposition

**Host no-adoption / deferred Hyperfine measurement.** Hyperfine could not be
installed or executed on the campaign host. This change documents the bounded
pilot and its limitation; it introduces no wrapper, dependency, CI job, gate,
metrics store, or scheduler. It does not conclude that Hyperfine is unsuitable on
other development hosts. There are zero Hyperfine samples and no speedup claim.

## Compatibility and installation evidence

On 2026-10-22 UTC (2026-10-21 America/Detroit), this host was Ubuntu 24.04.3,
x86_64, Linux 6.18.55, glibc 2.39, Python 3.12.14. `command -v hyperfine` and
`command -v cargo` found no executable. The apt package cache had no Hyperfine
entry. A local venv pip query found no Hyperfine distribution; pip is not the
upstream installation route. No elevated installer was used.

The official v2.0.0 Linux x86_64 release archive request returned HTTP 403 from
the host network policy. A Debian package-mirror request also returned HTTP 403.
The source is readable through the GitHub connection, but it does not transfer
release binaries. Installation footprint and execution overhead are therefore
unmeasured. Do not relabel this access failure as a successful benchmark.

Upstream v2.0.0 supports Linux, macOS and Windows release binaries and is dual
licensed MIT OR Apache-2.0. It requires Rust 1.97 or newer for source builds.
A supported binary may be installed in a private user directory on an authorized
host, without repository dependency changes or privilege elevation. Record its
version, executable digest, archive checksum, platform and installed size. Do
not make installation mandatory for normal development or CI.

Primary sources:

- [v2.0.0 release and schema migration](https://github.com/sharkdp/hyperfine/releases/tag/v2.0.0)
- [v2.0.0 usage and platform installation](https://github.com/sharkdp/hyperfine/blob/v2.0.0/README.md)
- [MIT license](https://github.com/sharkdp/hyperfine/blob/v2.0.0/LICENSE-MIT)
- [Apache license](https://github.com/sharkdp/hyperfine/blob/v2.0.0/LICENSE-APACHE)

## Two bounded commands

Run from a clean repository checkout in a disposable development environment.
The first evaluates the canonical readiness owner against its offline fixture.
The second syntax-checks the evaluator and its direct support modules; this is a
focused developer check, not authoritative aggregate validation. Both commands
read repository source and return nonzero on failure. Neither mutates GitHub,
production, caches, or validation authority. Python may create local bytecode
unless `PYTHONDONTWRITEBYTECODE=1` is set before both samples.

The exact POSIX command strings below were executed successfully with system
Python against source downloaded from base
`f522f1dd9863c610e3771723274aa9c503889d80`. Hyperfine invocations remain unexecuted.
Use the same interpreter path before and after an optimization.

```sh
command_1="python -c \"from pathlib import Path; from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness; assert evaluate_issue_readiness(Path('tests/fixtures/agent_os_issue_readiness/new_tiered_issue.md').read_text()).outcome.value == 'ready'\""
command_2="python -c \"import ast; from pathlib import Path; names=('__init__.py','models.py','parse_issue.py','path_contract.py','issueplan_scanner.py','readiness.py','report.py'); [ast.parse((Path('scripts/agent_os_issue_acceptance')/n).read_text(), filename=n) for n in names]\""
hyperfine --version
hyperfine --shell=default --warmup 3 --runs 20 --export-json warm.json --export-markdown warm.md "$command_1" "$command_2"
hyperfine --shell=default --warmup 0 --runs 20 --export-json no-warmup.json --export-markdown no-warmup.md "$command_1" "$command_2"
```

Shell execution is explicit because v2 defaults to no intermediate shell while
v1 used a shell. The shown syntax requires a POSIX shell; Windows command quoting
must be adapted and independently validated. The two files represent different
warm-up policies, not a controlled cold-cache experiment. Do not drop shared OS
caches or mutate CI state to create a cold run. Record cache state as uncontrolled
unless a genuinely isolated cold-start protocol is available.

## Sampling and provenance

Capture exact `git rev-parse HEAD`, `git status --porcelain`, Python/Hyperfine
versions, OS/architecture/CPU identity, command strings, warm-ups, repetitions,
start time, exit status, raw JSON and Markdown. Bind the source revision and
measurement-tool revision separately. Do not insert a self-referential SHA into a
committed report and call it an exact measurement head. Keep output outside tracked
source, bound the run count, and exclude credentials/environment secrets.

Report actual n, median, p90 (nearest rank: sorted index ceil(0.9*n)-1), mean,
sample standard deviation, min/max, and raw values. A nonzero command, missing
binary, timeout, invalid JSON or missing metric is an error/partial result, never
zero duration. Do not use `--ignore-failure`. Reject non-finite/negative timings.
Upstream v1 JSON has `results[i].times`; v2 has
`results[i].measurements[j].time_wall_clock.value` (seconds), with summaries under
`results[i].summary.time_wall_clock`. Check `schema_version` and the metric unit;
do not feed v2 output into a v1-only parser. Warm-ups are excluded from raw samples.

A local n=20 process-start pilot does not satisfy #520's representative CI
population. #520 requires the most recent comparable 30-day window and at least
20 representative runs per recurring workflow where available, with SHA/config
boundaries and low-confidence status below 20. Keep local runtime, developer-loop
latency, queue delay, suite duration, CPU samples and redundant CI counts separate.

## Executed fallback baseline (not Hyperfine)

The Python standard library `subprocess.run` and `time.perf_counter` executed
three warm-ups followed by 20 measured fresh process launches for each command.
Every command exited zero. This was six downloaded evaluator/support modules plus an empty package marker,
not a complete Git checkout; the six source modules and fixture were sourced from the
base SHA above. No optimization was applied. Cache state, shared-host load and
parallel campaign activity were uncontrolled. Bytecode may already have been
warm. These values demonstrate bounded command executability and characterize
this host only; they are not Hyperfine validation or before/after evidence.

The isolated subset used a synthetic empty package `__init__.py` to load the six
unchanged canonical modules without the repository package facade. The real
repository facade imports additional modules. Thus the measured startup and syntax
check are subset measurements, not full-checkout developer-loop latency. Re-run
both commands on a complete checkout before comparing an optimization.

| Command | n | Median seconds | p90 seconds | Mean seconds | Sample stdev seconds |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 0.058949 | 0.063895 | 0.060673 | 0.008470 |
| 2 | 20 | 0.034348 | 0.035882 | 0.034200 | 0.001883 |

Bounded raw fallback evidence:

```json
{
  "tool": "python-subprocess-perf_counter",
  "hyperfine_executed": false,
  "schema": "local-pilot-v1",
  "source_sha": "f522f1dd9863c610e3771723274aa9c503889d80",
  "scope": "downloaded canonical readiness subset, not whole-repo checkout",
  "environment": {
    "python": "3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]",
    "platform": "Linux-6.18.55-x86_64-with-glibc2.39"
  },
  "warmup": 3,
  "repetitions": 20,
  "cache_state": "uncontrolled; warmed process starts, no cache eviction",
  "results": [
    {
      "command": "python -c 'from pathlib import Path; from scripts.agent_os_issue_acceptance.readiness import evaluate_issue_readiness; assert evaluate_issue_readiness(Path('\"'\"'tests/fixtures/agent_os_issue_readiness/new_tiered_issue.md'\"'\"').read_text()).outcome.value == '\"'\"'ready'\"'\"''",
      "n": 20,
      "seconds": [
        0.06357897799898637,
        0.05340023199823918,
        0.05412250099470839,
        0.06452568399981828,
        0.06334859299386153,
        0.05506934699951671,
        0.09282073499343824,
        0.05902836300083436,
        0.05984397199790692,
        0.058474120996834245,
        0.05881442700047046,
        0.05825174300116487,
        0.05886949599516811,
        0.062136599997757,
        0.06389496499468805,
        0.05479759300214937,
        0.062187707000703085,
        0.052750288996321615,
        0.06276280000020051,
        0.05477612599497661
      ],
      "median_seconds": 0.058948929498001235,
      "p90_nearest_rank_seconds": 0.06389496499468805,
      "mean_seconds": 0.060672713597887194,
      "sample_stdev_seconds": 0.00847029148767089,
      "exit_codes": [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0
      ]
    },
    {
      "command": "python -c 'import ast; from pathlib import Path; names=('\"'\"'__init__.py'\"'\"','\"'\"'models.py'\"'\"','\"'\"'parse_issue.py'\"'\"','\"'\"'path_contract.py'\"'\"','\"'\"'issueplan_scanner.py'\"'\"','\"'\"'readiness.py'\"'\"','\"'\"'report.py'\"'\"'); [ast.parse((Path('\"'\"'scripts/agent_os_issue_acceptance'\"'\"')/n).read_text(), filename=n) for n in names]'",
      "n": 20,
      "seconds": [
        0.03431433600053424,
        0.03153320999990683,
        0.034593335003592074,
        0.03319599600217771,
        0.034511482997913845,
        0.03181933999439934,
        0.0345759990013903,
        0.031255383997631725,
        0.03374743399763247,
        0.0340031879968592,
        0.03357827899890253,
        0.03161313899909146,
        0.036296619997301605,
        0.03432974599854788,
        0.03557606699905591,
        0.03437862999999197,
        0.03499054800340673,
        0.034365931001957506,
        0.03942985300091095,
        0.0358815669969772
      ],
      "median_seconds": 0.03434783850025269,
      "p90_nearest_rank_seconds": 0.0358815669969772,
      "mean_seconds": 0.034199504249409075,
      "sample_stdev_seconds": 0.0018828290730136226,
      "exit_codes": [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0
      ]
    }
  ]
}
```

Additional verification: the existing focused
`test_readiness.py::test_tier_one_standard_issue_is_ready` passed once (1 passed
in 0.13 s) using read-only upstream pytest 8.4.2 bootstrapped by the duration lane.
The package marker was synthetic as described above. This test time is runner
output, not a benchmark distribution. POSIX command assignments were also executed
and their raw sample counts, median and nearest-rank p90 independently recomputed.

## Acceptance and handoff

- Reproducible isolated commands and sampling protocol: documented above; both
  direct commands executed successfully. Hyperfine execution remains unavailable.
- Variance/confounders and baseline or incompatibility: fallback raw samples above;
  official binary download denied; no claim that tool usefulness was demonstrated.
- Ordinary CI runs, selection, ordering, coverage, pass/fail and exits: untouched.
- Required checks, workflows, stores, schedulers and automated optimization: none.
- Independent QA: must verify the command/source provenance, access evidence,
  statistics and this limitation before a publication acceptance claim.

Return this deferred pilot and any future successful Hyperfine samples to #520.
Adopt a wrapper only after actual incremental value is demonstrated. An eventual
optimization belongs to its existing implementation owner. Rollback removes this
document; there is no runtime behavior to restore.
