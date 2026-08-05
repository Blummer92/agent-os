# Issue Quality Taxonomy
## Purpose
Define one reusable taxonomy that issue-completeness, dependency/blocker,
acceptance-criteria, and cleanup-recommendation checkers all read from,
instead of each checker inventing its own sections, outcomes, or scope.
## Boundary
This is a taxonomy contract only. It defines what sections, outcomes, and
fields mean. It does not implement a checker, does not call GitHub, and does
not replace `issue-acceptance-automation.md`'s Tier system, Readiness
Outcomes, or Acceptance Report Schema — it extends that standard's vocabulary
to issue-quality review rather than competing with it.
## Issue Families
`roadmap`, `implementation`, `validation`, `governance`, `cleanup`. Section
expectations below apply to every family unless a row says otherwise.
## Required Sections (by family)
| Section | roadmap | implementation | validation | governance | cleanup |
|---|---|---|---|---|---|
| Goal / Objective | required | required | required | required | required |
| Scope | required | required | required | required | required |
| Acceptance criteria | recommended | required | required | required | recommended |
| Dependencies | required | recommended | recommended | recommended | recommended |
| Definition of done | recommended | required | required | required | recommended |
## Recommended Sections (all families)
Parent, Related issues, Non-goals, Likely files, Tests / validation, Owner
agent, Handoff notes, Remaining risks. A missing recommended section is
`warn`, never `fail`.
## Outcomes
Reuse `issue-acceptance-automation.md`'s four-state vocabulary exactly:
`pass`, `warn`, `fail`, `manual-review`. `pass` means the expectation is
satisfied; `warn` means a recommended item is missing or weak; `fail` means a
required item is missing; `manual-review` means the input is ambiguous,
natural-language, or otherwise not deterministically decidable. A checker
must never resolve ambiguity into `pass` or `fail` — route it to
`manual-review`.
## Missing vs. Ambiguous
"Missing" means the section heading or field is absent, or present with no
content (`_No response_`, blank, or whitespace-only). "Ambiguous" means
content is present but a deterministic rule cannot classify it (vague
language, unclear scope, contradictory statements). Missing required
sections are `fail`; missing recommended sections are `warn`; ambiguous
content is always `manual-review`, never guessed into `pass` or `fail`.
## Governance-Sensitive Fields
Automation must never write to: issue state, labels, milestone, assignees,
readiness/approval/audit fields, or body text. This mirrors
`00_Governance/write-authorization-policy.md` and applies to every checker
built from this taxonomy. Findings are report-only.
## Offline Checker Input / Output Contract
- Input: an issue body string (and, where relevant, already-supplied
  metadata), never a live GitHub fetch in the first implementation.
- Output: one or more `CheckResult`-shaped records (`name`, `status`,
  `message`, `evidence`) as already defined in
  `scripts/agent_os_issue_acceptance/models.py`, reused rather than
  redefined.
- Checkers are pure functions: same input always produces the same output.
## Parent-Reference Expectations
A `## Parent` section is present and contains at least one issue reference
(`#<number>`). Missing section or missing reference inside an existing
section is `warn`, not `fail` — a parent is recommended context, not a hard
gate, unless a family-specific standard says otherwise.
## Related-Issue-Reference Expectations
A `## Related issues` section listing issue references. Same missing/warn
rule as parent references.
## Dependency And Blocker Expectations
A `## Dependencies` section states dependencies, or `none`. Blocker language
(e.g., "blocked", "blocking") without an accompanying unblock condition
(e.g., "until", "once", "when", "after") is `manual-review`. Blocker language
with a stated condition is `pass`. No blocker language is `pass`.
## Acceptance-Criteria Quality Expectations
Acceptance criteria must be present (checklist or itemized), testable (tied
to an observable outcome), and not solely placeholder text. Missing criteria
on a family that requires them is `fail`; present-but-vague criteria is
`manual-review`; criteria unsupported by any `Tests / validation` section is
`warn`.
## Validation, Handoff, Definition-Of-Done, Remaining-Risk Expectations
`Definition of done` and `Remaining risks` follow the same missing/ambiguous
rules as other sections. `Handoff notes` are recommended, not required,
except where a family-specific overlay elevates them.
## Cleanup Recommendation Boundaries
A cleanup-recommendation report built on this taxonomy may aggregate and
prioritize findings from other checkers, but it must stay report-only: no
label change, no body edit, no state change, no owner assignment. It
distinguishes "required fix" (any `fail`) from "suggested improvement" (any
`warn`) and leaves `manual-review` items for a human decision.
