# Ready-for-Review admission via the governed GitHub issue-comment route (#3446)

Owner: GitHub Service Agent. Canonical issue: #3446. Related: #3463 (route
classification, PR #3481), #3372 (optional custom-MCP host publication), #3281.

## Route-capability matrix

| Operation | Route | Status |
|---|---|---|
| Read PR/issue/checks, native Mark Ready, readback | Connected GitHub MCP | Available |
| Fixed Ready admission (`/agent-os ready-admit`) | GitHub MCP issue comment -> `agent-os-governed-invocation` -> GitHub-hosted consumer -> receipt | Ingress + consumer implemented here; workflow job in this change |
| Fixed Codespaces/GCE operations | Same ingress, Codespaces-first router | Unchanged; Ready is deliberately **not** routed there |
| `admit_agent_os_ready_for_review_tool` over MCP | Optional repository-local server | Unchanged; #3372 owns host publication |

## Fixed request

Post on an open issue (not a PR conversation) as the allowed owner actor, exact text:

```text
/agent-os ready-admit <pr-number> <head-sha-40-hex> <body-sha256-64-hex>
```

`body-sha256` is the SHA-256 of the UTF-8 PR body (empty string when absent). The
grammar is a single fullmatch; there is no shell, argv, module, URL, or JSON
payload. Ingress reason: `accepted-ready-admission-envelope`. Ingress grants no
execution authority; `codespaces_first_route` resolves the envelope to
`preferred="none"`, so it can never reach the Codespaces/GCE transports.

## Consumer

`python -m scripts.agent_os_issue_labels.ready_admission_actions` re-validates the
ingress record, independently reacquires the PR with a read-only token (state,
draft, head SHA, title/body, latest reviews, review threads, `Run validation plan`
check, `agent-os/authoritative-aggregate` status), binds head SHA and body
revision, and calls the single canonical evaluator
`evaluate_ready_for_review_admission`. The owner actor's fixed comment is the
explicit Ready request. No canonical close-issue authorization is reacquirable
here, so any GitHub-effective closing reference refuses
(`unauthorized-closing-reference`).

The receipt (`ready-admission-receipt:<sha256>`) is reason-coded, content-addressed,
and carries every authority flag as `false`. It is published as the
`agent-os-ready-admission-<run>-<attempt>` Actions artifact, the job summary, and the
job log.

## Host consumption contract (ChatGPT via connected GitHub MCP)

1. Compute `sha256(body)`; post the fixed comment on the owning issue.
2. Observe the `Agent OS Governed Invocation Ingress` run; read the receipt.
3. Immediately before mutation, re-read the PR and call
   `verify_ready_admission_receipt` (head, body, trigger id, repository, PR,
   duplicate receipt id). Any failure stops this item only.
4. Only then call native `mark_pull_request_ready_for_review`; read back `draft=false`.
5. Consume the Ready-triggered authoritative aggregate. For a provisional Ready,
   non-success, pending, or head drift requires converting back to Draft
   (`evaluate_provisional_ready_reconciliation`).
6. In a batch, record each item's disposition (`run_ready_batch`) and continue past
   item-local blockers such as #3411 or PR #3449.

Repeating the same request yields the same trigger id and receipt id; the host must
not re-post identical handoffs while a matching unconsumed receipt exists.

## Workflow integration

Owner-approved (2026-10-09) minimal change to
`.github/workflows/agent-os-governed-invocation.yml`: the `ingress` job skips the
`/agent-os ready-admit` trigger, and one new read-only `ready_admission` job
(`contents`/`pull-requests`/`checks`/`statuses: read`, no secrets, no GCP auth)
parses the envelope with the existing ingress module, runs the consumer, and
publishes the summary and `agent-os-ready-admission-<run>-<attempt>` artifact.
Contract tests: `tests/test_agent_os_ready_admission_workflow.py`.

Live acceptance (host-observed Draft -> Ready, negative refusals, Ready-triggered
aggregate, mixed batch) remains open under #3446 until this job is on `main`.
