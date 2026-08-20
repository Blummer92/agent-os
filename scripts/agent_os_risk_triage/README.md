# Agent OS Risk Triage Core

## Purpose

`agent_os_risk_triage` is the pure-local deterministic first stage of the governed risk-to-issue triage path. It consumes only immutable caller-supplied structured evidence and returns one advisory disposition. It never retrieves GitHub data and never performs a write.

Canonical lifecycle and authorization policy remain in `01_Shared_Standards/github/issue-lifecycle-standard.md`, `01_Shared_Standards/github/issue-acceptance-automation.md`, and `00_Governance/write-authorization-policy.md`.

## Input contract

`RiskTriageInput` contains a `FindingEvidence` record plus optional structured candidate evidence for current work, existing issues, and canonical risk owners. Candidate identity, state, relationship, and evidence are supplied by the caller; the core does not select identity from prose.

Qualitative `likelihood` and `impact` are preserved on the immutable finding only. They are not converted to a score and never authorize or select issue creation.

## Dispositions

The core returns exactly one of:

- `no-action` — supplied evidence says no action is required;
- `record-in-current-work` — exactly one valid supplied current-work target matches;
- `link-canonical-risk-owner` — exactly one valid supplied canonical risk owner matches;
- `update-existing-issue-candidate` — exactly one valid supplied existing issue matches;
- `create-child-issue-candidate` — supplied relationship evidence identifies one valid child target;
- `create-new-issue-candidate` — action is required and supplied evidence establishes no current target;
- `needs-decision` — evidence is ambiguous, conflicting, stale, retired, closed, unknown, or otherwise insufficient for one deterministic disposition.

Every result carries bounded reason codes. Targeted dispositions preserve the supplied target identity and evidence.

## Deterministic boundary

The core compares explicit enums and identities only. `equivalent` and `overlaps` are caller-declared structured relationships; `child` is an explicit caller-declared child relationship. The core does not infer semantic near-duplicates or similarity from finding text.

A valid unambiguous canonical risk owner takes precedence over downstream issue candidates. Conflicting canonical owners fail closed to `needs-decision`. Closed, stale, retired-scope, and unknown candidates cannot be selected as current targets.

## Side-effect boundary

The package imports no GitHub client, HTTP library, credential provider, subprocess helper, workflow adapter, or external service. `mutation_performed` and `write_authorized` are fixed false on results. Child/new issue dispositions are candidates only; later issue drafting or submission remains governed by the existing issue-draft architecture.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_risk_triage
```

Repository validation remains owned by the canonical testing and release standards.
