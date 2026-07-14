# Teacher Modeling Context Packet

Purpose: pass approved lesson-planning context into modeling work without
rechecking Unit Alignment or full unit history.

## Packet

- `source_of_truth`: Approved lesson-planning handoff or live planning source named by the task.
- `owner`: Teacher Modeling Coach.
- `source_fields`:
  - approved lesson objective
  - student task
  - think-aloud method
  - component breakdown
  - visual anchors
  - common misconceptions
  - student sentence frames
  - modeling readiness
- `cache_scope`: Current lesson modeling cycle.
- `refresh_trigger`: Lesson objective, student task, or modeling method changes.
- `invalidation_trigger`: Modeling readiness changes, lesson objective changes, or new misconception evidence.
- `live_verification_required`: Readiness/status updates or governed-field decisions.
- `blocked_write_surfaces`: Notion governed fields, Drive production files, and GitHub files.
- `next_owner`: Instructional Materials Coach.

## Notes

Use this packet to preserve approved modeling language, common errors, visual
anchors, and sentence frames for later material generation.
