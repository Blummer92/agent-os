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
- the target is the exact approved Codespace
  `literate-system-j4j4pr9g4q7h45q`;
- GitHub reports that Codespace belongs to `Blummer92/agent-os` and is already
  `Available`;
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

Only `remote-validation-suite` participates in this pilot. Other developer-
validation profiles remain on the existing GCE transport until separately
qualified for Codespaces. Discovery, first-run validation, Scheduler/control,
#759 containment, fixed-service-identity, host maintenance, and other VM-specific
operations remain GCE-owned under #2300.

The read-only token is a transport credential, not routing or execution
authority. Missing credential material leaves the prior GCE behavior intact.

## Persistence and continuation

Codespaces repository/worktree files may persist across stop/start, while running
processes do not. Persistence never proves clean Scheduler termination and never
releases a lease. #1237 owns same-lineage continuation; a red focused test or
Codespaces capability mismatch is intermediate evidence, not parent-mission
completion.

## Non-authorization

Runtime preference creates no implementation, GitHub-write, merge, issue-closure,
production, credential, workflow, protected-setting, or external-write authority.
