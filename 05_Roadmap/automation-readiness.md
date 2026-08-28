# Agent OS Automation Readiness

Last verified: 2026-08-21 against `main` repository implementation and governing contracts.

## Purpose

This note summarizes implemented automation surfaces, their safe boundaries, and remaining approval gates. It is roadmap evidence, not authorization and not a second source of truth for governance. Current implementation and governing standards win when this summary drifts.

## Currently Implemented And Governed

- Issue-scoped repository work through the Safe Implementation Lane after current eligibility, `status:ready`, explicit owner instruction, bounded scope, and authorization are established.
- GitHub Service Agent as the sole ordinary repository implementation and GitHub write owner across programming languages, providers, and integration domains.
- Internal registered-owner continuation for already-authorized work without requiring user copy/paste handoffs solely because responsibility changes.
- Resume of one valid issue-linked branch, Draft PR, or checkpoint lineage after current authorization, scope, head, checkpoint, and Scheduler lease evidence are reacquired.
- Connector-native zero-runtime execution for an already-authorized exact GitHub operation when the canonical executor route requires no runtime capability; the fast-track consumer itself grants no authority and performs no mutation.
- Governed-runner routing for work that requires checkout, process execution, dependency/runtime inspection, tests, builds, or other declared runtime capabilities.
- Focused developer-loop validation before Draft PR creation when required by the issue, followed by authoritative aggregate validation bound to the exact final PR head.
- Pull-request and manual-dispatch validation through `Agent OS Validation Gate`; Cloud Build remains a supplemental Linux validation surface under current repository policy rather than an exclusive final gate.
- Terminal Fast Lane as an opt-in, narrowly bounded release ceiling for eligible Tier 0/1 `no-external-write` work, composed through existing request interpretation, merge/lifecycle authorization, exact-head validation, and terminal reconciliation contracts.
- Read-only/report-only issue acceptance, metadata analysis, dry-run planning, and other non-authorizing evidence surfaces.

## Implemented But Not Authorization

The following may provide routing, execution, validation, or planning evidence without creating authority:

- passing focused tests, CI checks, Cloud Build runs, and validation summaries;
- issue-readiness, acceptance, documentation-impact, and metadata reports;
- executor-route decisions and connector-native/governed-runner capability evidence;
- checkpoints, ResumePlans, queues, Scheduler leases, validation states, and safe-parallel planning;
- dashboards, execution prompts, context packets, restart capsules, and audit-style reports;
- dependency-readiness and environment-health evidence.

A capability, route, checkpoint, label, passing test, or automation result never creates repository-write, merge, external-write, governed-field, production, or source-of-truth authority by itself.

## Still Blocked Or Separately Authorized

- Unbounded or unattended issue-to-code execution without a current governing authorization envelope.
- Merge or issue closure outside the applicable explicit merge/lifecycle authorization contract; ordinary Safe Implementation Lane does not authorize either.
- Auto-merge, protected-branch/ruleset/required-check changes, workflow changes, credentials, secrets, IAM, or permission expansion.
- Production-system changes, deployments, irreversible artifacts, or persistence-path authority changes outside separately approved scope.
- Automatic source-of-truth, ownership, governance, readiness, approval, audit, sharing, or governed-field mutation.
- External-system writes, including Workspace/Drive/Docs/Sheets/Gmail/Calendar/Apps Script operations, unless the exact external capability route is separately authorized.
- Treating Cloud Build as the exclusive Ready-for-Review final gate without a separate governed workflow/project-settings decision.

## Validation Model

```text
bounded implementation
-> smallest required focused developer-loop checks on a capable authorized surface
-> Draft PR
-> authoritative aggregate bound to the exact final PR head
-> Ready-for-Review only when required exact-head evidence and review state permit it
```

Focused local or VM success is non-final evidence. One clean exact-head aggregate may satisfy the full-suite requirement when the governing workflow accepts that provider. Cloud Build remains supplemental under current policy.

## Execution Surfaces And Boundaries

| Surface | Current boundary |
|---|---|
| Connected GitHub surface | Zero-runtime exact operations only after canonical routing and current write authority; no authority created by the adapter |
| Governed runner / Execution VM | Runtime-required developer-loop work through existing handoff, environment, Scheduler, checkpoint, and resume contracts |
| GitHub Actions | Repository-visible PR/manual validation and exact-head aggregate evidence under current workflow policy |
| Cloud Build | Supplemental Linux aggregate evidence; no repository mutation and not the exclusive final gate |
| GitHub Service Agent | Sole authorized repository implementation/write owner; bounded branches, commits, PRs, and approved issue metadata operations |
| QA / Test Agent | Independent validation and evidence; evidence is non-authorizing |
| ChatGPT Orchestrator | Routing, source-of-truth, capability, risk, and external-operation classification; no direct GitHub repository writes |
| Notion / Workspace | Separate destination and write-authorization contracts; repository authorization does not transfer |

## Safe Implementation And Resume Boundaries

A direct owner instruction such as `work on #123` can activate an eligible Safe Implementation Lane issue only after live readiness and authorization checks. If the sole missing prerequisite is the mechanical `status:ready` state, an authorized readiness mutation may converge it and the same still-current instruction may continue; that continuity does not survive blockers, scope/ownership conflict, excluded surfaces, or an active/ambiguous lease.

Existing valid branch/PR/checkpoint lineage is normally a resume target rather than a reason to create duplicate work. Scheduler lease evidence remains the concurrency authority. Head or base drift invalidates only the evidence required by the owning contracts and never widens authorization.

## Terminal Fast Lane Boundary

`work on #<issue> in fast lane` is interpreted through the canonical structured request path. For eligible Tier 0/1 `no-external-write` work it can carry a release ceiling into the existing merge and implementation-issue-closure authorization machinery; it does not directly set merge or closure authority. Tier 2, workflow, protected-setting, credential, production, external-write, and other excluded surfaces remain separately gated.

## Stop Conditions

Stop when authorization, target, source of truth, ownership, bounded scope, execution capability, currentness, or lease state is ambiguous; when a required developer-loop check has no capable authorized route; or when work would cross an excluded, protected, production, governed, irreversible, or external-write boundary without its own approval.

## Maintenance Rule

Re-verify this note when executor routing, runner/VM behavior, workflow triggers, final-validation provider policy, required checks, Safe Implementation Lane, Terminal Fast Lane, Scheduler/checkpoint semantics, write authorization, merge/closure authority, or external-write capability changes. Repository implementation and governing standards remain authoritative when this summary conflicts with them.

## Status

Agent OS supports governed issue-scoped implementation, same-lineage continuation, capability-based execution routing, focused pre-PR validation, and exact-head final validation. It is not a blanket autonomous coding or merge system: authority remains bounded by current issue eligibility, explicit owner decisions, canonical write contracts, and excluded-surface gates.
