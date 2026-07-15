# Response Pattern MVP Candidate Prompt Bank

## Status

Experimental candidate prompt bank for broader Response Pattern MVP testing.

## Purpose

Provide 100 candidate prompts that stress-test whether Agent OS can produce short, modular, source-aware answers while handling real Digital Media curriculum tasks.

These prompts are not all required before merge. Use the 10-test smoke suite as the merge gate and this bank as a broader trial pool for RP2, RP3, RP4, and future QA passes.

## What This Bank Tests

- Can the agent find or ask for the right source before answering?
- Can it identify lesson names, lesson context, and lesson-plan boundaries?
- Can it distinguish modeling types such as teacher talk, think-aloud, visual analysis, demonstration, guided practice, and student reflection?
- Can it connect Notion-grounded context to response patterns without treating cached context as live verification?
- Can it recommend slide images, slide placement, and slide content density without overbuilding a deck?
- Can it keep student-facing artifact generation routed to approved Google Drive destinations instead of GitHub?

## Scoring Guidance

For each prompt, score whether the response:

- Uses the smallest useful response pattern.
- Includes Source Context when source-grounded.
- Avoids claiming live verification unless live source access was actually used.
- Names the next source or owner when context is missing.
- Avoids generating full artifacts when the prompt only asks for planning or diagnosis.
- Preserves GitHub, Notion, and Google Drive source-of-truth boundaries.

## Candidate Prompts

### A. Source Finding And Routing

1. Use the Response Pattern MVP. Find the best source to answer what the next Photography Foundations lesson should be.
2. Use the Response Pattern MVP. Tell me whether this question belongs in GitHub, Notion, or Google Drive: What should Lesson 2 teach next?
3. Use the Response Pattern MVP. I need the current source of truth for unit readiness before generating slides.
4. Use the Response Pattern MVP. The cached Notion index says the unit is ready. What source should verify that before production?
5. Use the Response Pattern MVP. Identify the correct owner for lesson modeling and teacher-talk coaching.
6. Use the Response Pattern MVP. I want to update a readiness field in Notion based on this chat. What should happen first?
7. Use the Response Pattern MVP. Find whether the lesson plan lives in Notion, Google Drive, GitHub, or needs a handoff.
8. Use the Response Pattern MVP. I found conflicting lesson titles in two places. How should the agent handle the conflict?
9. Use the Response Pattern MVP. Tell me what source context should be included when answering from a cached Notion result.
10. Use the Response Pattern MVP. Decide whether a response needs Source Context when no external source was checked.

### B. Lesson Names And Lesson Context

11. Use the Response Pattern MVP. Find the lesson name for the first Photography Foundations lesson and explain confidence level.
12. Use the Response Pattern MVP. What lesson title should be used if Notion has one title and a working draft has another?
13. Use the Response Pattern MVP. Identify the smallest source check needed to confirm Lesson 1 context.
14. Use the Response Pattern MVP. Summarize what Lesson 1 is about in three bullets or fewer.
15. Use the Response Pattern MVP. Find the lesson context needed before deciding slide order.
16. Use the Response Pattern MVP. Determine whether Lesson 1 is a hook lesson, vocabulary lesson, skill practice lesson, or reflection lesson.
17. Use the Response Pattern MVP. Tell me what is missing before we can write the full Lesson 1 plan.
18. Use the Response Pattern MVP. Identify the lesson goal, student task, and teacher modeling need from the available context.
19. Use the Response Pattern MVP. Find whether the lesson plan itself exists or whether we only have planning notes.
20. Use the Response Pattern MVP. If the lesson plan cannot be found, produce a Notion handoff instead of inventing it.

### C. Day-To-Day Teacher Modeling

21. Use the Response Pattern MVP. Find the day-to-day modeling move for Lesson 1.
22. Use the Response Pattern MVP. Identify what the teacher should model before students take photos.
23. Use the Response Pattern MVP. Give a short think-aloud for modeling intentional photo choices.
24. Use the Response Pattern MVP. Decide whether the teacher modeling should be a live demo, image analysis, or guided discussion.
25. Use the Response Pattern MVP. Find what modeling action belongs at the start of the lesson versus during student work.
26. Use the Response Pattern MVP. Give me the teacher talk for introducing angle without overexplaining.
27. Use the Response Pattern MVP. Give me the teacher talk for introducing distance through a photo example.
28. Use the Response Pattern MVP. Give me the teacher talk for introducing light through observation.
29. Use the Response Pattern MVP. Give me the teacher talk for introducing blur as an intentional choice.
30. Use the Response Pattern MVP. Decide which modeling move should be repeated daily across the unit.

### D. Different Types Of Modeling

31. Use the Response Pattern MVP. Classify this modeling need: the teacher explains how they choose a photo angle.
32. Use the Response Pattern MVP. Classify this modeling need: students compare two photos and name what changed.
33. Use the Response Pattern MVP. Classify this modeling need: the teacher demonstrates moving closer to the object.
34. Use the Response Pattern MVP. Classify this modeling need: students reflect on why their photo choice worked.
35. Use the Response Pattern MVP. Tell me when to use think-aloud modeling instead of a step-by-step demo.
36. Use the Response Pattern MVP. Tell me when to use visual analysis modeling instead of vocabulary definitions.
37. Use the Response Pattern MVP. Tell me when to use guided practice instead of direct instruction.
38. Use the Response Pattern MVP. Find the difference between teacher modeling, student practice, and student reflection for this lesson.
39. Use the Response Pattern MVP. Recommend the best modeling type for teaching composition to beginners.
40. Use the Response Pattern MVP. Recommend the best modeling type for helping students choose intentionally.

### E. Lesson Plan Discovery And Boundaries

41. Use the Response Pattern MVP. Can you find the full lesson plan for Lesson 1, or do we only have lesson planning context?
42. Use the Response Pattern MVP. What should you do if the full lesson plan is not available in the current source context?
43. Use the Response Pattern MVP. Identify which parts of a lesson plan can be inferred and which parts require source verification.
44. Use the Response Pattern MVP. Find the lesson objective, materials, modeling, practice, and exit task if available.
45. Use the Response Pattern MVP. If a lesson has no confirmed objective, produce a short blocker report.
46. Use the Response Pattern MVP. Determine whether a lesson plan is ready for student-facing slide generation.
47. Use the Response Pattern MVP. Decide whether to create a lesson plan draft or ask for source confirmation first.
48. Use the Response Pattern MVP. Find the difference between a lesson candidate and an approved lesson plan.
49. Use the Response Pattern MVP. Identify what evidence proves the lesson is ready for production.
50. Use the Response Pattern MVP. Tell me whether a lesson-plan answer should use Quick Decision, Lesson Design, Deep Research, or Review Report.

### F. Slide Image Selection

51. Use the Response Pattern MVP. Find what kind of image should go on the opening slide for a Photography Foundations lesson.
52. Use the Response Pattern MVP. Recommend whether the first slide should show a finished photo, a question, or a vocabulary word.
53. Use the Response Pattern MVP. Identify where an example photo should appear in a slide sequence.
54. Use the Response Pattern MVP. Recommend images for teaching angle, distance, light, and blur.
55. Use the Response Pattern MVP. Decide whether a Pete Eckert image belongs on the hook slide or later analysis slide.
56. Use the Response Pattern MVP. Tell me what source confirmation is needed before using a specific artist image on slides.
57. Use the Response Pattern MVP. Recommend a safe placeholder image type when final image rights are not verified.
58. Use the Response Pattern MVP. Decide whether slide images should be student examples, teacher examples, or professional examples.
59. Use the Response Pattern MVP. Identify the slide where students should compare two images side by side.
60. Use the Response Pattern MVP. Decide whether an image needs a caption, label, or no text.

### G. Slide Layout And Image Placement

61. Use the Response Pattern MVP. Tell me where the main image should go on a slide introducing intentional photography.
62. Use the Response Pattern MVP. Recommend a layout for a slide with one image and one discussion question.
63. Use the Response Pattern MVP. Recommend a layout for a slide comparing two photos.
64. Use the Response Pattern MVP. Recommend a layout for a vocabulary-in-context slide.
65. Use the Response Pattern MVP. Decide when an image should fill the whole slide.
66. Use the Response Pattern MVP. Decide when the image should be on the left and teacher question on the right.
67. Use the Response Pattern MVP. Decide when the image should be centered with minimal text.
68. Use the Response Pattern MVP. Recommend where to place a callout label on a photo without cluttering the slide.
69. Use the Response Pattern MVP. Identify which slide should have no image and only a short instruction.
70. Use the Response Pattern MVP. Decide whether a slide needs one image, two images, or no image.

### H. Slide Content Density

71. Use the Response Pattern MVP. Decide how much text should go on a hook slide for elementary students.
72. Use the Response Pattern MVP. Decide how much content should go on a slide that introduces a new photo concept.
73. Use the Response Pattern MVP. Reduce this slide idea to the smallest student-facing text: intentional photo choices using angle, light, and distance.
74. Use the Response Pattern MVP. Decide whether a slide should have a full sentence, phrase, or single question.
75. Use the Response Pattern MVP. Recommend the maximum number of bullets for a photography lesson slide.
76. Use the Response Pattern MVP. Identify when teacher notes should hold detail instead of student-facing slide text.
77. Use the Response Pattern MVP. Rewrite a crowded slide into a simple image plus one question.
78. Use the Response Pattern MVP. Decide whether vocabulary should be defined on the slide or modeled in teacher talk.
79. Use the Response Pattern MVP. Recommend how much text belongs on a student task slide.
80. Use the Response Pattern MVP. Decide whether content density changes for kindergarten versus fifth grade.

### I. Artifact Routing And Production Safety

81. Use the Response Pattern MVP. I want to generate final student slides from cached lesson context. What must be verified first?
82. Use the Response Pattern MVP. Should a student-facing slide deck be stored in GitHub, Notion, or Google Drive?
83. Use the Response Pattern MVP. Decide whether a worksheet draft belongs in GitHub or Google Drive.
84. Use the Response Pattern MVP. Determine whether a teacher planning note should become a Notion handoff or a GitHub file.
85. Use the Response Pattern MVP. The user asks for a classroom artifact but has not approved a Google Drive folder. What should the response do?
86. Use the Response Pattern MVP. A lesson is blocked in Notion but the user asks to generate slides anyway. What should the agent do?
87. Use the Response Pattern MVP. A slide image source is not verified. What should the agent recommend?
88. Use the Response Pattern MVP. A source says production authorized but the cached index is stale. What should the agent do?
89. Use the Response Pattern MVP. Explain why a response can plan a deck but not create final student-facing materials without approval.
90. Use the Response Pattern MVP. Identify the safest next action when source authority, readiness, and image rights are unclear.

### J. Response Pattern Behavior And Iteration

91. Use the Response Pattern MVP. This answer needs to be shorter. Decide which module should be removed first.
92. Use the Response Pattern MVP. This answer needs more source trust. Decide whether to add Source Context or Deep Research.
93. Use the Response Pattern MVP. This answer gave too many options. Revise the pattern choice.
94. Use the Response Pattern MVP. This answer was too thin for a Notion-grounded lesson decision. What module is missing?
95. Use the Response Pattern MVP. Decide whether this task should use Quick Decision or Lesson Design.
96. Use the Response Pattern MVP. Decide whether this task should use Deep Research or Review Report.
97. Use the Response Pattern MVP. Decide whether this task should include a feedback note.
98. Use the Response Pattern MVP. Capture feedback after a response that was too long but accurate.
99. Use the Response Pattern MVP. Capture feedback after a response that was short but missed source context.
100. Use the Response Pattern MVP. Recommend whether this candidate prompt should become a formal smoke test, stay in the prompt bank, or be removed.

## Run Record

```text
Date:
Tester:
Branch or PR:
Prompt numbers sampled:
Patterns tested:
Source Context cases tested:
Pass count:
Fail count:
Blocked count:
Issues created or updated:
Candidate prompts to promote into smoke tests:
Candidate prompts to remove:
Next recommendation:
```
