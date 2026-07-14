# Classroom Production Context Packet

Purpose: bundle approved lesson and material context for production-ready
classroom output.

## Packet

- `source_of_truth`: Approved lesson, approved template source, confirmed Drive target, and approved asset source.
- `owner`: Instructional Materials Coach.
- `source_fields`:
  - approved lesson
  - output type
  - approved template
  - target Drive folder
  - naming convention
  - approved assets
  - QA status
  - remaining risks
- `cache_scope`: Current production request.
- `refresh_trigger`: Lesson approval, template, target folder, QA result, or asset status changes.
- `invalidation_trigger`: Failed production gate, changed approval, moved folder, changed asset permission, or failed QA.
- `live_verification_required`: Drive output, production status, sharing/permissions, or governed fields.
- `blocked_write_surfaces`: GitHub unless explicitly approved, template masters, sharing/permissions, and production status fields.
- `next_owner`: QA / Test Agent or Integration Manager.

## Notes

Student-facing classroom artifacts default to confirmed Drive folders. Repository
storage requires explicit approval and a GitHub Change Request.
