# Material Quality Rubric

Score each category from 1 to 4.

- 1 = Not met
- 2 = Approaching
- 3 = Meets
- 4 = Exemplary

A material should not ship below 3 on instructional alignment, teacher modeling
support, accessibility, student-language authenticity, vocabulary integration,
or digital media throughline.

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
| Vocabulary integration | Uses confirmed vocabulary, preserves teacher/student separation, honors `Slide/Worksheet Safe?`, and assesses only after explicit instruction or practice. |
| Digital media throughline | Shows creator choices shaping audience interpretation. |
| Student independence | Scaffold level matches student readiness. |
| Teacher revision burden | Requires only minor teacher edits. |
| Compute efficiency | Passed gates first and reused approved assets. |

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

0.2.0