# Module Version Map

Module versions are governed by `00_Governance/standards-change-control.md`.
Repository releases and module versions are versioned independently, so module
versions change only when the module's standards or contract changes.

| Module | Version |
|---|---|
| Global Engineering | 0.2.0 |
| Read-Only Default | 0.1.0 |
| Source-of-Truth Checks | 0.1.0 |
| Python Standards | 0.1.0 |
| Google Workspace Standards | 0.1.2 |
| Apps Script Standards | 0.1.0 |
| Notion Standards | 0.3.0 |
| QA/Test Standards | 0.1.0 |
| Dashboard Governance | 0.1.0 |
| Dashboard Migration Verification | 0.1.0 |
| Instructional Design Standards | 0.7.0 |
| Agent Orchestrator | 0.1.0 |
| Unit Alignment Agent | 0.3.0 |
| Teacher Modeling Coach | 0.2.0 |
| Instructional Materials Coach | 0.3.0 |
| Student Language Standard | 0.3.0 |
| Workflow Scheduler | 0.9.1 |
| Workspace Automation Builder Tooling | 0.1.1 |
| Agent Memory & Context Budget Manager | 0.1.0 |
| IA4D-to-Scheduler Handoff Contract | 0.2.0 |
| GitHub Issue Lifecycle Standard | 0.1.0 |
| Agent OS Execution Service | 0.4.0 |
| Artifact-First Response Standard | 0.1.0 |
| Teacher Decision Studio Standard | 0.1.0 |
| LP Pacing Handoff Contract | 0.1.0 |
| LP Reason Code Catalog | 0.1.0 |
| LP Notion Working Layer | 0.1.0 |

**Dashboard Migration Verification**
(`08_Tooling/dashboard-migration-verification/`) starts as a verification-only
migration evidence toolkit for dashboard registry examples, placeholder snapshots,
dependency graphs, conservative validation results, and human-readable reports. It
never authorizes live Notion, Workspace, trigger, sharing, source-of-truth, or
production dashboard writes. Standard packaging metadata was completed by D2 (#123).

**Workspace Automation Builder Tooling**
(`08_Tooling/workspace-automation-builder/`) includes an Apps Script safety
bridge, offline test suite, sync safety docs, sanitized sample handoff fixture,
JSON schemas, validation fixtures, and a local-only fixture validator. It does
not authorize live Workspace, Notion, trigger, sharing, or production writes.

**Workflow Scheduler**, **Agent Memory & Context Budget Manager**,
**IA4D-to-Scheduler Handoff Contract**, and **Agent OS Execution Service**
extended descriptions moved to `04_Registry/module-version-map-details.md` to
keep this index under the line-limit. Workflow Scheduler remains `0.9.0`;
Agent OS Execution Service remains `0.4.0`.

**Artifact-First Response Standard**
(`01_Shared_Standards/instructional-design/artifact-first-response-standard.md`,
#821) requires classroom-material responses to lead with the requested
artifact, preview, or content specification before backend routing and
governance reporting, while preserving all existing gate, ownership, and
stop-condition behavior.

**Teacher Decision Studio Standard**
(`01_Shared_Standards/instructional-design/teacher-decision-studio-standard.md`
plus `teacher-decision-studio-previews-standard.md`, #823/#824) defines a
table-first rubric/assessment consultation protocol -- comparison table,
format catalog, explanation-risk analysis, and per-option in-chat and PDF
worksheet previews -- that recommends without auto-approving and never writes
a governed field without explicit teacher confirmation.

**LP Pacing Handoff Contract**
(`01_Shared_Standards/instructional-design/lp-pacing-handoff-contract.md`,
`01_Shared_Standards/instructional-design/lp-pacing-handoff-adaptation.md`, `01_Shared_Standards/instructional-design/lp-pacing-handoff-cases.md`, and
`04_Registry/lp-pacing-handoff-contract.yaml`, #648) defines the provider-neutral
pacing handoff packet, owner-state independence, the six-dimension diagnosis, and
the ordered adaptation hierarchy. It authorizes no runtime evaluator, OCR,
classroom data, external write, or gate advancement.

<<<<<<< HEAD
**Agent OS Execution Service** (`08_Tooling/agent-os-execution-service/`) moved `0.3.0` -> `0.4.0` under PILOT-VALIDATION (#723): `command_planning.py` allowlists one additional exact command and adds one explicit exact-type pre-PR branch that binds the immutable `PrePrValidationSubject` and additive `PrePrValidationPlan` from `scripts/agent_os_remote_validation/models.py` to an `ExecutionServiceRequest` for validation-only candidate #726, without fabricating a pull request. Positive-PR validation-plan and command-plan payloads and identities are unchanged, and `COMMAND_REGISTRY_VERSION` stays `1.0` because allowlisting a command is additive. Planning stays pure-local and non-authorizing: `execution_authorized`, `merge_authorized`, and `side_effects_performed` remain false, the 30-second per-command and 300-second total validation ceilings are enforced, #726 was not executed, and Scheduler concurrency remains `0`. Workflow Scheduler remains `0.9.1`.

**Agent OS Execution Service** moved `0.2.0` -> `0.3.0` under WSC6B4 (#697): `execution_composition.py` adds `compose_and_run_validation(...)`, a thin, non-authorizing boundary that revalidates request/plan/authorization/runtime identity and delegates exactly once to the canonical Workflow Scheduler validation-only entrypoint, retaining the exact `FrozenTestValidationResult`. No second runtime, command loop, or duplicate evidence model was added; `merge_authorized` stays false; execution authorization, validation, review, and merge authorization remain separate states. Workflow Scheduler remains `0.9.1`.
=======
**LP Reason Code Catalog**
(`01_Shared_Standards/instructional-design/lp-reason-code-catalog.md` and
`04_Registry/lp-reason-code-catalog.yaml`, #711) holds the finite `lp-*` semantic
reason catalog and its producer/consumer ownership map. Generic parsing, bounds,
version, serialization, and authority mechanics stay with LP9, LP12, and CW5A.

**LP Notion Working Layer**
(`01_Shared_Standards/notion/lp-notion-working-layer-standard.md` and
`04_Registry/lp-notion-working-layer-change-request.yaml`, #652) defines the
bounded Notion working-layer design and the exact-target Change Request. The
Change Request is recorded as proposed and not authorized; six unresolved
decisions block any live change.
>>>>>>> origin/main

## Reconciliation Notes

A3 reviewed this map against visible repository evidence only. Any runtime status
not directly supported by files or validation evidence remains intentionally
unstated rather than inferred.
