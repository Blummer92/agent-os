# Teacher Decision Studio Previews Standard

Extends `teacher-decision-studio-standard.md`: every rubric/worksheet option
in a Teacher Decision Studio comparison gets an in-chat section-by-section
preview plus a labeled PDF preview link, so a teacher compares actual layout
and wording instead of abstract labels alone.

## Required Interaction

After the comparison table, each option gets an action equivalent to
`View Option <N> worksheet` and `Open Option <N> PDF`. Opening an option shows
the actual student-facing structure, not another prose summary.

## Required Preview Structure

Per option: title and purpose; student-readable directions; the actual
planning/evidence fields (prompts, boxes, checklists); the complete
option-specific rubric or feedback section; reflection/next-step section;
scoring visibility (points, weighting, or explicit feedback-only statement);
a teacher-support note on what must be explained first; and the status label
`Teacher Decision Preview -- Not Yet Authorized for Classroom Distribution`.
The in-chat preview may be condensed; the linked PDF must show the complete
worksheet as the student would receive it.

## Source Worksheet Behavior

1. Search for and retrieve the current approved source worksheet, packet, or
   assessment before generating variants; identify that source in the
   response.
2. Preserve content not part of the decision under review; change only the
   requested rubric, feedback, scoring, or section structure across options.
3. Never silently reconstruct missing source content. When no usable source
   exists, state that plainly, show a clearly labeled wireframe or mockup if
   safe, and never claim a complete source-based PDF exists.

## PDF Rules

Each option PDF: is a separate link named like
`<Unit> Rubric Preview -- Option A -- 3 Column.pdf`; identifies the option
and format on its first page; includes every worksheet section the option
affects; uses student-facing language per `student-language-standard.md`;
preserves the full scoring structure; carries a visible preview watermark or
header plus a generated timestamp or version identifier; and stays readable
on screen and when printed, with no clipped text, broken tables, or missing
pages. Preview PDFs are decision artifacts, not final classroom materials:
they never overwrite the approved worksheet and never imply Production
Authorized status.

## Destination And Storage Rules

Final student-facing materials remain an approved Drive outcome. Preview
PDFs use an approved preview/review destination or a bounded temporary
artifact location; never store classroom PDFs in GitHub, change sharing
permissions automatically, overwrite an existing Drive file, or treat a
preview link as production authorization. If no approved preview destination
is available, stop before the external write and return an in-chat preview
plus the exact destination decision required.

## Non-Goals

Do not automatically choose or publish an option. Do not automatically
replace the approved worksheet. Do not generate three cosmetically different
files sharing the same underlying rubric structure.

## Version

0.1.0
