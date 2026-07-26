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
- Context budget declarations: identify bounded file and test expectations
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
current_phase: <current phase>
branch: null
pr_number: null
changed_files: []
allowed_inspect_first: []
forbidden_unless_needed: []
known_facts: []
prior_decisions: []
acceptance_criteria: []
validation_commands: []
compute_limits:
  max_files_to_inspect: 8
  targeted_tests_only: true
  no_full_scheduler_suite: true
stop_conditions: []
```

`branch: null` means no branch exists. `pr_number: null` means no pull request exists. Non-null branches must be non-empty strings. Non-null PR numbers must be non-negative integers. `0` remains accepted only for legacy compatibility; new pre-PR packets use `null`.

Compute limits are declarations and stop obligations. This issue does not add runtime counters or enforcement.

## Compute-Saving Policies
- Prefer cached summaries over re-reading stable files
- Prefer targeted grep/glob over full-repo search
- Prefer targeted tests over full test suite
- Avoid generated/cache files (.git/, __pycache__/, node_modules/)
- Don't re-read unchanged files after validation
- Don't retry blocked tools; escalate instead
- Don't subscribe to PR activity unless explicitly needed
- Ask for clarification if working set is undefined

## Memory H2 — Safety-Complete Summary Rendering
- `packet_summary.summarize_handoff_packet(packet, evidence=...)` renders every canonical field in fixed order (objective, phase, branch, PR number, changed files, allowed-inspect-first, forbidden-unless-needed, known facts, prior decisions, acceptance criteria, validation commands, compute limits, stop conditions), reusing #265's validator as sole authority.
- `branch=None`/`pr_number=None` render truthfully; truncation is bounded and reports the omitted count; safety-critical sections stay visible when empty.
- **Rendering evidence**: `RenderingEvidence` (producer, packet schema version, renderer version, provenance status, source fingerprint) is caller-supplied only — never derived from the clock, Git, the filesystem, network, or environment/process state. `RenderedHandoffSummary` carries rendered text, source/summary fingerprints, and a trust classification.
- **Trust states** (`packet_summary.TRUST_*`): `current` (complete matching supported evidence), `stale` (fingerprint proves the packet changed), `unsupported` (unrecognized schema/renderer version), `unverifiable` (evidence missing, malformed, contradictory, detached, or unrecognized). `current` requires every field valid, `provenance_status="supplied"`, a supported version, and a matching fingerprint; anything short fails closed. Trust reasons are a bounded, stable code vocabulary, never raw exception text or object representations.
- **Fingerprints**: SHA-256 over canonical UTF-8 JSON (packet) or UTF-8 text (rendered sections); bind every safety-relevant field; exclude clocks, randomness, process identity, environment, absolute paths, Git, and network data; are equality checks, not cryptographic signatures.
- Every rendering ends with a fixed non-authorization notice (context evidence only; not implementation/execution/merge authorization; not proof the packet is current unless trust status is `current`).
- The renderer stays pure-local, deterministic, side-effect free, with no cache, Scheduler, network, or GitHub-write behavior. Memory H3 may later build cache-key v2 / namespace / lookup / writer behavior on this contract; none is implemented here.

## Future Scheduler Integration
Pre-task context packet generation; per-task file allowlist and budget declarations; per-task test recommendations based on changed modules; audit log entries for context used; memory cache invalidation after file changes; approval gate when requested work exceeds the declared budget.

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
