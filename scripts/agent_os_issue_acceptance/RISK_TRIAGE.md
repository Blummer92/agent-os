# Risk Triage Contract

`risk_triage.py` is the pure-local RIT1 contract for issue #1296.

## Boundary

The core consumes only immutable caller-supplied evidence. It does not retrieve
GitHub state, inspect live issues, call a network or subprocess, mutate a
repository or issue, infer write authorization, or submit an issue draft.
Connected read-only retrieval belongs to a later adapter, if separately governed.

Likelihood and impact are qualitative evidence only. They are preserved in the
result and never converted into a numeric authorization or issue-creation score.

## Input

`RiskFindingEvidence` carries a stable finding identity and concise finding text,
optional qualitative likelihood/impact, and optional structured evidence for:

- current-work candidates;
- existing-issue candidates;
- canonical risk owners;
- explicit manual-review need; and
- explicit no-action evidence.

Candidates preserve their caller-supplied identity, currentness state,
relationship/equivalence evidence, and bounded explanatory evidence.

## Output

`triage_risk_finding()` returns exactly one advisory `RiskDisposition`:

- `no-action` — explicit supplied evidence says no issue action is needed;
- `record-in-current-work` — one current-work target is explicitly proven;
- `link-canonical-risk-owner` — one current canonical owner is explicitly supplied;
- `update-existing-issue-candidate` — one current existing issue is explicitly equivalent/overlapping;
- `create-child-issue-candidate` — an explicit structured child relationship is supplied;
- `create-new-issue-candidate` — no target exists and no ambiguity blocks a new candidate;
- `needs-decision` — ambiguity, conflicting targets, non-current targets, or explicit manual review prevents deterministic disposition.

Every result has finite reason codes, preserves target identity/evidence when
applicable, and hard-codes execution and external-write authority to false.

## Deterministic/manual-review boundary

Free-form finding text is never used to infer semantic equivalence or a near
duplicate. Exact equivalence, overlap, child relationship, canonical ownership,
and currentness must arrive as structured caller-supplied evidence. Unknown or
conflicting evidence fails closed to `needs-decision`.

Closed, stale, and retired-scope targets are not revived by this core. They route
to `needs-decision`, preserving the lifecycle boundary owned by #543.

Canonical owner evidence wins only when exactly one unambiguous current owner is
supplied. The result links that identity rather than copying canonical risk prose.

## Downstream use

`create-child-issue-candidate` and `create-new-issue-candidate` are advisory
inputs that may later feed the existing #599/#600 issue-draft architecture. This
module does not submit, edit, label, close, reopen, or otherwise mutate issues.

Canonical lifecycle and authorization policy remains in the shared GitHub
standards and governance files; this document intentionally does not duplicate
that policy text.
