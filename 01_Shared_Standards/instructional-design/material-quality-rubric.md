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

### Worksheet density and hierarchy review

For worksheets, a mechanically valid page may still require revision when the rendered hierarchy asks students to process too many competing sections at once. Review density from the instructional roles present, not from universal row, box, word, or fill-percentage limits.

When the render is overloaded, identify the specific competing directions, banks, tables, reflections, checklists, scoring controls, or visual regions creating the conflict. Prefer simplifying, consolidating, or deleting redundant simultaneous elements before adding pages or decorative structure. Preserve required student evidence, usable response space, and intentional whitespace.

Intentional whitespace is not a defect by itself. When structural evidence cannot establish whether density, hierarchy, or whitespace is instructionally manageable, route that dimension to rendered/manual review rather than assigning a mechanical pass.

### Worksheet vertical pagination balance

A mechanically valid worksheet page may still require revision when its page
composition strands vertical space while later content overflows. Use
available vertical page space before introducing a page break.

Flag a page when rendered evidence shows a large unused vertical band and the
next bounded content block (a mission, section, or step group) would fit
safely on the same page. A band is *avoidable* when it equals or exceeds the
next block's height plus the separation that block needs. Compare band and
block from rendered block positions, not from page counts or universal fill
thresholds.

Reflow is required only when all of these hold:

- the next bounded block fits on the current page with clear mission
  separation preserved;
- screenshots remain readable at their instructional size;
- Kami writing and annotation response areas stay large enough for student
  use;
- no crowding, clipping, or overlap is introduced.

Do not fix the band by compressing later missions more tightly; balance
density across pages instead of moving the compression downstream. Do not
reduce required student response space or shrink screenshots below legible
size to reclaim space. Intentional whitespace that serves pacing, transitions,
or readability is not a defect.

When block heights or page occupancy cannot be established from rendered
evidence, do not assign a mechanical pass; route the pagination-balance
dimension to rendered/manual review.

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

0.3.3

## Changelog

- 0.3.3 adds a worksheet vertical-pagination-balance review dimension: a large unused vertical band is a defect when the next bounded block would fit safely on the page, with screenshot-legibility, Kami response-space, mission-separation, and no-crowding guards, and fail-closed manual review when block heights cannot be established (#2735).
- 0.3.2 makes worksheet cognitive-density/hierarchy an explicit rendered-review dimension, names competing instructional regions, prefers simplification over added structure, preserves evidence/response space, and rejects universal fill/box/word thresholds (#3098).
- 0.3.1 added the rendered classroom review gate for phone/projector quality
  and explicit separation of mechanical evidence from manual visual judgment
  (#1835).
- 0.3.0 added the Rubric completeness & weighting row (#822) as a required
  ship gate.
- 0.2.0 initial rubric, QA heuristics, feedback, and revision rules.