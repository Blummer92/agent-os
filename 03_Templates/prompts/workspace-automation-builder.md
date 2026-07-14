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

Known targets

- Drive folder/file IDs:
- Sheet IDs and tabs:
- Doc IDs:
- Calendar IDs:
- Gmail labels or queries:
- Apps Script project ID:
- Notion page/database IDs, if involved:

Boundaries

- Do not write to live Workspace systems unless explicitly approved.
- Do not create triggers, change sharing, or deploy Apps Script without approval.
- Prefer read-only discovery, dry-run design, mocks, and local tests first.
- Preserve source-of-truth and ownership boundaries.

Required output

1. automation spec
2. target inventory
3. data-flow map
4. read/write operation list
5. implementation plan or local code changes
6. validation plan and tests run
7. deployment approval checklist
8. rollback or disable plan
9. unresolved blockers
10. remaining risks
```

## Version

0.1.0
