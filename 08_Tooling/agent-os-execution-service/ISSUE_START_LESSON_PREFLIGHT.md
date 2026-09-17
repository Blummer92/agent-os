# Issue-start Lessons Learned preflight

Issue: #2247

## Purpose

The execution service exposes `activate_agent_os_issue_start_lessons_tool` as the machine-consumable ChatGPT boundary for the existing CKR6/CKR11 Lessons Learned preflight before the first substantial Agent OS investigation, implementation, or repair hypothesis.

The tool does not create a second selector or Notion reader. It builds the existing `CodingKnowledgeRequest`, delegates bounded retrieval to `orchestrate_lesson_retrieval(...)`, and returns the existing CKR6 selection/handoff projection.

## Admission signal

`substantial_hypothesis_admissible=true` only when the CKR6 result is one of:

- `not-needed`;
- `sufficient`;
- `unavailable-safe-fallback`.

`insufficient` and `manual-review` keep the first substantial hypothesis blocked. `not-needed` performs zero Notion reads.

This signal controls execution order only. It grants no repository write, execution, merge, issue-closure, workflow/protected-setting, credential, production, or external-write authority.

## Authority

GitHub remains authoritative for governance, issue state, code, tests, authorization, and exact-head validation. Lessons Learned remain advisory-only.

## Retry boundary

This initial gate does not replace failed-repair re-entry. After a failed repair, use the existing `activate_agent_os_failed_repair_tool` and `failed-repair-lesson-reentry.md` contract before another materially different repair hypothesis or mutation.

## Host integration requirement

A ChatGPT/runtime host that claims Agent OS issue-start conformance must call the issue-start tool before crossing the first-substantial-hypothesis boundary and must honor `substantial_hypothesis_admissible=false`. Repository conformance cannot force an external host to invoke the tool; host-side enforcement remains an integration requirement.

### Installed stdio launch target (#2528)

The `agent-os-execution-service` distribution installs `agent-os-mcp`, which launches the existing bounded `agent_os_execution_service.mcp_server` over MCP stdio transport. This gives an authorized MCP-capable host a stable executable target to attach without importing repository internals or inventing a second server/tool registry.

The launch target does **not** register additional tools, select a host, edit ChatGPT/plugin configuration, deploy a service, expose a network listener, or grant credentials, workflow/protected-setting, production, repository-write, merge, closure, or external-write authority. Host attachment and product/connector exposure remain separately governed. A live ChatGPT surface that does not attach this executable can therefore remain non-conformant even when repository packaging tests pass.
