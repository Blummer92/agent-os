# Agent Intake Form

Use `04_Registry/agent-risk-tiers.md` to classify the task. Classification does not
grant authorization. `00_Governance/write-authorization-policy.md` remains authoritative.

## Route

- Tier 0 or Tier 1 that remains read-only or local-only: use Lightweight Intake.
- Tier 2, Tier 3, governed-field, source-of-truth, permission, sharing, production,
  external-write, sensitive-data, or irreversible work: use Full Intake and the
  Live Readiness Checklist.
- Ambiguous scope or write authority: stop for human decision.

## Lightweight Intake — Tier 0 or Tier 1

```yaml
agent:
overlay:
task:
target:
output_format:
write_mode: read-only | local-only
stop_only_if:
```

Confirm before proceeding:

- the task remains read-only or local-only;
- no artifact will be sent, uploaded, published, or copied externally;
- no governed field, source-of-truth record, permission, sharing setting, production
  system, or irreversible artifact will change;
- the requested output and prohibited write surfaces are clear.

If any confirmation fails, route to Full Intake.

## Full Intake — Tier 2, Tier 3, or Governed Work

```yaml
agent:
overlay:
task:
target:
system_of_record:
owner:
write_needed:
approved_write_surfaces:
blocked_write_surfaces:
approval_source:
risk_tier: 2 | 3
required_output:
tests_or_evidence_required:
rollback_plan:
stop_only_if:
```

Before work begins, verify:

- the exact target and system of record;
- the owner and approval source;
- allowed and blocked write surfaces;
- governed fields and sensitive data boundaries;
- required tests, evidence, rollback, and final-report destination;
- the Live Readiness Checklist is complete.

## Escalation

Escalate from Lightweight to Full Intake when scope expands, a local artifact is about
to leave the local environment, authorization becomes unclear, or the task touches an
external system, production, governed records, permissions, sharing, sensitive data, or
irreversible state.

## Output Rule

Passing validation, readiness checks, capability checks, labels, or tier classification
never creates write authorization.