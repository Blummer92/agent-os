# GitHub issue-comment ingress (#1203)

## Boundary

The v1 repository-side ingress accepts exactly:

```text
/agent-os resume <executor-handoff-id>
```

where the handoff identity is the canonical `executor-handoff:<64 lowercase hex>`
content identity already produced by executor routing.

The GitHub issue comment is transport data only. A successful envelope parse does
not create implementation authorization, Scheduler admission, lease ownership,
dependency readiness, executor authority, GitHub write authority, Ready-for-Review,
merge, issue closure, provider authority, or external-system authority.

## Event and identity rules

- only `issue_comment: created` is eligible;
- pull-request conversation comments are ignored;
- the v1 connector actor is exactly `Blummer92` and sender/comment-user evidence
  must agree;
- workflow reruns (`GITHUB_RUN_ATTEMPT != 1`) are blocked as executable transport
  authority;
- the body is parsed from `GITHUB_EVENT_PATH`, never interpolated into shell
  source;
- malformed commands, extra tokens, shell syntax, and non-canonical handoff IDs
  are rejected;
- duplicate comments for the same repository/issue/handoff produce the same
  deterministic logical-trigger identity. That identity is transport evidence,
  not a replacement Scheduler lease.

## Current dispatch disposition

The workflow deliberately stops after bounded transport validation and publishes
non-authorizing JSON evidence. Its dispatch result is:

```text
blocked: governed-runtime-control-path-not-yet-bound
```

This is intentional. Current architecture selects persistent GCE as the primary
Scheduler-host candidate, while GitHub Actions remains transport only. #1203 does
not authorize Google IAM, credentials, VM start/stop, deployment, or production
external execution, and no separately governed callable GCE control path is yet
bound to this workflow.

When that path is separately authorized and proven, the transport result must be
fed into the existing canonical state-reacquisition / ResumePlan / ExecutorHandoff
/ Scheduler path. Do not turn Actions concurrency, artifacts, comments, or this
logical-trigger identity into a second execution lease, queue, or retry system.

## Permissions and evidence

The workflow grants only:

```yaml
permissions:
  contents: read
```

It does not request repository-write, issue-write, pull-request-write, actions-write,
secret, cloud, or provider authority. The evidence artifact contains bounded
transport/result JSON only and intentionally excludes the raw comment body.

## Rollback

Revert the bounded workflow, parser, tests, and this runbook. No external service,
credential, runner, queue, database, or cloud resource is created by this
repository-side implementation.
