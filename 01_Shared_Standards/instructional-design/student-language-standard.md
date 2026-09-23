# Student Language Standard

Teacher modeling must produce student-appropriate language artifacts that
instructional materials can directly extract and reuse on slides, flowcharts,
and tutorials.

## Teacher Language vs Student Language

| Aspect | Teacher Language | Student Language |
|--------|---|---|
| **Purpose** | Sets cognitive focus; manages behavior; prompts deeper thinking | Formulates questions; tests hypotheses; demonstrates understanding |
| **Structure** | Deliberate phrasing; academic syntax; clear enunciation; strategic pauses | Informal, fragmented, conversational; emergent as meaning unfolds |
| **Examples** | "Based on the text, what can we infer?" "Who can build on that?" | "I notice that..." "I agree because..." "Can you explain what you meant?" |
| **Tone** | Authoritative yet supportive; scaffolds learner's zone of proximal development | Peer-to-peer; shifts from casual to academic as confidence grows |

## Teacher Modeling Outputs for Materials Extraction

Modeling must produce four artifact types that Materials Coach reuses:

### 1. Think-Aloud Transcripts
- Teacher narrates internal thought process aloud
- Written in student-accessible language
- Extractable phrases: "I notice...", "I think...", "I checked by...", "That's not right because..."
- Materials uses: Fills slide text, worked examples, thought bubbles

### 2. Worked Examples
- Show how a 9th grader (not the teacher) actually approaches the task
- Problem statement → Student-level reasoning → Solution
- Include misconceptions and self-corrections
- Materials uses: Practice problems, tutorial sequences, step-by-step walkthroughs

### 3. Student Sentence Frames
- "I notice that..." (observation)
- "I agree because..." (evidence-based agreement)
- "Can you explain what you mean by...?" (peer questioning)
- "I thought... but that's wrong because..." (self-correction)
- Materials uses: Discussion prompts, peer-collaboration slides, reflection questions

### 4. Error Analysis in Student Voice
- Common mistake articulated as a student would make it
- Self-correction step shown from student perspective
- Example: "I thought we add first, but that's wrong because of the parentheses"
- Materials uses: Anchor charts, error-pattern slides, misconception checks

## Vocabulary Integration

Inherit `unit-vocabulary-map-standard.md` and
`lesson-vocabulary-planner-response-standard.md`. Preserve source location,
evidence class, confirmation state, CLS2 category, CLS4 category, and practice
evidence. Keep teacher language, student language, material safety, and assessment
eligibility independent. Only confirmed vocabulary marked material-safe may flow
to student-facing materials. Assessment requires explicit instruction or practice.

## Rubric Language Requirements

Student-facing rubrics are a mandatory application of this standard.

1. Criteria and performance levels use first-person language ("My idea is clear") instead of teacher-observer phrasing ("The student demonstrates...", "The audience can tell...").
2. Teacher-facing scoring notes and calibration guidance stay separate from the student-facing rubric.
3. A final-assessment response shows the complete rubric and total scoring model, not only a rotating or changed row.
4. State each criterion's weight and the total possible score; preserve and show stable rows alongside any rotating row.
5. Rubric language stays accurate to the approved evidence and must not oversimplify the learning target.
6. A beginning-performance score points toward another attempt or a specific next step when revision is permitted.

Example: teacher-facing "The student watched, checked the taught move, and made one specific fix" becomes student-facing "I watched my video, found one problem, and made a change that helped." Teacher wording may stay in the scoring guide.

## Pipeline Rule

1. **Teacher Modeling Coach** creates all 4 artifact types in student voice
2. **Instructional Materials Coach** extracts from modeling outputs
3. **QA Reviewer** scores "Student Language Authenticity" on rubric
   - Must be ≥3: Slide text comes from modeling OR approved student frames
   - Student voice is authentic (exploratory, peer-focused, evidence-based)
   - Never teacher directives or formal academic syntax
4. Student-facing materials use approved Google Drive destinations, not GitHub storage.

## Version

0.3.0

## Changelog

- 0.3.0 added Rubric Language Requirements (#822): first-person student
  rubric language, separated teacher scoring guidance, complete-rubric and
  weighting visibility, and next-step guidance on beginning scores.
- 0.2.0 initial student-language artifact and pipeline rules.