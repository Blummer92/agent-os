# Campaign item admission (#3502)

## Purpose

An owner-approved finite implementation campaign must end with one
evidence-backed disposition per item, never a generic "blocked" summary built
from labels, missing headings, or unattempted preflights.
`agent_os_execution_service.campaign_item_admission` is a pure projection over
existing owners. It adds no readiness engine, lease, scheduler, queue, or
executor, and it grants no write, merge, closure, label-mutation, workflow, or
external-write authority.

## Per-item evidence and decisions

`classify_campaign_item_admission(evidence)` executes the canonical
`evaluate_issue_readiness` on the current issue body and consumes:

| Input | Rule |
|---|---|
| Readiness | Only the evaluator decides READY. `blocked` and `needs-decision` are verified blockers that carry the evaluator's exact checks, blockers and manual-review items as the smallest owner decision. |
| `status:*` labels | Compared with the canonical managed projection (`issue_operational_state`). One stale managed label under READY is `mechanical-drift` (projection repair only); unresolved or conflicting labels fail closed. Labels are never mutated here. |
| CKR6 | Admission comes only from a canonical result: the in-process owner or a `result-returned` ingress observation (`CKR6_GITHUB_BRIDGE.md`). A refusal is a verified blocker; `not-run`, `pending`, `ingress-failed`, and similar states mean admission was not completed. Admissibility must match the canonical status. |
| Concurrency | GitHub primary-PR claims are the cross-surface concurrency evidence: one active claim resumes it, more than one is `claim.multiple-primary`. A Workflow Scheduler lease is authority only for `governed-runner` and `scheduler` routes; there, missing lease evidence means admission was not completed. On other routes the lease is `not-applicable` and is never reported as clear or blocked. An observed active lease always blocks. |
| Authorization | The current direct owner instruction must cover the item. Each required excluded surface (for example `workflow`) needs its own separate authorization. |
| Repository seam | `identified` (with refs), `absent-verified` (a precise blocker, not an invented executor), or `not-investigated` (admission not completed). |
| Live acceptance | `required-not-authorized` never blocks offline repository delivery; it is reported as pending separately authorized acceptance. |

Each item is `admitted`, `verified-blocker`, or `admission-not-completed`, with
its distinct reason codes, unverified checks, and next action. An admitted item
carries the delivery obligations: GitHub Service Agent writer, one
issue-specific branch, focused tests, primary-PR creation admission, Draft PR,
and exact-head readback.

## Campaign rules

`classify_campaign_admission(items, shared_blockers=...)` keeps the supplied
order and requires unique items. Item-local blockers never stop independent
items. Only a shared authorization, source-of-truth, bounded-scope,
excluded-surface, capability, or material-decision blocker stops the remaining
items, and each stopped item keeps its own evidence row. `stop_permitted` is
false while any item is admitted or not yet completed, and
`generic_blocked_summary_permitted` is always false.

Only verified blockers produce `lane_evidence`, the finite no-PR lane input for
`classify_issue_batch_completion` (#2607). An incomplete admission produces
none, so the batch classifier cannot close that lane out as blocked.

`python -m agent_os_execution_service.campaign_item_admission --evidence <file.json>`
prints the campaign projection for a JSON `{items, shared_blockers}` file.
