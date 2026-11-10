# Optional Python sampling profiles

Issue: #3697. Measurement owner: #520. Existing aggregate/suite timing owner:
#1359. Profiling is advisory and opt-in; it never replaces validation.

## Pilot outcome

**Adoption deferred on the original pilot host (2026-10-21): the profiler could not be installed through that host's tested package routes.**
This is an observed package-access limitation, not evidence that py-spy is
incompatible with Agent OS or that process-memory access is denied. No profiler
wrapper, dependency, CI tracing, workflow, or runtime change is introduced.

Pilot source boundary: Agent OS main
`f522f1dd9863c610e3771723274aa9c503889d80`. Host: Linux x86_64;
CPython 3.12.14; isolated venv pip 25.0.1. The host had no `py-spy`
executable. Both package-installation attempts below returned exit 1 and
`No matching distribution found for py-spy`:

```bash
python -m venv /tmp/agent-os-profile-venv
/tmp/agent-os-profile-venv/bin/python -m pip install py-spy pytest
/tmp/agent-os-profile-venv/bin/python -m pip install py-spy --index-url https://pypi.org/simple --retries 0 --timeout 10
```

The pilot used a campaign-local isolated venv rather than the example `/tmp`
path. Failure to install the first requirement also means that invocation did
not establish pytest availability. No package version was installed, no target
was launched by py-spy, no PID was attached, and no permission/sandbox change
was attempted. Flamegraph count and profile sample count are both **0**.
A bounded download attempt for the upstream v0.4.2 Linux x86_64 wheel also
returned HTTP 403 (`curl --fail --location`, exit 22); no binary was obtained.
Sampling overhead, attach permissions, launch-mode permissions and runtime
compatibility remained **unmeasured on that original pilot host**. The failed
package lookup is not a profile and must never be reported as successful
measurement.

### Later independent QA capability observation (2026-10-21)

The four-lane independent acceptance review reported that **a different QA host**
installed `py-spy 0.4.2` and ran it without elevated privileges. It reported a
synthetic run of 330 samples and a run against the actual readiness test suite
of 76 samples with an approximately 216 KB flamegraph. Those observations
contradict any *general* claim that py-spy cannot be installed or launched;
they do **not** invalidate the original host-specific install failures above.
This section is secondary evidence from that QA report, **not a profiling run
performed by this documentation repair**. Full reproduction provenance
(exact profiling source SHA, host details, command, profile digest, sampling
errors, wall duration and raw profile) was not supplied in the acceptance
summary and is **NOT VERIFIED** here; it must not be guessed or backfilled.

The synthetic run is not representative Agent OS performance evidence. The
readiness suite completed too quickly in the companion timing pilot to justify
claiming an expensive hotspot. Neither QA smoke test identifies a verified
expensive hot path or establishes sampling overhead; AC-3 remains open until
an evidence-selected representative target is profiled and interpreted.

## Measured target selection

The companion #3695 pilot executed the current-main
`tests/agent_os_issue_acceptance/test_readiness.py` suite once with
`--durations=20 --durations-min=0`: **43 passed in 0.21 s**. All displayed top-20
call phases rounded to 0.00 s. The first ranked node was
`test_legacy_build_issue_headings_are_recognized_but_require_tier_decision`,
but that rank does not establish an expensive function or fixture.
One short-suite sample cannot justify an expensive-hotspot claim. Target
selection therefore remains deferred; no synthetic repetition is used to
manufacture a long-running profiling target. No flamegraph or hot-path
conclusion is claimed for this suite.

## Least-privilege reproduction on a capable development host

First use actual #520/#1359 timing or pytest duration evidence to select at most
two expensive Python targets. Preserve the measured target's exact command,
working directory, selected tests, coverage options, environment, input/fixture
identity and source SHA. Do not select a production process or profile the
whole repository without a measured reason.

Install py-spy only in a disposable local tool environment if the host permits
it. Record the installed version and retain `py-spy record --help` for that
version; supported flags and interpreter compatibility must be checked against
that executable. Record `git rev-parse HEAD`, `git status --porcelain`, Python
version, platform, CPU, and the prior duration evidence. A dirty checkout must
be identified; a SHA alone does not identify uncommitted content.

For a measured pytest target, launch the target as py-spy's own child rather
than attaching to an arbitrary PID. Substitute the already-measured target and
its original options into this command (the placeholders are not executable):

```text
py-spy record --rate 100 --format flamegraph --output /tmp/agent-os-profile.svg -- python -m pytest <measured-target> <original-options>
```

Run once per selected bounded target. Use an existing test timeout/bounded
fixture; do not add another ordinary CI execution. A local opt-in profile is a
separate diagnostic run and is counted as such in #520. Do not use `--locals`,
collect credentials, profile an unauthorized process, elevate privileges,
change ptrace/sandbox settings, or add container capabilities. If launch mode
fails, retain its exit code and diagnostic, classify `permission-denied`,
`unsupported-runtime`, `tool-error`, or `unknown` only as the evidence supports,
and stop. A partial output file does not convert a failed command to success.

py-spy's upstream documentation describes Linux child-launch profiling as a
possible unprivileged alternative to PID attachment. That possibility does not
prove this host permits it. If the installed tool is unavailable, record
`tool-unavailable`; do not fabricate a launch or attach result.

## Bounded evidence to #520

Retain the command exit status, profiler stderr, profile output byte size and
SHA-256, py-spy/Python versions, actual source SHA and dirty state, target
command/working directory, host/CPU, timestamp, rate, observed wall runtime,
number of samples and sample failures as exposed by the installed tool. Keep
raw profiles local and review paths/symbols before sharing. Record a
machine-readable result using these fields; `null` means unmeasured, not zero:

```json
{
  "source_sha": "f522f1dd9863c610e3771723274aa9c503889d80",
  "source_dirty": null,
  "status": "tool-unavailable",
  "profiler_version": null,
  "target_command": null,
  "sampling_rate_hz": null,
  "wall_seconds": null,
  "sample_count": 0,
  "profile_sha256": null,
  "overhead_fraction": null,
  "limitations": ["pilot package installation unavailable"]
}
```

This example describes the pilot limitation; it is not a successful profile.
Only set `source_dirty=false` for a clean, verified target checkout; the pilot
had no profiling target checkout, so its dirty state is null. Keep executed-source identity distinct from the documentation
implementation head. Any later profile must bind both to actual readback.

For overhead, compare the same bounded command with and without profiling on
an otherwise comparable host/configuration. Report raw samples, actual `n`,
median and p90 with a declared percentile convention; note low confidence
when samples are sparse. Do not derive a speedup or stable overhead estimate
from one run. Profiler overhead and a target optimization are separate effects.
The normal CI path must not run twice to collect either number.

## Interpretation limits

- Stack sample proportions indicate observed execution, not causal proof that
  a function should be changed. Retain sampled count and error count.
- Default active-thread filtering can omit waits. An idle-inclusive run answers
  a different question and must be labeled separately; waiting is not CPU time.
- Python frames do not fully explain native extension CPU costs. Native-mode
  support, symbols and overhead vary and were not evaluated in this pilot.
- Child-process work is not automatically attributed to the parent. Subprocess
  profiling changes the measurement scope and must be deliberate and labeled.
- Short import/startup phases may finish between samples or before attachment.
  A missing import frame does not prove imports are cheap. Use separate
  opt-in import timing if a measured startup problem warrants it.
- Profiles can contain filesystem paths and symbols; never collect locals or
  publish secrets. Do not assume a flamegraph is safe merely because it is SVG.

## Follow-up and acceptance boundary

Although subsequent independent QA demonstrated that py-spy 0.4.2 could install
and launch without elevated privileges on its host, a representative expensive
Agent OS target still needs selection from #520/#1359 timing evidence, a bounded
profiling run with full exact-source provenance, inspected hot-path output,
qualified overhead, and independent QA of those findings before AC-3 is met.
This documented pilot plus subsequent QA smoke test do **not** establish
concrete hot functions or justified optimization recommendations.
No fallback profiler or second performance framework is introduced.

Rollback is removal of this document. No persistent runtime state, repository
configuration or validation command is changed.

## Primary tool references

- [Upstream py-spy README](https://github.com/benfred/py-spy/blob/master/README.md)
  (inspected blob `91372efe3a975f4e26037f4075394db8cd16afd1`): installation,
  child launch, platform/interpreter support, idle filtering and limitations.
- [Upstream v0.4.2 release](https://github.com/benfred/py-spy/releases/tag/v0.4.2):
  release inventory was readable; this does not establish binary execution.
- [MIT license](https://github.com/benfred/py-spy/blob/master/LICENSE).
