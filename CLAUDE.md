# Agent OS — Claude Code Entry Point

@AGENTS.md

## Purpose

This file is Claude Code startup and execution guidance for Agent OS.
It is an execution map, not an independent policy source.

GitHub `main` is the canonical source of truth for Agent OS governance,
standards, overlays, registries, templates, tests, tooling contracts, and
release notes. When this file conflicts with a canonical repository source,
follow the canonical source.

Fresh repository evidence overrides stale conversations, saved SHAs, branch
metadata, memory, historical pull-request text, and summaries in this file.
Do not infer current authority or state from old evidence.

## Start Here

1. Start with the imported `AGENTS.md`.
2. Use `04_Registry/navigation-alias-registry.md` before manually searching for
   common Agent OS documentation paths.
3. Resolve the responsible owner through
   `04_Registry/agent-inheritance-registry.md` and
   `04_Registry/responsibility-matrix.md`.
4. Resolve legacy names through `04_Registry/legacy-agent-alias-registry.md`;
   do not invent executable agents for subject domains.
5. Read the selected file in `02_Agent_Overlays/` and only the shared standards
   that overlay references and the task actually requires.
6. Confirm source of truth, write authorization, bounded scope, stop conditions,
   and excluded surfaces before a write.

Do not copy dynamic agent, owner, alias, version, workflow, branch, or status
inventories into this file. Read their canonical registries or standards live.

## Operating Mode And Precedence

`00_Governance/agent-os-advisory-mode.md` remains the low-risk pilot guidance
for read-only, local-only, planning, drafting, QA notes, summaries, code review,
local specs, and similar low-risk work.

More specific current contracts take precedence for work they govern. In
particular, eligible explicitly authorized repository implementation follows
`01_Shared_Standards/github/safe-implementation-lane.md`, while excluded
surfaces remain governed by
`01_Shared_Standards/github/excluded-surface-baseline.md` and the applicable
write-authorization rules.

Never use Advisory Mode to bypass a more specific authorization, ownership,
validation, governed-field, production, external-write, or irreversible-action
boundary.

## GitHub Repository Work

GitHub repository writes belong to the GitHub Service Agent. Read
`02_Agent_Overlays/github-service-agent.md` for its current scope and stop
conditions.

For eligible Safe Implementation Lane work:

- reuse one existing valid issue-linked branch, Draft PR, or checkpoint lineage
  when one exists instead of creating a competing lineage;
- reacquire current repository, issue, authorization, ownership, branch, PR,
  checkpoint, and exact-head evidence before acting;
- treat saved SHAs as checkpoint evidence only, never as proof of current head;
- preserve the Scheduler lease as concurrency authority and do not create a
  competing execution when an active or ambiguous lease exists;
- distinguish same-branch head advancement from base-branch drift;
- route a behind PR through the governed branch-refresh path instead of treating
  it as ordinary head advancement;
- continue registered-owner transitions internally while authorization, source
  of truth, and bounded scope remain valid;
- remember that `continue`, `next step`, or similar conversation continuity
  never authorizes an excluded surface.

Merge, auto-merge, issue closure, protected settings, workflows, credentials,
IAM, production, external-system writes, governed-field mutation, source-of-
truth changes, and other excluded surfaces require their own governing
authorization.

## Execution Surface And Automation

Do not assume the active Claude Code environment has local Git, `gh`, process
execution, dependencies, network access, or the runtime capabilities required
for a task.

For current execution routing, use the contracts referenced by
`02_Agent_Overlays/chatgpt-orchestrator.md`. Classify the exact next action
against current execution-surface capability evidence and reroute when the
selected surface cannot perform it.

A missing CLI or runtime capability is capability-mismatch evidence, not by
itself evidence that the issue or repository is defective. A route change does
not widen authority. If no capable authorized route exists, stop with the
current governed decision state rather than inventing a fallback.

Treat repository automation as implemented only when current `main` provides the
corresponding code or governing contract. Issues, roadmap text, experiments,
and historical discussions do not make a proposed Notion coding engine, GCE
transport, provider path, multi-issue behavior, or other planned capability
active.

## Validation And Evidence

Use `01_Shared_Standards/global-engineering/testing-and-release.md` for the
current validation contract and `scripts/README.md` plus repository-local docs
for executable tooling discovery.

- Run the smallest relevant focused checks after a change.
- Issue-required developer-loop checks are pre-PR gates and must run on a capable
  authorized surface before Draft PR creation.
- Focused validation is non-final evidence.
- Ready-for-Review requires the required aggregate validation bound to the exact
  final pull-request head when the governing workflow requires it.
- Never reuse validation evidence from another SHA.
- Treat stale, queued, cancelled, superseded, failed, or terminal evidence using
  the current owning contract rather than guessing from labels or prose.

For the repository's current local aggregate and CI/Cloud Build relationships,
read current `README.md` and the owning validation documentation. Do not freeze a
CI provider, workflow name, or project-side trigger into this startup file.

The current Markdown structural rule remains owned by
`07_Agent_Tests/validate-repo-structure.sh` and its governance documentation.
Do not change that rule based on this entrypoint.

## Destination Routing

Use the current destination rules from `AGENTS.md` and the selected overlay:

- Agent OS governance, code, standards, overlays, registry files, templates,
  tests, and release notes default to GitHub.
- Teacher planning, readiness status, lesson candidates, and working knowledge
  default to Notion or an approved Notion handoff.
- Student-facing Slides, Docs, worksheets, and generated classroom materials
  default to approved Google Drive workflows and folders.
- GitHub storage for classroom artifacts requires the existing explicit approval
  and GitHub Change Request path.

External-system writes remain subject to
`00_Governance/write-authorization-policy.md`. Do not infer permission to mutate
Notion governed fields, Drive sharing, production data, or source-of-truth
records from ordinary task authorization.

## Reporting And Handoffs

Use `01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`
for current response ordering, progress evidence, and report fields.

For implementation or review work, preserve at least:

- files changed;
- tests run;
- docs updated;
- unresolved blockers;
- handoff recommendations;
- remaining risks.

Report actual branch, exact-head evidence, rollback, authorization boundaries,
and excluded-surface confirmation when the governing GitHub workflow requires
them. Do not turn a recommendation, plan, or stale checkpoint into a claim that
execution occurred.

## Claude Code Maintenance Rule

Keep this file concise and stable. It should answer:

> What do I need to read, what evidence must I reacquire, and what am I allowed
> to do next?

Prefer literal backticked repository paths for detailed canonical references.
Do not add broad `@` imports beyond `@AGENTS.md` unless a future governed change
proves the extra startup context is necessary.

Do not embed transient branches, SHAs, current PR numbers, dynamic agent lists,
roadmap state, provider status, or copied policy text here. Update the canonical
owner instead and keep this file as the smallest reliable Claude-specific map.