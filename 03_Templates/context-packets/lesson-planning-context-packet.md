# Lesson Planning Context Packet

Purpose: carry minimum approved context from a teacher request into Unit Alignment
or curriculum planning without loading full unit history.

## Packet

- `source_of_truth`: Notion, Drive, or approved curriculum source named by the task.
- `owner`: Unit Alignment Agent or Agent Orchestrator.
- `source_fields`:
  - course
  - unit title
  - lesson title
  - learning objective
  - standards/objective map
  - assessment or evidence target
  - pacing
  - source confidence
  - unit readiness
  - blockers
- `cache_scope`: Current lesson or current unit planning session.
- `refresh_trigger`: Unit, lesson, standards, objective, pacing, or assessment changes.
- `invalidation_trigger`: Source confidence changes, unit readiness changes, active blocker, or objective changes.
- `live_verification_required`: Readiness, approval, source-of-truth, or production decisions.
- `blocked_write_surfaces`: Notion readiness/status fields, Drive files, GitHub repository files, and governed fields.
- `next_owner`: Teacher Modeling Coach or Instructional Materials Coach.

## Notes

Use this packet for planning handoffs only. It does not authorize writes or
production artifact generation.
