# #2299 — Codespaces developer-loop runner

## Purpose

Agent OS keeps one provider-neutral #918 governed-runner route while preferring
the existing `agent-os-codespaces-v1` environment for ordinary developer-loop
runtime work. GCE remains available when Codespaces is unavailable, stale, or
missing a required capability. Operations already classified as requiring an
autonomous VM host never select Codespaces; #2300 owns the detailed #759 /
Scheduler / fixed-host boundary.

## Composition

```text
operation requirements
-> current runtime observations
-> choose_governed_runner(...)
   -> Codespaces when current + capable + developer-loop eligible
   -> otherwise GCE when current + capable
   -> otherwise no capable governed runner
-> project selected runtime into existing #918 inputs
-> select_executor_route(...)
-> existing validation-route preference (#1573)
```

`choose_governed_runner` is a candidate preference only. It creates no executor
route enum, Scheduler, lease, capability registry, validation plan, transport,
credential, or authority. The selected candidate supplies #918's existing
`governed_runner_capabilities`, environment profile, environment-health evidence,
and workflow runtime identity.

## Developer-loop validation

Use the canonical validation plan/profile. Run the smallest sufficient focused
validation in the persistent Codespaces worktree and iterate there. Do not run a
second GCE validation for equivalent developer-loop evidence unless a distinct VM
capability is required. Aggregate validation remains owed only when the existing
admission/risk contracts require it; the final repository-visible exact-head gate
remains independent.

The focused selector maps `scripts/agent_os_execution_interface/` and its tests to
`python -m pytest tests/agent_os_execution_interface`. Aggregate runtime
optimization remains #2243 and measurement remains #520.

### Affected-package coverage for the ui-cross-platform-reference fixture (#3184)

PR #3128 changed only `05_Examples/ui-cross-platform-reference/package.json`
(Vitest 3.x → ^5.0.3). The exact-head aggregate passed, but its logs covered only
the structure, Python package, and root suites — the fixture's npm/Vitest tests
never executed, because the rule map had no focused owner for the fixture and a
`.json` change fell through to `profile.aggregate-unmapped-executable`.

The rule map now carries a fixture-owned focused rule,
`ui-cross-platform-reference`, covering `05_Examples/ui-cross-platform-reference/`.
A dependency-only `package.json` change there selects this single
affected-package command pair, executed in order:

```text
cd 05_Examples/ui-cross-platform-reference && npm install
cd 05_Examples/ui-cross-platform-reference && npm test
```

`npm install` re-resolves the fixture's private, lockfile-free dependencies so
the bumped vitest runtime is the tested runtime; `npm test` runs the vitest unit
suite. The bounded CI executor resolves both command texts to fixed
`("npm", "install")` / `("npm", "test")` argv in the fixture directory, and the
existing validation route executes them at the change's exact head SHA. The
bounded result evidence (stdout/stderr, exit status) returns bound to that head
SHA — the final repository-visible exact-head gate remains independent.

Third-party PR lineage is admitted without replacing the PR and without a
generic shell. The positive-PR selection route already admits any branch lineage,
so the Dependabot PR itself now selects the fixture's focused commands. The
`/agent-os dev-validate` ingress intentionally keeps its `agent/`-only admission
and fixed validation-identity allowlist; an `agent/` branch carrying the
identical dependency-only change can additionally be validated through the
existing pre-PR planning route against the same rule map. No workflow, runtime
provisioning, credential, or protected-setting change is involved.

## Current Codespaces access boundary

#1212 proved `gh codespace ssh` with the official Dev Container SSH feature, but
that closed qualification PR was not merged. #2299 does not silently reactivate
its devcontainer changes. Live use must consume current environment-health and
transport evidence; stale or unavailable Codespaces evidence falls back to GCE
through the same #918 route. Any devcontainer activation change is separately
validated before being treated as current capability.

## Governed ingress read-only pilot (#2931)

The first production consumer of the Codespaces preference is deliberately
narrow. The existing governed issue-comment ingress may use Codespaces only for
the accepted developer-validation envelope when all of these conditions hold:

- the validation identity is the already-qualified `remote-validation-suite`;
- the target is the one current Codespace resolved from live GitHub evidence
  (#2965): the read-only repository Codespaces listing must contain exactly one
  `Blummer92`-owned `Blummer92/agent-os` Codespace that is already `Available`.
  No Codespace identity is compiled in; zero, multiple, truncated, or malformed
  candidates are unavailable (the historical `literate-system-j4j4pr9g4q7h45q`
  pin could report `Shutdown` while a newer surface was current);
- the credential exposed to the step is the repository-scoped
  `AGENT_OS_CODESPACES_TOKEN` with Codespaces read permission only; and
- the remote environment-health result is `agent-os-codespaces-v1`, bound to
  that exact execution surface.

The workflow never starts, stops, exports, creates, edits, deletes, or publishes
a Codespace. A stopped, stale, mismatched, unauthenticated, or otherwise
unqualified Codespaces candidate is treated as unavailable and preserves the
existing GCE fallback. GitHub CLI is invoked with a fixed trusted command built
from the existing developer-validation request identity; caller-provided shell
or argv is not exposed.

Only `remote-validation-suite` participates in the developer-validation pilot.
Other developer-validation profiles remain on the existing GCE transport until
separately qualified for Codespaces. Discovery now prefers Codespaces too: the
`agent-os-governed-invocation` workflow resolves a Codespaces-first route per
ingress envelope (`workflow_scheduler.governance.codespaces_first_route`), and
the accepted discovery envelope runs the bounded read-only discovery adapter
(`workflow_scheduler.governance.discovery_codespaces`) on the current Codespace
before any GCE fallback. Discovery on Codespaces reuses the same single-current-
surface resolver, read-only token, and fixed `gh codespace ssh` transport as the
diagnostic and developer-validation pilots; the remote runner executes the
repository-owned handoff discovery entrypoint with a fixed argv and returns a
framed read-only evidence object bound to that execution surface. The remote
runner verifies the host-local checkpoint store (`invocations` directory) is
present before importing the discovery implementation: a Codespace without the
store reports `codespaces_capable=False` so the workflow falls back through the
existing GCE path instead of returning a misleading `not-found`. If the current
Codespace is unavailable, the repository checkout is missing, or the store is
absent, the run fails closed and the existing GCE path is preserved. First-run
validation, Scheduler/control, #759 containment, fixed-service-identity, host
maintenance, and other VM-specific operations remain GCE-owned under #2300.

The read-only token is a transport credential, not routing or execution
authority. Missing credential material leaves the prior GCE behavior intact.


## Reconstructed #2826 acceptance coverage

`tests/agent_os_remote_validation/test_issue_2826_continuation_acceptance.py`
adds a fixed, repository-owned controller experiment to `remote-validation-suite`.
It is reconstructed coverage, not the original external `test_scratch_harness.py`.
The existing operation identity, issue-comment grammar, qualification, SSH
transport, fixed suite command, 120-second timeout and cleanup remain unchanged.

The fixture compares unguarded early delivery and an artificial inner ceiling
against treatments using canonical investigation/finite-batch admission,
structured completion payloads and `drive_governed_continuation`. Test adapters
dispatch finite reads and reconcile an in-memory mutation receipt; no external
mutation is performed. Terminal delivery, genuine blocker, authorization/route
and currentness rejection, repeated no progress and hard-cap stops are checked.
The inner-ceiling treatment explicitly starts the next bounded driver batch
from the retained test cursor. This proves behavior of a controller that owns
the loop; it does not prove that native ChatGPT performs that re-entry.

The same fixture executes a fixed tuple of existing execution-interface
regressions: continuation driver/reachability, finite batch, investigation
completion, mission completion, subordinate-write/batch delivery and operation
target/mutation-currentness safety. The enclosing suite also runs the existing
#2220 real MCP continuation-payload tests. Child pytest has a 60-second bound;
collection errors, skipped coverage, absent modules and nonzero exits fail the
fixture. No caller can select child commands, paths or upload a probe.

At session teardown, `ISSUE_2826_ACCEPTANCE=` emits a compact JSON receipt through
pytest's terminal reporter into the existing bounded stdout evidence. It records
observed Python/pytest versions, reconstructed provenance, per-case pass receipts
and child-regression counts, exit status and duration. Unfinished/failed cases
are unverified. This test receipt supplements the existing route/health/SHA and
cleanup artifacts and is never execution or completion authority. Truncated or
missing evidence must be reported as an evidence gap, not inferred as a pass.

A local or GCE pass cannot satisfy Codespaces acceptance. A qualifying Codespaces
pass validates repository/controller behavior only; #2826's native ChatGPT
continuation and host-versus-client-transport attribution remain unresolved.

## Bounded GitHub MCP diagnostic consumer (#2947)

The governed issue-comment ingress also exposes one finite read-only diagnostic
identity for ChatGPT-driven Codespaces investigation:

```text
/agent-os diagnose ppux-canva-cdp-readonly <request-id>
```

This is not a generic shell. The caller supplies only the fixed diagnostic
identity plus a bounded request slug. The repository-owned diagnostic implementation
selects the same approved `agent-os-codespaces-v1` surface and existing
`gh codespace ssh` transport, then runs a checked-in fixed observation bundle.
Caller-provided shell, argv, URL, filesystem path, profile, port, or browser action
is not accepted.

The first diagnostic is deliberately read-only. It records current workspace
identity, Chrome process count, loopback listener reachability for the already-used
CDP control ports, and sanitized Chrome DevTools discovery metadata. It does not
click, navigate, edit Canva, start or stop the Codespace, expose a public port, or
emit browser-profile/authentication material.

A recognized diagnostic envelope is `handled` by the Codespaces diagnostic path
even when the approved Codespace is unavailable or the read-only credential cannot
reach it. In that case the path writes bounded fail-closed result evidence and does
not fall through to GCE. This keeps a Codespaces-specific diagnostic from silently
changing execution surfaces.

Result evidence is published through the existing governed-invocation artifact/log
path so GitHub MCP can read the workflow run, job/log, and JSON evidence and
continue the parent mission without owner copy/paste. This result publication is
separate from developer-validation success and creates no implementation, merge,
closure, production, credential, or browser-mutation authority.

### Adobe Express minimum probe (#3094)

The same dispatcher now admits one additional fixed identity:

```text
/agent-os diagnose ppux-adobe-minimum-probe <request-id>
```

The caller still supplies only the registered identity and bounded request slug.
The Adobe Express entry URL is fixed in repository code as
`https://new.express.adobe.com/`; URL, shell, argv, browser flags, profile paths,
ports, JavaScript, credentials, cookies, tokens, passwords, and MFA material are
not ingress fields.

The probe reuses `resolve_current_codespace()`, the existing
`agent-os-codespaces-v1` environment-health binding, and the existing
`gh codespace ssh` transport. It records only bounded platform, browser,
graphics, WebGL/WebGL2, navigation/classification, and cleanup evidence. It does
not authenticate to Adobe, inspect a stored browser profile, expose CDP, modify an
Adobe project, or mutate Codespace lifecycle state. Ordinary CI exercises only
synthetic/offline fixtures and never contacts Adobe.

The diagnostic does not install browser tooling. It first proves that a normal
Chrome/Chromium executable, Node, and the Playwright module are already available
on the selected surface; a missing prerequisite is
`CODESPACES_EXECUTION_PATH_BLOCKED`, not an Adobe compatibility result. The
base `agent-os-codespaces-v1` profile currently guarantees Python/Git/GitHub CLI
developer tooling but does not itself declare Node, Playwright, or Chrome/Chromium,
so live-probe readiness requires current evidence for those prerequisites.

A minimum-probe pass additionally requires a successful HTTP response below 400,
an allowlisted Adobe Express/account/auth surface, a non-empty bounded title, no
navigation error, and no bounded error/challenge/consent title classification.
An Adobe-origin error or generic page is therefore not sufficient for PASS.
Graphics-blocked classification requires an actually reachable response plus
explicit WebGL=false and WebGL2=false evidence. Browser cleanup is observed from
the fixed runner; an unconfirmed close or outer timeout is execution-path failure
rather than `cleanup_complete=true`.

Its disposition vocabulary is limited to
`CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM`, `CODESPACES_BLOCKED_GRAPHICS`,
`CODESPACES_ADOBE_MINIMUM_PROBE_PASS`, `CODESPACES_NETWORK_ONLY`,
`CODESPACES_EXECUTION_PATH_BLOCKED`, and `MANUAL_REVIEW`. Reaching
`/unsupported-browser` or an equivalent unsupported-system surface is an
unsupported-platform result. Reaching a normal Adobe login/application surface
without that rejection is only a minimum-probe pass; it does not prove
authentication, editor or capture functionality, general PPUX suitability, or
Tinkercad suitability. Transport failures remain execution-path failures rather
than Adobe compatibility failures.

## Developer-validation SSH start timeout (#2944)

For the developer-validation operation only, the exact `gh codespace ssh`
error `timed out while waiting for the codespace to start` (exit 1 with no
remote stdout) proves that the remote command did not begin. The route records
the requested SHA, validation identity, SSH exit code, and bounded reason,
then sets `selected=false` so the existing governed GCE fallback can run.
Other SSH failures, remote-result errors, and the read-only diagnostic operation
remain fail closed. The GCE result replaces the provisional developer-validation
result; the Codespaces reason remains in the route artifact.

## Target-bound lifecycle contract (#3345)

Repository-side lifecycle composition is deliberately separate from the existing
read-only `AGENT_OS_CODESPACES_TOKEN`. A caller with separately authorized
configuration may inject a lifecycle credential whose only required repository
permission is Codespaces lifecycle admin write. Repository code never creates,
rotates, stores, or broadens that credential.

The lifecycle target is authorization-bound and must match the canonical Agent OS
repository/owner surface returned by the existing #2965 resolver. One-shot
consumption is injected from the existing authorization owner; the lifecycle
adapter does not create a replay database or second authority store. The bounded
sequence is start when the pre-state is `Shutdown`, wait for GitHub `Available`,
independently prove `gh codespace ssh` readiness, consume one already-registered
operation, then stop the same Codespace in cleanup and read back `Shutdown`.
API `Available` alone is not execution readiness. Cleanup failure is a
fail-closed `needs-decision` result.

The stronger lifecycle credential is used only for the authenticated-user
lifecycle API. SSH readiness uses a distinct weaker transport credential, and
the registered operation receives neither credential. The two injected
credential values must be distinct.

The lifecycle adapter does not expose create/delete/rebuild/rename/export, a
generic shell, caller-selected arbitrary Codespace targets, repository-write
authority, merge/closure authority, or credential provisioning. Live lifecycle
use remains separately authorized configuration; offline tests use injected fake
credentials and provider calls only.

## Persistence and continuation

Codespaces repository/worktree files may persist across stop/start, while running
processes do not. Persistence never proves clean Scheduler termination and never
releases a lease. #1237 owns same-lineage continuation; a red focused test or
Codespaces capability mismatch is intermediate evidence, not parent-mission
completion.

### Preferred-surface unavailability is item-local (#3139)

A preferred Codespaces surface that cannot be directly observed or entered is an
item-local capability boundary, not a shared mission blocker, unless evidence
proves the limitation is shared across the remaining population. Finite missions
preserve their cursor and continue every independent operation still admissible
through canonical GitHub read evidence; see the ChatGPT Orchestrator overlay's
"Preferred Execution Surface Unavailability" section.

## Non-authorization

Runtime preference creates no implementation, GitHub-write, merge, issue-closure,
production, credential, workflow, protected-setting, or external-write authority.
