# Teacher Decision Studio Standard

Table-first consultation protocol for rubric-format and assessment-design
choices. Default response is a readable comparison table, a concise
recommendation, and an explicit teacher choice. Never auto-approves a rubric,
readiness state, or classroom artifact. See
`teacher-decision-studio-previews-standard.md` for per-option worksheet and
PDF preview requirements.

## Ownership

`Assessment Agent / Student Evidence Coach` is a canonical governance-level
ownership label defined in `00_Governance/agent-os-governance-v1-baseline.md`
for Notion-side evidence and assessment readiness state; it has no GitHub
overlay in `04_Registry/agent-inheritance-registry.md`. Do not invent one.
Rubric-format and assessment-design consultation is handled by existing
registered overlays: Teacher Modeling Coach owns explanation-risk and
student-understanding analysis; Instructional Materials Coach owns final
student-facing rubric rendering; ChatGPT Orchestrator owns interaction
routing; GitHub writes route only through GitHub Service Agent.

## Locked Interaction Model

For a meaningful rubric or assessment decision:

1. Name the decision in plain language; ask at most two or three high-value
   questions when context is genuinely missing.
2. Present two or three recommended choices in a table, plus
   `Other / Build My Own`, each with benefits, downsides, assessment impact
   (evidence/grading/feedback/revision), and explanation/support burden.
3. Provide a recommendation without auto-selecting it; show where assessment
   and rubric-explanation views disagree instead of forcing agreement.
4. Let the teacher select, combine, modify, reject, or defer; show an
   immediate preview of the resulting rubric or student experience.
5. Record backend approval or readiness changes only after explicit teacher
   confirmation and authorized-owner execution.
6. Skip the table for simple direct edits with no meaningful tradeoff.

## Format Catalog

Show only the two or three most relevant formats plus `Other / Build My Own`;
never dump every format into one response.

| Format | Minimum description |
|---|---|
| 3/4/5-column rubric | Three to five student-readable performance levels; more columns add scoring precision and reading/explanation burden. |
| Single-point | One expected standard plus `What is working` / `What to improve`. |
| Checklist | Required features marked `Yes / Not yet`. |
| Feedback-only | Strengths, questions, next steps; no levels or points. |
| Holistic | One overall performance description. |
| Hybrid | Short leveled rubric plus feedback and a next-step section. |
| Conference | Student self-scores and discusses evidence with the teacher. |

## Explanation And Support Scale

| Level | Meaning |
|---|---|
| Low | Brief introduction plus one example is enough. |
| Medium | Row-by-row explanation, a worked example, and guided practice. |
| High | Repeated explanation, annotated examples, side-by-side comparisons, and check-ins. |

State the reason for the assigned level; do not display only the label.

## Required Content Below The Table

Joint recommendation; where the views disagree; biggest risk; important
unknowns; teacher choice (select, combine, enter Other, or make no change).

## Non-Goals

Do not let agents make final rubric or grading decisions without teacher
confirmation. Do not require a decision table for factual questions or
tradeoff-free edits. Do not weaken production authorization or source-control
gates. Do not write classroom artifacts to GitHub. Do not create a new
canonical assessment agent without explicit governance and registry
authorization.

## Version

0.1.0
