# Material Design Defaults

## Purpose

Use these defaults for stable classroom-material design choices across future
builds and revisions unless the current request gives different constraints.

## Core Priorities

Optimize for clarity, coherence, visual hierarchy, accessibility, and teacher
usability. Prefer the smallest useful material that fully supports the task.

When a material feels overloaded, cut redundancy, decorative clutter, repeated
directions, and elements that do not support the instructional purpose.

## Default Build Rules

- Prefer short, scannable, classroom-ready, low-clutter materials.
- Use chunking and whitespace to break content into clear sections.
- Keep related text, visuals, and actions close together.
- Make every element deliberate and easy to justify.
- Keep sequencing, task flow, and completion criteria visible.

## Modeling First

When a task introduces a new process, asks students to explain reasoning, or
requires creative judgment, include modeling support.

Prefer:

- worked examples
- annotated examples
- non-examples or common mistakes
- short teacher cues
- guided practice before independent work

## Evidence First

Every material should make the expected student evidence obvious.

Students should be able to tell:

- what they are making or completing
- how much is expected
- how they know they are finished
- what success looks like

## Length and Writing Load

Keep worksheets to one page when possible. Use multiple pages only when separate
stages, readings, or workspaces would feel cramped if compressed.

Default to mostly short responses plus one or two purposeful full-sentence
moments. Use longer writing only when the lesson goal depends on explanation,
analysis, or reflection.

## Worksheet Identification And Challenge Cards

For student-facing worksheets that need student identification, place the primary
identification row near the top of the first page rather than at the bottom. Use
`Name`, `Hour`, and `Date`, plus a compact `Unit/Day` lesson identifier when the
unit sequence provides one. Prefer notation such as `1.1` for Unit 1, Day 1 so
printed work can be sorted and traced to the lesson sequence without a long label.

Treat the worksheet title and that identification row as one compact first-page
top band by default. Keep the title clearly larger than body text without using a
display-scale heading that consumes substantial work space; keep the
identification fields immediately adjacent to the title with minimal vertical
separation. A renderer or approved template may opt out when the teacher requests
a different layout or the material type needs a distinct first-page treatment.
Do not let Warm-Up, Exit Ticket, learning-target, or challenge components expand
the identification band; those remain lesson sections below it.

When a lesson uses differentiated challenge cards, use neutral student-facing
labels `Challenge A`, `Challenge B`, and `Challenge C`. Do not expose ability
labels such as `Beginning`, `Middle`, `On Grade`, or `Advanced`. Students should
be able to move among challenges without the material assigning an ability
identity.

Keep one essential learning target across the A/B/C family. Vary scaffolding,
independence, constraints, or depth rather than creating unrelated assignments:

- Challenge A may use stronger visual scaffolds, choices, sentence starters, or
  partially structured response space.
- Challenge B may use lighter prompts and more independent explanation,
  repair, planning, or practice.
- Challenge C may use fewer supports plus additional constraints, transfer, or
  deeper justification.

When the teacher has approved the quick-score pattern for the lesson, challenge
cards may use this compact 0-2 scoring strip:

- `2 - Got It` - complete and demonstrates or explains the intended choice.
- `1 - Almost` - mostly complete; needs one meaningful fix or clarification.
- `0 - Not Yet` - missing, off-task, or does not demonstrate the intended choice.

Treat this strip as fast progress/evidence marking, not as a replacement for an
approved analytic rubric when the lesson requires one.

For challenge-card worksheets, keep these regions visually distinct and easy to
scan: challenge title or lesson identity; top identification row; directions;
challenge task; student work/response space; and quick-score area. Rendered
judgments such as spacing, writing-room adequacy, and scanability require visual
or manual review when they cannot be proven structurally.

## Worksheet Opening And Closing

Ordinary student worksheets should include a concise, lesson-specific `Warm-Up`
near the beginning and a concise `Exit Ticket` near the end by default.

Use current teacher/lesson-spec content when it explicitly supplies either
component; do not add a generated duplicate. When the lesson deliberately
designates an equivalent lesson-specific self-critique or reflection as its
closing evidence, reuse that component as the Exit Ticket instead of adding a
second closing prompt.

When a worksheet needs a safe default because current governed evidence does not
supply one, derive it only from already-authored lesson content such as the
learning objective, worksheet task, or existing response prompt. Do not invent a
new learning target, assessment criterion, or unrelated generic activity.

Differentiation may change scaffolding, independence, response support, transfer,
or depth, but it must not silently remove the opening or closing component from
an otherwise standard worksheet. For multi-day packets, apply the rule to each
day worksheet independently.

Keep these components below the compact #1567 title/identification band and
protect useful core-task and response space. If adding the components would make
the worksheet cramped, prefer another page or a more compact redundant element
rather than shrinking required work space below usable levels. Rendered
space/scanability judgments still require visual or manual review when structural
evidence cannot prove them.

## Visual Baseline And Components

See `material-design-defaults/visual-baseline-and-components.md` for the token
baseline, layout defaults, scaffolding defaults, reusable components, and
discussion support guidance.

## Accessibility and Cognitive Load

- Reduce eye strain and keep text scannable.
- Maintain comfortable contrast and strong visual hierarchy.
- Segment content into short, user-paced parts.
- Use labels, arrows, highlights, or emphasis cues to direct attention.
- Use near-black and near-white instead of pure black and pure white when it improves comfort.
- Avoid dense text blocks, cramped layouts, tiny response boxes, and decorative visuals.

## Teacher Usability

Keep setup minimal, directions short, sequencing clear, and student progress easy
to monitor during live instruction.

## Revision Defaults

Preserve the core learning goal, useful structure, and elements that clearly
support comprehension or task flow. Cut redundancy, long paragraphs, unnecessary
duplication, weak design elements, and clutter.

Use direct edits when the source is available. Otherwise give concise,
high-value audit feedback.

## Realistic Teacher-Input Benchmarking

When a comparison is intended to measure the normal teacher-facing workflow, preserve the simulated teacher utterance at the level of detail the teacher actually supplied. Do not silently upgrade a short natural request into an expert or system-style specification.

Keep benchmark controls outside the simulated teacher utterance. The harness may define source packets, execution conditions, model/configuration, blinding, and evaluation criteria, but those controls must not be disguised as teacher-authored instructional or design requirements.

Give both comparison arms the same teacher utterance and equivalent harness controls unless the prompt itself is the intended independent variable. Details the teacher actually supplied remain part of the utterance and must not be removed merely to make it shorter.

## Comparative Artifact Test Context Isolation

When a teacher asks to compare classroom-artifact generation approaches as independent runs, keep the experimental execution context explicit and separate from the classroom task itself.

For an independent A/B comparison:

- state the clean-context or fresh-chat condition explicitly so prior worksheet discussion, candidate choices, or earlier outputs cannot leak into the comparison;
- give both arms the same fixed source packet and equivalent model/configuration, blinding, and evaluation controls unless one of those controls is the intended independent variable; and
- do not add fresh-chat boilerplate to ordinary single-artifact generation when no independent comparison is being run.

A fresh chat is one control, not proof of a valid experiment. Source evidence and the intended independent variable must still be held constant.

## Override Conditions

Override these defaults when the user asks for compact, print-efficient,
low-ink, denser, or more complex materials, or when the lesson goal clearly
requires extended writing or a different format.

## Version

0.6.0

## Changelog

- 0.6.0 requires explicit clean-context isolation for independent comparative artifact tests while keeping fixed-source/config/evaluation controls equivalent across arms (#3090).
- 0.5.0 separates realistic teacher utterances from benchmark harness controls so comparative artifact tests do not hide teacher-facing UX burden through prompt-engineering leakage (#3091).
- 0.4.0 makes concise lesson-specific Warm-Up and Exit Ticket sections standard worksheet defaults, preserves supplied/equivalent closing evidence without duplication, applies the rule per differentiated/day worksheet, and keeps both below #1567's compact header without sacrificing core response space (#1568).
- 0.3.0 makes a compact title + student-identification top band the default for worksheets, keeps lesson sections below that band, and preserves an explicit layout opt-out (#1567).
- 0.2.0 adds reusable worksheet identification, neutral Challenge A/B/C
  differentiation, unit/day notation, quick-score guidance, and rendered-review
  boundaries from the Typography Business Card worksheet review (#1805).
- 0.1.1 existing classroom-material design defaults.
