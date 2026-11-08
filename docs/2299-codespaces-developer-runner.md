# #2299 — Codespaces developer-loop runner

## Purpose

Agent OS reuses the provider-neutral #918 governed-runner contracts while
using the existing `agent-os-codespaces-v1` environment for qualified ordinary
developer-loop operations. Governed issue-comment discovery, developer validation,
and diagnostics never fall back to GCE. A missing, stale, unauthorized, incapable,
or failed Codespace produces bounded failure evidence. This follows the owner's
[2026-10-14 Codespaces-first decision](https://github.com/Blummer92/agent-os/issues/3333#issuecomment-6178339957).
GCE resources remain preserved under #3102; no VM-only operation is qualified for
Codespaces by this route change.

## Composition

```text
operation requirements
-> current runtime observations
-> choose_governed_runner(...)
   -> Codespaces when current + capable + developer-loop eligible
   -> otherwise GCE candidate metadata when current + capable
   -> otherwise no capable governed runner
-> project selected runtime into existing #918 inputs
-> select_executor_route(...)
-> existing validation-route preference (#1573)
```

`choose_governed_runner` is a candidate preference only. It creates no executor
route enum, Scheduler, lease, capability registry, validation plan, transport,
credential, or authority. The Codespaces implementation dispatcher refuses a
GCE selection rather than invoking GCE. The selected candidate supplies #918's existing
`governed_runner_capabilities`, environment profile, environment-health evidence,
and workflow runtime identity.

### Production consumer (#3333)

`scripts/agent_os_execution_interface/codespace_implementation_dispatch.py` is
the canonical production consumer of this chain for an already-admitted
implementation mission: `dispatch_admitted_operation_to_codespace(...)` runs
`choose_governed_runner` → `executor_route_inputs` → `select_executor_route`
(requiring `CHATGPT_GOVERNED_RUNNER`) → the #3335 `TransportRequest` /
`run_codespace_transport`, failing closed with reason-coded evidence at each
junction. It creates no second router, transport, or authority.

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
transport evidence; stale or unavailable evidence blocks ordinary ingress.
The generic preference function can still describe GCE candidates; it executes
no provider operation. Any devcontainer activation change is separately
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
unqualified Codespaces candidate produces an explicit failure receipt.
No alternate execution is attempted, including after the CLI pre-start timeout. GitHub CLI is invoked with a fixed trusted command built
from the existing developer-validation request identity; caller-provided shell
or argv is not exposed.

Only `remote-validation-suite` participates in the developer-validation pilot.
Other developer-validation profiles return `codespaces-profile-not-qualified`
without executing either provider. Qualification of a replacement remains a
separate decision; historical GCE support is not Codespaces capability evidence.

Discovery reuses the same current-surface selection, read-only token, fixed SSH
transport, and provider-neutral handoff-discovery contract. Its checkpoint store
defaults to `/workspaces/agent-os-state/checkpoints`, matching the devcontainer.
A missing checkout, missing store, failed SSH, malformed response, or unavailable
Codespace retains its own reason-coded `needs-decision` receipt. The independent
`codespaces-discovery-result.json` copy remains available for existing evidence
consumers. GCE discovery is retired and is never an ordinary alternate route.

The workflow only invokes discovery for a discovery envelope, so it cannot
overwrite a failed developer-validation receipt. Developer validation always
writes its SHA/profile-bound result when its request is recognized. The existing
gate still requires success, exit code zero, matching branch/SHA/profile, and
completed cleanup; it rejects unsupported or failed routes. Ordinary route
evidence retains `gce_fallback_allowed=false` for schema compatibility, but no
cloud step consumes that field as authority.

Fixed-host inspection, governed resume/control, PPUX projection, and publication
activation remain separately implemented GCE paths; no new migration or live
qualification is claimed. The owner-only `host_install.outputs.requested` branch
was retired in GCE Wave 1: the governed workflow no longer classifies, authenticates,
or runs a host-runtime installation, and the former `/agent-os install-host-runtime`
comment is ignored through canonical ingress. The owner decision forbids GCE
reactivation/reinstallation; #3102 resource disposition and any further repository
retirement remain separately gated.

The read-only token is transport access, never implementation authorization.
The fixed #3333 implementation pilot separately requires canonical descriptor,
authorization, currentness, health, and lease evidence; its Actions entry remains
fail closed. Discovery and test success do not establish pilot qualification.


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

The former #2944 SSH-start-timeout-to-GCE fallback was retired by PR #3820.
For developer validation, a `gh codespace ssh` start timeout now preserves the
requested SHA, validation identity, SSH exit code, and bounded
`dev-validation-codespaces-ssh-failed` reason. The developer-validation gate
rejects this non-success result. No GCE authentication, VM start, or alternate
provider execution is attempted. Other SSH failures and malformed remote
results also fail closed; read-only diagnostics retain their own bounded
receipts. A successful workflow conclusion for a non-gated diagnostic is not
proof of a successful Codespaces operation.

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
credential values must be distinct. Each `gh` child inherits the caller's
environment (PATH, HOME, proxy, and CA settings) with inherited `GH_TOKEN` and
`GITHUB_TOKEN` removed and only the selected credential set as `GH_TOKEN`;
replacing the whole environment bypasses a credential-injecting proxy and
surfaces as HTTP 401.

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


### Replacement Codespace environment qualification (issue #3463)

The existing #2947 diagnostic ingress now recognizes one additional fixed, read-only
operation identity: `codespaces-environment-qualification-readonly`. The
registered owner-authored issue-comment grammar is:

```text
/agent-os diagnose codespaces-environment-qualification-readonly <request-id>
```

The request ID is a bounded lowercase slug. It is not a Codespace name,
terminal command, URL, path, port, profile, or permission grant. The operation
uses the existing #2965 resolver to select the one current owner/repository-
qualified `Available` Codespace, then uses the existing bounded
`gh codespace ssh` transport and verifies `CODESPACE_NAME`, the fixed
`/workspaces/agent-os` checkout, and the existing
`agent-os-codespaces-v1` environment-health contract. The result includes a
bounded workspace commit identity, content-bound environment-health evidence,
fail-closed reason codes, and existing workflow/job/artifact correlation. No
browser, port, lifecycle, credential, GitHub-write, or production mutation is
authorized. An unavailable or ambiguous Codespace is a diagnostic blocker,
not a reason to silently execute this Codespaces-specific diagnostic on GCE.

The existing workflow's `--allowed-actor Blummer92` rule remains unchanged:
registration does not authorize an assistant-authored trigger or prove native
ChatGPT dispatch. A live replacement-VM acceptance needs the authorized
owner-actor ingress, actual SSH/health result, GitHub Actions run/job/artifact
readback, and host consumption without an operator terminal relay. A
successful workflow with its Codespaces step skipped is not acceptance.
Changes to `.github/workflows/**`, actor admission, credentials, or
Codespace lifecycle require separate exact authorization. Issue #3463 remains
open for the broader host-routing and live-acceptance obligations.


### Fixed read-only SSH stage isolation (#3345 follow-up)

When the `codespaces-environment-qualification-readonly` operation selects one
current `Available` Codespace, the existing diagnostic runner now performs
two fixed read-only preflight commands before the full environment-health probe:
`gh codespace ssh -c <resolved> -- true` and a Python startup marker.
These are diagnostic operations, not general-purpose shell/argv authority.
Each preflight has a bounded 25-second timeout and distinct
`codespaces-ssh-probe-*` or `codespaces-python-probe-*` failure codes.
The original 90-second bounded full diagnostic remains unchanged and runs
only after both preflights succeed. A successful SSH preflight alone is not
environment-health PASS; the full identity-bound health receipt is still required.
An SSH preflight timeout cannot distinguish network establishment from
authentication or remote shell readiness and must not be overclassified.

No Codespace lifecycle mutation, token scope change, actor-allowlist change,
GitHub Actions workflow edit, browser credential exposure, or production action
is part of this stage-isolation increment. The live owner-reported replacement
Codespace remains subject to independent QA and correlated artifact readback.


### Fixed read-only CLI authentication preflight (#3345 follow-up)

Before the two SSH/Python qualification stages, the fixed diagnostic now
checks `gh api --method GET /user --jq .login` using the same transport
credential. It returns only a bounded status/reason, never the user identity,
token, stderr, or raw API response. The 12-second authentication timeout and
fail-closed classifications distinguish CLI API authentication failure from
subsequent SSH-stage timeout. A successful API authentication check **does not**
establish SSH authorization, network connectivity, or environment health.
The fixed `gh codespace ssh` commands and their existing timeouts remain
unchanged. No lifecycle mutation, credential or workflow edits are included.


## Teacher OS frontend validation (proposed, not yet runtime-qualified)

The existing affected-package selector recognizes the Teacher OS web executable surface (`08_Tooling/teacher-os-web/src/`, `08_Tooling/teacher-os-web/tests/`, plus `package.json`, `package-lock.json`, `tsconfig.json`, `index.html`, `playwright.config.ts`) and selects these exact commands, bound to that directory and in this order. Documentation-only changes (e.g. `README.md`) remain static:

1. `npm ci`
2. `npm run build`
3. `npm run test:unit`
4. `npx playwright install chromium`
5. `npx playwright test`

The executor admits only the fixed argument vectors, not arbitrary caller commands. Selection and command admission do not prove runtime success. `npm ci` requires a genuine dependency-resolved `package-lock.json` on the Teacher OS implementation branch. Until a qualified npm registry executor generates and verifies that lockfile, this plan is **blocked**, not passing. The existing workflow's Node setup and browser dependencies must also be qualified; workflow edits remain separately authorization-gated. Actual command exit codes, stdout/stderr, exact checked-out head and browser evidence are required for QA acceptance. A passing build does not establish a working preview or production integration.

## Owner-only remote Codespaces startup (#3345)

The existing `codespaces_lifecycle.py` remains the canonical start/SSH-readiness/
stop controller for one-shot operations. The new `codespaces_remote_start.py`
is a **start-and-verify** adapter for a developer session that should remain
running; it reuses the same lifecycle API helpers and SSH readiness checks.

The GitHub Actions ingress accepts only the exact owner-authored comment
`/agent-os codespace-start` on issue #3345. It runs in a separate serialized
job with no GCE fallback, no arbitrary Codespace target, no generic shell and
no GitHub repository-write permission. The normal governed ingress explicitly
excludes this command. A workflow rerun is rejected. An already Available
Codespace is verified without issuing a second start.

The lifecycle job needs two **separate** repository secrets:
`AGENT_OS_CODESPACES_TOKEN` (existing Codespaces read/SSH credential) and
`AGENT_OS_CODESPACES_LIFECYCLE_TOKEN` (separately provisioned fine-grained
user credential with Codespaces lifecycle admin write for only
`Blummer92/agent-os`). Do not widen the existing read token. This PR
does not create or inspect secret values. An absent or identical credential
fails closed before API access. Lifecycle credentials are used only for
authenticated-user state/start calls; the read token is used for canonical
discovery and SSH readiness.

The adapter requires exactly one owner/repository-qualified Codespace in
Shutdown or Available state, compares independent pre-state evidence and
rechecks identity before a start, then waits for both GitHub Available state
and SSH readiness. A nonzero/timeout start outcome remains uncertain and is
never automatically retried. No stop is issued: the existing Codespaces
idle timeout remains responsible for inactivity shutdown. This is an explicit
developer-session policy distinct from the #3345 one-shot start/execute/stop
contract; do not silently replace that contract.

This is **code and CI integration only**, not proof of a live remote start.
The workflow must not be exercised until its exact-head validation and
independent QA pass and the separate lifecycle credential is configured
through an authorized settings operation. GitHub Actions success without a
`codespaces-ssh-ready` receipt is not acceptance.

