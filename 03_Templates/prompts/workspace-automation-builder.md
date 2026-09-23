# Workspace Automation Builder Prompt

Use this prompt when asking ChatGPT to design or build a Google Workspace
automation through the Workspace Automation Builder capability workflow. This
capability is not an executable agent.

Repository implementation routes to GitHub Service Agent with applicable
Workspace/language standards. ChatGPT Orchestrator classifies cross-system and
external-operation intent. Live Workspace writes remain separately exact-target
authorization-gated.

Legacy names such as `Google Workspace Automation Engineer`, `Workspace
Automation Developer`, and `Workspace Automation Builder` are compatibility
input only and must resolve through
`04_Registry/legacy-agent-alias-registry.md`.

```md
@GitHub

Repository: Blummer92/agent-os
Branch: main

Task: Build a scoped Google Workspace automation.

Start from:

1. AGENTS.md
2. 00_Governance/ownership-and-source-of-truth.md
3. 00_Governance/write-authorization-policy.md
4. 04_Registry/agent-inheritance-registry.md
5. 04_Registry/responsibility-matrix.md
6. 04_Registry/legacy-agent-alias-registry.md
7. 02_Agent_Overlays/chatgpt-orchestrator.md
8. 02_Agent_Overlays/github-service-agent.md
9. 01_Shared_Standards/google-workspace/workspace-automation-builder.md
10. 01_Shared_Standards/google-workspace/workspace-write-authorization.md
11. any additional shared standards referenced by the selected route

Automation request

[Describe the workflow to automate.]

Route selection

Choose one:

- Patch existing code
- Build a new project
- Debug or optimize
- Evaluate implementation approach
- Plan a separately authorized external Workspace operation

Routing

- Repository patch/build/debug work: GitHub Service Agent plus applicable
  Workspace/language standards.
- Cross-system, source-of-truth, and external-operation routing: ChatGPT
  Orchestrator.
- Independent validation evidence: QA / Test Agent where required.
- Live Workspace writes: separately authorize the exact target and operation
  under workspace-write-authorization.md before execution.

Before building, identify:

1. project goal
2. source of truth
3. safe write location
4. owner or approval path
5. smallest working version
6. exact external operations, if any
7. stop condition

Known targets

- Drive folder/file IDs:
- Sheet IDs and tabs:
- Doc IDs:
- Calendar IDs:
- Gmail labels or queries:
- Apps Script project ID:
- Notion page/database IDs, if involved:

Attached working set

If these files apply, inspect them before implementation:

- OVERVIEW.md
- CHANGE_RULES.md
- SAFETY_RULES.md

Boundaries

- Do not write to live Workspace systems unless the exact target and operation
  are explicitly authorized.
- Do not create triggers, change sharing, or deploy Apps Script without approval.
- Prefer read-only discovery, dry-run design, mocks, and local tests first.
- Preserve source-of-truth and ownership boundaries.
- Do not store secrets in code, docs, samples, memory, Notion, or logs.
- Do not treat a legacy Workspace agent name as current execution ownership or
  write authority.

Required output

1. selected route
2. automation spec
3. target inventory
4. data-flow map
5. read/write operation list
6. implementation plan or local code changes
7. validation plan and tests run
8. deployment approval checklist
9. rollback or disable plan
10. unresolved blockers and remaining risks
```

## Version

0.1.2
