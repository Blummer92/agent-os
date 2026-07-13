# Agent Memory & Context Budget Manager

## Purpose
Reduce agent compute by selecting only the context needed. Agents waste compute re-reading unchanged files and scanning full repos. Memory Manager helps agents operate within file budgets, reuse cached summaries, and prevent unnecessary scans.

## Relationship to Workflow Scheduler
**Workflow Scheduler** owns: execution order, retries, approvals, batching, parallel dispatch, audit trails.
**Memory Manager** owns: context selection, file budgets, summary caching, stale-context detection.
Scheduler calls Memory Manager pre-task to generate a context packet. Memory Manager does not execute workflows.

## Core Responsibilities
- Task context planning: determine what context is needed
- Relevant file selection: identify files by relevance to task
- Memory summary retrieval: pull cached summaries instead of re-reading
- Stale-context detection: flag outdated summaries after file changes
- Context budget enforcement: reject excessive file/search requests
- Stop/continue recommendations: signal when working set is unclear or scope grows

## Memory Types
- **Project memory**: stable architecture, conventions, rules
- **Phase memory**: goals, completed milestones
- **PR memory**: branch, PR number, changed files, validation state
- **File memory**: summaries; last-read timestamp
- **Test memory**: test coverage; pass/fail state
- **Decision memory**: approved choices, rejected alternatives
- **Risk memory**: known hazards, blockers, unsupported features

## Context Budget Rules
- **Small task** (3–7 files max): typo fix, single-line change, simple rename
- **Medium task** (8–15 files max): feature in one module, component refactor
- **Large task**: explicit planning required before scanning
- Full-repo search only after targeted grep/glob searches fail
- Full test suite only for final validation or broad behavior changes
- No connector retries after auth/approval failure without explicit user approval

## Agent Handoff Packet
Compact YAML format agents receive before work:
```yaml
objective: <task goal>
phase: <current phase>
branch: <git branch>
changed_files: [list of git-changed paths]
allowed_inspect_first: [files to read first]
forbidden_unless_needed: [files to avoid]
known_facts: [prior validated findings]
acceptance_criteria: [pass/fail conditions]
validation_commands: [CLI commands to verify]
compute_limits: {max_files, max_searches, max_tests}
stop_conditions: [rules that halt execution]
```

## Compute-Saving Policies
- Prefer cached summaries over re-reading stable files
- Prefer targeted grep/glob over full-repo search
- Prefer targeted tests over full test suite
- Avoid generated/cache files (.git/, __pycache__/, node_modules/)
- Don't re-read unchanged files after validation
- Don't retry blocked tools; escalate instead
- Don't subscribe to PR activity unless explicitly needed
- Ask for clarification if working set is undefined

## Future Scheduler Integration
- Pre-task context packet generation (Memory Manager generates before Executor runs)
- Per-task file allowlist and budget enforcement
- Per-task test recommendations based on changed modules
- Audit log entries for context used (files read, searches, tests run)
- Memory cache invalidation after file changes (git diff triggers re-summary)
- Approval gate when agent requests exceeds budget

## Stop Conditions
Recommend stopping when: budget exceeded, expensive tools called repeatedly, scope grows beyond phase, required context missing, auth failure, tests fail with no new evidence, unrelated cleanup proposed.

## Non-Goals
❌ No autonomous writes | ❌ No vector DB | ❌ No embeddings | ❌ No daemon | ❌ No REST API | ❌ No dashboard | ❌ Does not replace Scheduler or Orchestrator

## Roadmap
| Phase | Scope | Dependencies |
|---|---|---|
| **Memory 0A** | Design doc | None |
| **Memory 0B** | Handoff packet template | 0A approval |
| **Memory 0C** | Budget policies & examples | 0A approval |
| **Memory 0D** | Summary cache format | 0B approval |
| **Memory 0E** | Scheduler integration design | 0D approval |
| **Memory 1A** | Minimal local implementation | 0E approval |
| **Memory 1B** | Audit/logging integration | 1A complete |
| **Memory 1C** | Stale-context detection | 1B complete |
| **Memory 2+** | Prod integration, vector DB | All 1A–1C complete |
