# Agent Memory & Context Budget Manager

## Purpose
Reduce agent compute by selecting only the context needed. Agents waste compute re-reading unchanged files and scanning full repos. Memory Manager helps agents operate within file budgets, reuse cached summaries, and prevent unnecessary scans.

## Relationship to Workflow Scheduler
**Workflow Scheduler** owns: execution order, retries, approvals, batching, parallel dispatch, audit trails.
**Memory Manager** owns: context selection, file budgets, summary caching, stale-context detection.
Scheduler calls Memory Manager pre-task to generate a context packet. Memory Manager does not execute workflows.

## Core Responsibilities
Task context planning (what context is needed); relevant file selection by task relevance; memory summary retrieval instead of re-reading; stale-context detection after file changes; context budget declarations for bounded file and test expectations; stop/continue recommendations when the working set is unclear or scope grows.

## Memory Types
**Project** (stable architecture, conventions, rules); **phase** (goals, completed milestones); **PR** (branch, PR number, changed files, validation state); **file** (summaries, last-read timestamp); **test** (coverage, pass/fail state); **decision** (approved choices, rejected alternatives); **risk** (known hazards, blockers, unsupported features).

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
Prefer cached summaries over re-reading stable files, targeted grep/glob over full-repo search, and targeted tests over the full suite. Avoid generated/cache files (`.git/`, `__pycache__/`, `node_modules/`). Don't re-read unchanged files after validation, don't retry blocked tools (escalate instead), and don't subscribe to PR activity unless explicitly needed. Ask for clarification if the working set is undefined.

## Memory H2 — Safety-Complete Summary Rendering
- `packet_summary.summarize_handoff_packet(packet, evidence=...)` renders every canonical field in fixed order, reuses #265's validator as sole packet-validity authority, preserves truthful nullable branch/PR values, reports truncation, and keeps safety-critical sections visible. Validator defects propagate for inert exact-built-in packets; only validation surfaces that may invoke caller-defined behavior use the fail-closed containment boundary.
- Displayed output and renderer processing are separately bounded: display strings use 256 characters and displayed collections use 25 entries; processing rejects per-list counts above 500, total list entries above 2,000, per-dictionary counts above 300, total dictionary entries above 1,500, per-string lengths above 10,000 characters, total string content above 50,000 UTF-8 bytes, canonical traversal above 5,000 nodes or depth 20, integers above 1,024 bits, canonical or fingerprint buffers above 100,000 bytes, or total-call traversal above 10,000 nodes. Surrogate code points are escaped in the single-pass display path so every returned summary is strict UTF-8 encodable.
- `RenderingEvidence` is supplied only by the caller. `current` requires inert, supported, complete evidence plus a matching SHA-256 source fingerprint; `stale`, `unsupported`, and `unverifiable` cover mismatch, unsupported identity, or missing/malformed/unsafe evidence. H2 does not independently verify provenance, so fabricated matching evidence remains possible.
- Within those processing limits, the source fingerprint binds the complete packet through canonical type-tagged UTF-8 data and the summary fingerprint binds the complete rendered contract through bounded incremental type-tagged framing. The summary digest checks every encoded chunk before hashing it and never constructs one oversized JSON serialization first. A structurally valid packet exceeding a renderer limit receives a deterministic `unverifiable` resource result and no trusted source fingerprint; renderer limits do not redefine #265 packet validity. Fingerprints are deterministic equality checks, not signatures or authorization.
- Every summary states that it is context evidence only and does not authorize implementation, execution, readiness/status changes, external writes, governed-field changes, merge, deployment, or production action; it is not a substitute for the canonical GitHub issue, approval record, or repository state.
- The renderer stays pure-local, deterministic, side-effect free, with no cache, Scheduler, network, filesystem-write, or GitHub-write behavior. Memory H3 may later consume this contract for cache-key v2 and related behavior; none is implemented here.

## Memory H3 — Cache Contract v2 and Cutover
- **Cache-key v2.** `build_handoff_packet_cache_key_v2(packet)` returns `handoff-summary-v2:2.0:<64 hex>`. The digest binds the cache-key, cache-entry, and namespace versions, the supported packet-schema and renderer versions, the H2 source-fingerprint algorithm version, and the complete H2 source fingerprint. Because that fingerprint is produced by the merged H2 renderer, every canonical packet field binds cache identity -- including `forbidden_unless_needed` and `acceptance_criteria`, which the v1 key omits -- and `branch: null` / `pr_number: null` stay distinct from strings, integers, and legacy sentinels. `handoff_packet_source_fingerprint(packet)` exposes the same fingerprint so callers can build matching evidence. Limitations: a packet that H2 reports as unsafe or over its resource limits gets no v2 identity, and mapping key order does not change identity.
- **Cache-entry v2.** One strict schema with exactly these fields: `cache_entry_version`, `cache_key`, `cache_key_version`, `cache_namespace_version`, `packet_schema_version`, `producer`, `provenance_status`, `renderer_version`, `source_fingerprint`, `source_packet`, `summary`, `summary_fingerprint`, `trust_status`. The v1 optional `metadata` contract is deliberately **not** carried forward, so no field can influence identity or trust. One shared bounded validator serves build, write, and lookup.
- **Strict bounded JSON.** Reading opens the exact expected path once, reads at most `MAX_CACHE_ENTRY_BYTES + 1` (512 KiB), rejects over-limit files before parsing, decodes strict UTF-8, rejects duplicate object names, `NaN`/`Infinity`/`-Infinity`, and floats, requires an exact built-in `dict` at the top level, allows only exact built-in JSON types, and enforces depth 8, 20,000 nodes, 1,000 entries per collection, 40,000 characters per string, and 400,000 total string bytes.
- **Atomic publication.** The final path is never written directly. The writer serializes bounded deterministic bytes, creates a securely named temporary file inside the v2 namespace, writes, flushes, closes, then publishes with same-filesystem `os.replace()`, removing the temporary file after failure where safely possible. Any failure before replacement preserves the previously published entry. Mapping key order is preserved rather than sorted, because the canonical renderer displays compute limits in insertion order.
- **Namespace and paths.** All v2 entries live under the fixed `v2/` child of the caller-supplied cache root, and the filename comes only from the validated fixed-format digest -- never arbitrary caller text. Absolute paths, `..`, slash and backslash variants, drive-letter and UNC forms, null characters, reserved platform names, and trailing dot/space forms are structurally excluded, and the lexical path is confirmed to stay inside the namespace. A symlink at the namespace or destination is rejected where portable checks allow. The cache root is assumed to be owned and controlled by the caller; a privileged adversary concurrently replacing trusted ancestor directories is outside this portable local-cache threat model.
- **Canonical writer eligibility.** `write_summary_cache_v2(cache_root, packet, evidence=...)` calls `summarize_handoff_packet(...)` itself. It accepts no summary text and no externally assembled `RenderedHandoffSummary`. Only a complete, supported, matching H2 result whose trust status is exactly `current` is published; `stale`, `unsupported`, and `unverifiable` fail closed and create no entry.
- **Fail-closed lookup and rejection.** `lookup_summary_cache_v2(...)` performs one bounded open/read (no `exists()`-then-read race), then verifies every version, key, packet, renderer, source, summary, provenance, trust, and rendered-text binding by re-rendering the stored packet through the canonical H2 public renderer. Any inconsistency is a miss, never a partially trusted hit. Misses use one finite non-sensitive vocabulary -- `not_found`, `malformed_or_oversized`, `unsupported_version`, `identity_mismatch`, `trust_not_current`, `unsafe_path_or_entry`, `local_io_unavailable` -- and never expose decoder text, exception text, paths, temporary filenames, object representations, caller data, or partial entry content. `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` propagate.
- **No v1 fallback.** v2 never reads v1 keys, v1 entry schemas, unversioned files, or the old root namespace, never scans the directory, and never searches alternative filenames. Old v1 files are **left completely untouched**: v2 neither migrates, rewrites, reinterprets, nor deletes them, and the v1 helpers remain available and unchanged. Because the two contracts use separate namespaces, cutover and rollback are manual and non-destructive: adopt v2 by calling the v2 functions, and roll back by reverting to the v1 calls. Stale `v2/` files left behind are ignored by v1 code and may be deleted by the operator when convenient. Treat any pre-existing root-level `*.json` cache file as a v1-era marker; there is no automatic migration.
- **Boundaries.** v2 is pure-local and deterministic: no clock, Git, GitHub, environment, network, subprocess, or Scheduler input, and no dependency was added. Fingerprints are integrity and equality evidence only -- never signatures, approval, authorization, or proof of writer identity. A process with write access to the trusted cache root can fabricate an internally consistent entry, so a cache hit is context evidence only and authorizes nothing. The Scheduler boundary is unchanged: nothing here is wired into Scheduler execution.

## CKR2 — Coding Knowledge Selection
`coding_knowledge_selection.select_coding_knowledge(...)` is a pure-local, provider-neutral selector for already-normalized coding working-knowledge candidates. The caller supplies bounded task/repository signals and decides whether specialized knowledge is needed before retrieval. CKR2 performs no GitHub, Notion, filesystem, network, Scheduler, model, or provider access.
Selection is deterministic: exact library match outranks ecosystem/language plus capability, which outranks exact path/keyword evidence; stable knowledge identity breaks ties. Ordinary input is capped at five candidates and at most three retained records. Currentness is finite (`current`, `stale`, `unverifiable`), and stale, unverifiable, duplicate-identity-conflicting, or authority-conflicting evidence fails closed to `manual-review`.

The result exposes finite sufficiency (`not-needed`, `sufficient`, `insufficient`, `manual-review`) and caller-owned retrieval escalation (`none`, `known-reference`, `filtered-data-source-query`, `exact-narrow-lookup`, `workspace-search`, `manual-review`). `not-needed` requires no knowledge preload. Canonical GitHub references remain authoritative; CKR2 creates no authority and performs no writes or side effects.

**Request/task authority vs. candidate-owned provenance (#1520).** `request.canonical_rule_refs` is caller-owned task-authority / inspect-first evidence. Every retained selected `CodingKnowledgeCandidate` must separately carry its own non-empty `canonical_github_refs` before `sufficient` can be returned; `sufficient` never follows from request-owned refs alone, and one retained candidate's refs never satisfy another retained candidate's missing provenance. `select_coding_knowledge(...)` returns `insufficient` with reason `canonical-reference-missing` whenever any retained candidate lacks its own reference, regardless of request-owned evidence. The `canonical_github_refs` field on the result remains the union of request and candidate references for inspect-first display; it is not the sufficiency signal.

`CodingKnowledgeSelectionResult.to_handoff_projection()` maps only into existing Memory Manager concepts: `known_facts`, `prior_decisions`, `allowed_inspect_first`, and `stop_conditions`. It does not create or modify the canonical handoff-packet schema. Benchmark counters are available through the result (`candidate_count`, `selected_count`, knowledge/canonical refs, sufficiency, and recommended escalation) for #1146; unit tests do not establish compute savings.

## CKR10 — Decision / ADR Retrieval Preflight
`decision_preflight.plan_decision_preflight(...)` and `consume_decision_preflight(...)` extend the existing CKR2/CKR6 preflight pattern to already-read Decision Log / ADR evidence. Decision-sensitive tasks use bounded retrieval; routine mechanical work returns `not-needed` with zero Decision Log lookup. The adapter accepts at most five records and CKR2 retains at most three.

Accepted/current decisions may become secondary-index context only when canonical GitHub provenance is present. Proposed/working decisions remain unresolved; superseded/deprecated decisions cannot become active guidance and may only route to a known successor. Stale, unverifiable, authority-conflicting, duplicate-conflicting, or oversized evidence fails closed. Retrieval outage degrades to GitHub-only safe fallback when specialized prior-decision knowledge is not required, otherwise to explicit insufficiency/manual review.

CKR10 inherits the shared CKR2 candidate-provenance invariant (#1520) without an adapter-local duplicate guard: a Decision record without its own `canonical_github_refs` cannot reach `sufficient` merely because `request.canonical_rule_refs` is non-empty. `DecisionPreflightResult.verification_required` reflects candidate-backed provenance only -- it is derived from the selected Decision candidates' own references, never set from request-only refs.

Selected decision identities project into the existing `prior_decisions` field, canonical GitHub references into `allowed_inspect_first`, and no new packet, selector, Memory Manager, connector, database, RAG/vector system, persistence path, Scheduler behavior, or agent is introduced. `source_authority` is always `secondary-index`; GitHub remains authoritative before reliance. See `CKR10_DECISION_PREFLIGHT.md` for the full contract and #1146 benchmark handoff scenarios.

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
