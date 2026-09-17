# Issue-start Lessons Learned preflight

Issue: #2247. Availability projection clarification: #2331.

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

## Lessons Learned route status (#2331)

The MCP boundary also projects the composition state of the existing canonical reader. This projection is diagnostic evidence and does not change CKR6 admission semantics:

- `lesson_read_route_status=configured-canonical-reader` means the current process has the non-secret source identity required to construct the existing CKR11 -> `NotionReadOnlyAdapter` reader.
- `lesson_read_route_status=current-surface-unbound` with `lesson_read_route_reason_code=connector-surface-unavailable` means only that the current execution surface lacks that binding. It **does not** prove that the canonical Lessons Learned corpus is unavailable.
- `canonical_lessons_source_unavailable` remains `false` at this composition boundary. Source/provider unavailability can be established only by an attempted canonical read and is handled by the existing CKR6 capability/disposition contracts, including #2142; a missing local binding cannot manufacture that conclusion.
- explicit `lesson_rows` remain a test/diagnostic override and are projected as `diagnostic-override`; they are not a production source or alternate reader.

The canonical reader remains `build_lesson_read_executor()` / `resolve_lesson_read_route()` in `lesson_reader_composition.py`. It uses only the existing read-only Scheduler Notion adapter. This clarification adds no second reader, selector, Notion client, source, workflow, credential path, or authority model.

A disabled, missing, or unsupported native/direct ChatGPT Notion plugin is likewise execution-surface evidence only. The ChatGPT Orchestrator must resolve `@notion-lessons-learned` and the current governed route before describing the canonical source as unavailable. Host exposure of the Agent OS MCP namespace remains the separate #2528 integration boundary.

## Authority

GitHub remains authoritative for governance, issue state, code, tests, authorization, and exact-head validation. Lessons Learned remain advisory-only.

## Retry boundary

This initial gate does not replace failed-repair re-entry. After a failed repair, use the existing `activate_agent_os_failed_repair_tool` and `failed-repair-lesson-reentry.md` contract before another materially different repair hypothesis or mutation. The failed-repair MCP boundary projects the same reader-route evidence without changing retry admission semantics.

## Host integration requirement

A ChatGPT/runtime host that claims Agent OS issue-start conformance must call the issue-start tool before crossing the first-substantial-hypothesis boundary and must honor `substantial_hypothesis_admissible=false`. Repository conformance cannot force an external host to invoke the tool; host-side enforcement remains an integration requirement.
