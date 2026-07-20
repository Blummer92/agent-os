# Agent OS Automation Readiness

Last verified: 2026-07-20 against `main` and current GitHub issue state.

## Purpose

This note summarizes implemented automation surfaces, their safe boundaries, and the
remaining approval gates. It is roadmap evidence, not authorization and not a second
source of truth for governance.

## Currently Implemented And Safe

- Manual, issue-scoped repository work through a descriptive branch and pull request.
- GitHub writes performed by the GitHub Service Agent after explicit user approval.
- Local aggregate validation through `./scripts/validate-all.sh`.
- Pull-request and manual-dispatch validation through `Agent OS Validation Gate`.
- GitHub-hosted validation on `ubuntu-latest`; no weekday schedule is currently defined.
- External comparison validation through `cloudbuild.yaml` when Cloud Build is available.
- Read-only or report-only issue acceptance, issue-label analysis, and label dry-run plans.
- Local Scheduler and project-execution dry-run models with no live external writes.
- Read-only Notion and Drive review, plus explicit handoffs to approved destinations.

## Implemented But Not Authorization

The following provide evidence or planning capability only:

- passing CI checks and validation summaries;
- issue-readiness and documentation-impact reports;
- proposed label additions from dry-run workflows;
- dependency graphs, queues, leases, validation states, and safe-parallel planning;
- dashboards, execution prompts, context packets, and audit-style reports;
- cached dependency restoration or scheduled analysis;
- dry-run Scheduler projections and worker-assignment models.

None of these authorize autonomous code changes, issue mutation, merge, external writes,
or changes to governance, readiness, approval, ownership, or sharing fields.

## Still Blocked Or Approval-Required

- Autonomous issue-to-code or issue-to-PR execution without explicit human approval.
- Autonomous merge or any worker-controlled merge gate.
- Production-system changes or irreversible artifacts.
- Automatic source-of-truth or governance updates.
- Live Google Drive writes outside an approved destination and governed workflow.
- Live classroom artifact generation before C3 (#118), C4 (#119), and explicit approval.
- Automatic changes to sharing, ownership, readiness, approval, or audit fields.

## Current Dependency Ladder

1. A1 (#106), A2a (#143), and A2 (#107) are completed historical foundations.
2. Current validation uses GitHub-hosted Actions plus the Cloud Build comparison lane.
3. Report-only and dry-run tooling may expand while preserving non-mutation boundaries.
4. C3 (#118) must prove the Scheduler-to-Materials-Coach path without live Drive writes.
5. C4 (#119) and explicit approval are required before one governed live artifact run.
6. Autonomous issue-to-PR or merge requires a separate approved governance change.

The original self-hosted-runner design remains historical context; it is not the current
validation architecture described by this note.

## Execution Surfaces And Boundaries

| Surface | Current boundary |
|---|---|
| Local validation | Manual, read-only repository checks |
| GitHub Actions | PR and manual-dispatch validation on `ubuntu-latest` |
| Cloud Build | External aggregate comparison; no GitHub mutation |
| GitHub Service Agent | Approved branches, commits, issues, and pull requests only |
| Report workflows | Read-only evidence and dry-run plans; no approval or mutation |
| Workflow Scheduler | Local dry-run planning; no live dispatch or external writes |
| Notion | Planning and working knowledge; read-only unless explicitly approved |
| Google Drive | Approved classroom destinations; live writes require approval |

## Stop Conditions

Stop before automation when authorization, target, system of record, or field ownership
is unclear; when a dry-run boundary would be crossed; or when work would modify a live
system, protected setting, governed field, or irreversible artifact without approval.

## Maintenance Rule

Re-verify this note when runner type, workflow triggers, required checks, governance,
write authorization, C3/C4 status, issue-to-PR authority, merge authority, or external-
write capability changes. Repository workflows, governance files, and open issue state
remain authoritative when this summary conflicts with current evidence.

## Status

Agent OS is ready for governed manual implementation, validation, reporting, and dry-run
planning. It is not authorized for autonomous implementation, autonomous merge, or live
classroom artifact generation.