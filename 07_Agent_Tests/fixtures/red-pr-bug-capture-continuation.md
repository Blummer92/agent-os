# Red-PR Bug Capture Is Not Completion — #2635 / #2220

## Live reproduction — 2026-09-18

```text
parent issue: #2595
parent PR: #2630
exact failing head: 452d8c9db2f57f9f0757272849dedd0847eccdfa
progress: current exact-head validation failure diagnosed
progress: distinct documentation-validation selector defect identified
progress: bounded duplicate/owner reconciliation performed
required: persist or link the canonical defect
required: canonical readback of the persisted defect evidence
required: reacquire parent PR/head/checkpoint and current check state
required: complete the strongest still-authorized same-lineage handoff
observed failure: assistant reports diagnosis/handoff progress and returns control to owner
```

## Required classification

```text
red PR
+ exact failure diagnosis
+ subordinate bug capture or handoff evidence
+ unfinished admitted parent action
!= terminal completion
```

A diagnostic explanation, bug issue, issue comment, handoff record, or other subordinate GitHub mutation is intermediate evidence while admitted same-lineage work remains.

## Expected sequence

For an already-authorized red-PR repair mission:

1. inspect current exact-head failure evidence;
2. when a distinct defect is proven, perform only the bounded duplicate/owner check needed to select its canonical owner;
3. persist or link the defect when current policy permits;
4. canonically read back that subordinate mutation;
5. reacquire the parent issue, PR, branch, exact head, checkpoint, and current check state;
6. resume the existing #2220 continuation path from the current failed-repair boundary; and
7. stop only at the strongest still-authorized terminal handoff or one explicit genuine blocker with its clearing condition.

If the parent PR already exists, subordinate bug capture still cannot make the parent mission terminal. The existing mission-completion admission must continue to project a non-terminal same-lineage action until canonical delivery/terminal evidence is independently proven.

## Reuse and stop conditions

Reuse:
- #2220 mission-completion and continuation semantics;
- the existing failed-repair CKR6 re-entry contract;
- the existing red-CI checkpoint/continuation owner;
- canonical GitHub readback and parent-lineage reacquisition.

Do not create another scheduler, queue, retry engine, mission-state model, bug tracker, GitHub writer, or continuation architecture.

Stop safely when current evidence proves an authorization, source-of-truth, scope, ownership, excluded-surface, material-decision, or capability blocker. Missing defect readback or missing parent-lineage reacquisition is a blocker, not completion.

## Non-authority

This fixture grants no merge, issue closure, workflow/protected-setting mutation, credential/IAM, production, external-write, retry, or repository-write authority. It specifies continuation ordering only.
