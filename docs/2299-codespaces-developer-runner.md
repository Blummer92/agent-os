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

## Persistence and continuation

Codespaces repository/worktree files may persist across stop/start, while running
processes do not. Persistence never proves clean Scheduler termination and never
releases a lease. #1237 owns same-lineage continuation; a red focused test or
Codespaces capability mismatch is intermediate evidence, not parent-mission
completion.

## Non-authorization

Runtime preference creates no implementation, GitHub-write, merge, issue-closure,
production, credential, workflow, protected-setting, or external-write authority.
