# Agent OS ChatGPT MCP Facade — #1966

## Purpose

This is the explicit ChatGPT-facing Agent OS app surface selected as the bounded successor to #1237. It does not replace ChatGPT's hidden/global router. The v1 contract applies when the Agent OS app is explicitly selected or invoked.

```text
ChatGPT + Agent OS app
-> two bounded MCP tools
-> existing Agent OS route/continuation owners
-> existing GitHub connector for any authorized repository write
-> existing GitHub -> GCE transport
-> server-side #1242/#1218 discovery/currentness
-> existing Scheduler/lease owners
```

## MCP tools

`plan_agent_os_continuation_tool(repository, issue_number, canonical_handoff_id=None)` accepts only bounded repository/issue identity plus an optional handoff that must already have been produced by canonical Agent OS evidence. Without a handoff it returns `discover-current-handoff`; with one canonical `executor-handoff:<64hex>` it preserves the identity exactly and returns the existing `/agent-os resume <id>` ingress. It never scans a checkpoint store or invents an identity.

`classify_agent_os_continuation_tool(...)` adapts structured attempt evidence into the existing #1237 `post_selection_continuation` contract. It adds no classification or routing vocabulary. `CAPABILITY_ALTERNATIVE_AVAILABLE` remains automatic same-lineage continuation; ambiguous effects require readback; cross-surface compatibility remains #1201-owned; repeated equivalent recovery remains #1200-owned; red CI, base drift, and stale gates remain with #1251/#1209/#1235.

Both tools are non-authorizing. Their result models cannot grant execution, GitHub writes, merge, closure, external writes, Scheduler admission, or lease acquisition.

`admit_agent_os_failed_repair_tool(...)` gates the next repair mutation on the retry-specific CKR6 activation result plus separated diagnostics. It also accepts three optional keyword-only recovery-progress inputs — `current`, `prior` (`RecoverySemanticEvidence`), and `prior_transition_fingerprint` — which compose the existing `classify_recovery_progress` projection (#2281): an `EQUIVALENT` observation (no semantic progress vs `prior`) makes the mutation inadmissible, and a `RECOVERY_STALLED` observation (the same equivalent transition seen again) additionally sets `agent_os_continuation["stalled"]` to `True` on the non-authorizing host payload. Omitted params behave exactly as before; the params are additive so #3280's later optional params land cleanly.

`admit_agent_os_ready_for_review_tool(...)` projects the Draft -> Ready-for-Review admission (#3279) before any Ready transition. It binds the exact head SHA (`expected_head_sha` vs `observed_head_sha` / `validation_head_sha`) and the PR body revision (`expected_body_revision` vs `observed_body_revision`); stale bindings are refused with named reason codes (`exact-head-drift`, `stale-validation-head`, `stale-body-revision`). Closure-authorization evidence (`repository`, `issue_number`, `authorizer_id`, `decision_id`, `observed_at_revision`) is converted into canonical `IssueClosureAdmission` structs through `evaluate_lifecycle_mutation`, so detected closing targets are compared against digest-bound authorization evidence, never caller-supplied target strings. GitHub-effective closing references in the PR title/body are detected with the single canonical parser consumed by `evaluate_ready_for_review_admission`; targets without canonical close-issue authorization refuse the transition (`unauthorized-closing-reference`), including negated closing prose such as PR #3156's "does **not** close" wording, while `Part of` / `Refs`-only linkage passes. Like the other admission tools it is non-authorizing: the projection grants no merge, closure, workflow, protected-setting, production, or external-write authority.

## Mission completion tools

`classify_agent_os_mission_completion_tool(repository, issue_number, branch_exists, implementation_commit_count, draft_pr_exists, canonical_pr_readback_verified, capable_route_available, subordinate_writes_only, implementation_pr_required=False, ...)` accepts the same ten live-consumer/successor inputs as `classify_agent_os_mission_completion` in the facade: `live_consumer_required`, `live_consumer_requirement_source`, `live_consumer_reachability_proven`, `live_consumer_identity`, `live_consumer_evidence_source`, `live_consumer_evidence_current`, `live_consumer_evidence_kind`, `successor_issue_number`, `successor_current`, `successor_owns_residual_live_acceptance`. All default to `False`/`None`, so repository-only callers that pass only the original nine parameters are unaffected: a mission whose issue contract does not require a live consumer keeps the repository-only completion semantics.

When `live_consumer_required` is true, completion through the tool is refused unless either (a) current source-specific live observation is proven against the exact consumer identity (`required-live-consumer-current-observation-proven`) or (b) a current successor issue provably owns the residual live-acceptance obligation (`residual-live-acceptance-owned-by-current-successor`). Packaging, registration, fixtures, contracts, and unit tests are repository evidence only; they never satisfy the live-consumer requirement.

`classify_agent_os_issue_batch_completion_tool(repository, issue_number, lane_evidence)` reads the same ten keys as optional per-lane fields from each `lane_evidence` entry and forwards them to the single-issue admission gate for PR-required lanes. Per-lane is deliberate: heterogeneous lanes must not homogenize (one lane's live-consumer requirement never blocks or blesses another lane). No-PR lanes never call admission, so per-lane live-consumer keys are naturally a no-op there.

Tool registration is not evidence of live consumption. The fact that these tools are registered on the MCP surface proves only that the contract inputs exist; nothing about registration, packaging, or a passing tool call observes the live host/runtime/connector. A completion claim backed only by tool availability is a false completion.

## Governed mutation seams (#3281)

`admit_agent_os_issue_comment_mutation_tool(phase, issue_number, ...)` exposes the issue-comment write boundary. Phase `pre-write-guard` runs the #2741 verify-open guard (`evaluate_defect_evidence_mutation`) on host-supplied target state: stale state evidence is refused fail-closed for re-acquire; a closed target is refused with the directive `route-to-open-owner` (when an open owner is named) or `create-new-bug`; only a current, verified-open target is admitted. Phase `post-write-readback` runs the #2785 canonical readback (`evaluate_comment_persistence`) over the host's canonical comment list: a subordinate write is `persisted` only when the exact intended body appears in the canonical readback; a provider success claim without readback proof is `not-persisted` and retry-safe; an incomplete or ambiguous readback is `uncertain` and never authorizes an automatic retry, so an uncertain response followed by reconciliation never creates a duplicate comment.

`project_agent_os_lane_post_pr_issue_reconciliation_tool(phase, ...)` exposes the Safe Implementation Lane post-PR step. Phase `plan` runs the #2791 projection (`project_lane_post_pr_issue_reconciliation`) on host-supplied issue/PR readback evidence and projects the issue's expected post-PR disposition using only the existing lifecycle-mutation vocabulary (`remove-lifecycle-label`, `close-issue`); phase `readback-proof` replays the returned plan dict against the canonical post-mutation readback (`evaluate_lane_post_pr_issue_readback`). Draft PR creation is never reported `fully_reconciled` while the linked issue keeps a stale Ready label or an open disposition. The projection can never grant merge or Ready authority (`merge_authorized`/`ready_authorized` are `Literal[False]`).

Both tools are pure admission/readback composition in `governed_mutation_seams_facade.py`. They perform no GitHub writes, authorize none, and introduce no second issue registry, queue, scheduler, or lifecycle authority. Live host consumption is separately authorized; registration and tests alone are not closure evidence.

## Discovery and write boundaries

#1284 remains unchanged: MCP never reads `<checkpoint_store>/invocations/*.json` directly. The app requests the existing server-side discovery operation through the governed GitHub/GCE path. Zero matches remain `not-found`; multiple/corrupt/unavailable evidence remains `needs-decision`; no newest/latest heuristic is added.

The MCP server has no GitHub repository-write credential in this phase. GitHub mutations remain GitHub Service Agent-owned and use the existing connected GitHub surface. The MCP facade does not invoke GitHub, Scheduler, shell, provider, cloud, VM, publication, authorized validation, activation, resume, or replay itself.

## Protocol binding

`agent_os_execution_service.mcp_server` uses the official Python MCP SDK (`mcp>=2.2.0,<2.3`) and registers exactly the two tools above with `MCPServer`. The supported MCP range is owned by `08_Tooling/agent-os-execution-service/pyproject.toml`; this documentation mirrors that canonical package requirement. The repository phase does not start a network listener or choose a deployment transport.

`mcp_facade` imports the #1237 owner from `scripts.agent_os_execution_interface.post_selection_continuation`. That package is already distributed by `workflow-scheduler` (#1426), and this distribution declares `workflow-scheduler>=0.18.0,<0.19.0`, so a clean host installation resolves the continuation owner through the existing single-owner distribution boundary. It is deliberately not re-packaged here: #1300 requires that no runtime module be carried by two distributions.

The SDK supports stdio and Streamable HTTP, but hosting, authentication/principal validation, origin/host policy, TLS/network exposure, ChatGPT Developer Mode/app installation, Secure MCP Tunnel, credentials, and production activation are separate external/configuration decisions and are not authorized by #1966.

## #1233 regression intent

With the Agent OS app explicitly selected:

```text
Work on #1233
-> plan_agent_os_continuation_tool(Blummer92/agent-os, 1233)
-> discover-current-handoff (server-side governed path)
-> canonical handoff, if exactly one/current, is preserved
-> existing governed resume ingress
```

Local `gh` is not an input to the MCP plan and therefore cannot become a global Agent OS availability gate. If local CLI is later explicitly selected for a different operation, its prerequisites remain relevant only to that selected surface.

## #1239 boundary

This facade does not solve or fake the canonical `AuthorizedValidationLifecycleRequest` v1.1 producer path. It does not serialize `SingleIssuePilotInput`, put validation evidence in prompt/comment text, invoke #1929/#1830, create a source capsule, activate #1959, resume, or replay. After the MCP app is externally activated and the #1233 route regression is proven, return to #1237 and then separately reconcile the remaining #1239 source-envelope integration.

## Rollback

Remove `mcp_facade.py`, `mcp_server.py`, their focused tests/docs, and the `mcp` dependency. Existing #1237 policy, #1284 server-side discovery, #1203/#1217 transport, #1218 currentness, GitHub connector, Scheduler state, and all external systems remain unchanged.
