# Live Readiness Checklist

Required only for Tier 2, Tier 3, production, governed-field, external-system,
sharing or permission, source-of-truth, sensitive-data, or irreversible work.

Ordinary Tier 0 read-only and Tier 1 local-only work does not require this checklist.
Use `03_Templates/prompts/agent-intake-form.md` for routing.

## Agent And Loadout

- [ ] Correct agent is named.
- [ ] Correct overlay is named.
- [ ] Required inherited standards and loadout are identified.
- [ ] The task is within the agent's registered responsibility.

## Source Of Truth And Ownership

- [ ] Exact target is identified.
- [ ] System of record is identified.
- [ ] Artifact or field owner is identified.
- [ ] Current source evidence has been read.
- [ ] No competing source of truth is being created.

## Write Surface

- [ ] Risk tier is Tier 2 or Tier 3.
- [ ] Write needed is stated explicitly.
- [ ] Approved write surfaces are listed.
- [ ] Blocked write surfaces are listed.
- [ ] Governed fields are identified.
- [ ] Permissions, sharing, production, sensitive data, and irreversible effects are
      classified.

## Approval And Target Verification

- [ ] Approval source is named and current.
- [ ] Approval covers the exact target and action.
- [ ] Authorization comes from the owner or approved policy, not from capability,
      validation, labels, readiness, or tier classification.
- [ ] Repository writes use the GitHub Service Agent when GitHub is the target.
- [ ] External-system changes have separate explicit approval.

## Evidence And Rollback

- [ ] Required tests or evidence are listed.
- [ ] Exact-head or current-state evidence is required where applicable.
- [ ] Rollback steps are specific and feasible.
- [ ] Partial failure and cleanup behavior are defined.
- [ ] Stop conditions fail closed.

## Reporting And QA

- [ ] Final-report destination is identified.
- [ ] QA evidence or QA handoff is defined.
- [ ] Files or records changed will be listed.
- [ ] Tests run, docs updated, blockers, handoffs, and remaining risks will be reported.
- [ ] Audit evidence preserves exact target, actor, approval, and result when required.

## Final Decision

```yaml
ready_for_write: true | false
human_decision_required: true | false
reason:
approved_target:
approved_write_surface:
rollback_owner:
```

Mark `ready_for_write: false` when ownership, target, source of truth, approval, governed
fields, evidence, rollback, or stop conditions are incomplete or ambiguous.