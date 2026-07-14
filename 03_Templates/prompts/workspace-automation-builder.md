# Workspace Automation Builder Prompt

Use this prompt when asking the Google Workspace Automation Engineer to design or
build a Workspace automation safely.

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
6. 02_Agent_Overlays/google-workspace-automation-engineer.md
7. 01_Shared_Standards/google-workspace/workspace-automation-builder.md
8. any additional shared standards referenced by the overlay

Automation request

[Describe the workflow to automate.]

Route selection

Choose one:

- Patch existing code
- Build a new project
- Debug or optimize
- Evaluate implementation approach

Before building, identify:

1. project goal
2. source of truth
3. safe write location
4. owner or approval path
5. smallest working version
6. stop condition

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

- Do not write to live Workspace systems unless explicitly approved.
- Do not create triggers, change sharing, or deploy Apps Script without approval.
- Prefer read-only discovery, dry-run design, mocks, and local tests first.
- Preserve source-of-truth and ownership boundaries.
- Do not store secrets in code, docs, samples, memory, Notion, or logs.

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

0.1.1
