# Worksheet Generation Context Packet

Purpose: provide only the approved context needed for a worksheet, guided notes,
handout, or exit ticket.

## Packet

- `source_of_truth`: Approved lesson/modeling handoff, Drive template source, and evidence source named by the task.
- `owner`: Instructional Materials Coach.
- `source_fields`:
  - learning objective
  - student task
  - evidence target
  - directions
  - response format
  - sentence frames
  - approved rubric language
  - approved template
  - target Drive folder
- `cache_scope`: Current worksheet or material generation task.
- `refresh_trigger`: Evidence target, task, template, or folder changes.
- `invalidation_trigger`: Missing evidence, revised task, template replacement, or target folder change.
- `live_verification_required`: Drive write, production artifact creation, or sharing/permission change.
- `blocked_write_surfaces`: Template masters, files outside confirmed folder, governed fields, and GitHub files.
- `next_owner`: QA / Test Agent.

## Notes

Use this packet only after required generation gates are satisfied or when
creating a draft/spec that does not write externally.
