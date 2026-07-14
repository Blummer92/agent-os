# Slide Generation Context Packet

Purpose: provide only the approved modeling and material context needed to create
or plan a slide deck.

## Packet

- `source_of_truth`: Approved modeling handoff, Drive template source, and approved asset source named by the task.
- `owner`: Instructional Materials Coach.
- `source_fields`:
  - lesson objective
  - approved modeling language
  - slide purpose
  - student-facing language
  - approved template
  - target Drive folder
  - approved visual assets
  - QA checklist rows
- `cache_scope`: Current slide deck generation task.
- `refresh_trigger`: Template, target folder, modeling, or asset changes.
- `invalidation_trigger`: Template replacement, folder move, asset approval/status change, or modeling update.
- `live_verification_required`: Drive write, template copy, sharing/permission decision, or production artifact creation.
- `blocked_write_surfaces`: Template masters, files outside confirmed target folder, sharing/permission settings, and GitHub.
- `next_owner`: QA / Test Agent.

## Notes

Use approved templates and assets before generating new equivalents. Verify the
Drive target before creating or copying files.
