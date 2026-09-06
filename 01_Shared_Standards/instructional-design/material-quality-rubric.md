# Material Quality Rubric

Score each category from 1 to 4.

- 1 = Not met
- 2 = Approaching
- 3 = Meets
- 4 = Exemplary

A material should not ship below 3 on instructional alignment, teacher modeling
support, accessibility, student-language authenticity, rubric completeness &
weighting, vocabulary integration, or digital media throughline.

| Category | 3 means |
|---|---|
| Instructional alignment | Matches the approved learning target. |
| Teacher modeling support | Uses an approved worked example or model. |
| Student evidence alignment | Task produces the defined evidence. |
| Visual clarity | One purpose per slide; clear hierarchy and labels. |
| Worksheet usability | Directions, model, practice, and reflection are present. |
| Accessibility/UDL | Alt text, contrast, and multiple representations are present. |
| 9th-grade readability | Grade-level rigor with clear vocabulary support. |
| Student language authenticity | Slide text comes from modeling outputs or approved student frames; student voice is exploratory, peer-focused, evidence-based; never teacher directives. |
| Rubric completeness & weighting | Rubric criteria use first-person student language per `student-language-standard.md`; the complete rubric, weighting, and total score are visible, not only a rotating or changed row. |
| Vocabulary integration | Uses confirmed vocabulary, preserves teacher/student separation, honors `Slide/Worksheet Safe?`, and assesses only after explicit instruction or practice. |
| Digital media throughline | Shows creator choices shaping audience interpretation. |
| Student independence | Scaffold level matches student readiness. |
| Teacher revision burden | Requires only minor teacher edits. |
| Compute efficiency | Passed gates first and reused approved assets. |

## Rendered Classroom Review Gate

Student-facing slide decks require a rendered-review checkpoint before a
classroom-ready claim. Successful PPTX/source generation or structural
validation alone is not sufficient evidence of rendered quality.

The rendered review must inspect, at minimum:

- occlusion and opaque placeholder/container artifacts;
- contrast and readability of required instructional text;
- clipping, overflow, and unintended region collisions;
- instructional visual hierarchy and role-appropriate scale;
- a phone-preview/readability perspective; and
- a projected-classroom perspective when the deck is intended for projection.

Reuse mechanical artifact-structure/layout QA for facts it can prove. Keep
those results separate from visual judgments that require rendered inspection.
If the available evidence cannot prove a rendered judgment, return
`manual-review-required` for that dimension rather than a classroom-ready pass.
A structurally valid deck with visible occlusion, clipping, unreadable contrast,
or broken hierarchy cannot satisfy this gate.

## Quick QA Heuristics

Legacy `agent_tools/material_qa.py` checks are advisory heuristics, not a full rubric.
Use them only for quick final checks of generated material files.

A quick check should flag whether the material has:

- a warmup, entry task, do-now, or equivalent launch
- a main activity, practice task, creation task, or build task
- an exit ticket, reflection, wrap-up, or transfer prompt
- student action words such as write, choose, explain, create, compare, or build
- no instruction line longer than about 35 words

Failing a heuristic means `CHECK`, not automatic rejection. Use the rubric rows
above for final decisions.

## QA Feedback Rule

QA feedback must name the rubric row, the exact issue, and the requested change.
Do not rewrite the full material unless explicitly scoped.

## Revision Rule

A revision should change only the failed rubric rows unless the source changed
or a gate violation is discovered.

## Version

0.3.1

## Changelog

- 0.3.1 added the rendered classroom review gate for phone/projector quality
  and explicit separation of mechanical evidence from manual visual judgment
  (#1835).
- 0.3.0 added the Rubric completeness & weighting row (#822) as a required
  ship gate.
- 0.2.0 initial rubric, QA heuristics, feedback, and revision rules.