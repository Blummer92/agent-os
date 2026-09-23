# Issue Quality Taxonomy

## Purpose

Define one reusable issue-quality contract for pure, report-only checks inside
`scripts/agent_os_issue_acceptance/`.

This standard complements existing Agent OS acceptance, lifecycle, routing, and
post-PR contracts. It does not replace them and creates no authority.

## Supported Issue Families

- `roadmap`
- `implementation`
- `validation`
- `governance`
- `cleanup`

## Section Expectations

| Section | roadmap | implementation | validation | governance | cleanup |
|---|---|---|---|---|---|
| Goal / Objective | required | required | required | required | required |
| Scope | required | required | required | required | required |
| Acceptance criteria | recommended | required | required | required | recommended |
| Dependencies | required | recommended | recommended | recommended | recommended |
| Definition of done | recommended | required | required | required | recommended |
| Tests / validation | recommended | required | required | recommended | recommended |
| Parent | recommended | recommended | recommended | recommended | recommended |
| Related issues | recommended | recommended | recommended | recommended | recommended |
| Handoff notes | recommended | recommended | recommended | recommended | recommended |
| Remaining risks | recommended | recommended | recommended | recommended | recommended |

## Outcomes

Reuse `scripts/agent_os_issue_acceptance/models.py` exactly: `pass`, `warn`,
`fail`, and `manual-review`.

Missing required content is `fail`. Missing recommended content is `warn`.
Ambiguous or vague content is `manual-review`; checkers must not guess it into
`pass` or `fail`.

## Missing, Empty, And Placeholder Content

A section is missing when its heading is absent. A section is empty when it has
no non-whitespace content. Obvious placeholder-only content such as `TBD`,
`TODO`, `_No response_`, `N/A?`, or `placeholder` is ambiguous and returns
`manual-review` rather than being interpreted semantically.

## Parent And Related-Issue References

`Parent` and `Related issues` are recommended context unless another canonical
standard makes them required for a specific lane. When present, they should
contain at least one `#<number>` issue reference. Missing recommended sections
are `warn`; present sections without a resolvable reference are `warn`;
placeholder-only sections are `manual-review`.

## Dependencies And Blockers

A `Dependencies` section may name dependencies or explicitly state none. When
blocker language such as `blocked`, `blocking`, or `blocks` is present, the text
should also state an unblock condition using bounded language such as `until`,
`once`, `when`, `after`, or `unblock`. Blocker language without such a condition
is `manual-review`. No blocker language is `pass` for this check.

## Acceptance-Criteria Quality

For families where Acceptance criteria are required, a missing or empty section
is `fail`. Placeholder-only criteria are `manual-review`.

Every criterion must be itemized or checklist-like and independently include
observable completion language. Narrow deterministic checks may recognize
concrete verbs such as `passes`, `returns`, `contains`, `creates`, `rejects`,
`preserves`, `matches`, `reports`, or `exists`. If every item cannot be
classified safely, return `manual-review` rather than attempting semantic
judgment.

When Acceptance criteria are present but no `Tests / validation` section is
present, return `warn`; this indicates missing supporting validation evidence,
not implementation failure.

## Checker Boundary

Issue-quality checkers accept caller-supplied local text and finite metadata,
return existing `CheckResult` records, and are pure and deterministic. They
perform no GitHub fetch or mutation, filesystem write, subprocess, environment
inspection, model call, network call, persistence, or external-system access.
They do not set issue state, labels, milestones, assignees, readiness, approval,
merge, closure, or external-write authority.

Operational state, authorization, routing, queue/lane selection, and post-PR
recommendation remain owned by their existing canonical contracts.

## Version

0.1.0
