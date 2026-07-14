# Context Packet Templates

Use these templates to pass the smallest approved context between Agent OS
owners without reloading full source history.

These packets are not source-of-truth records. They summarize where context came
from, who owns it, when it must refresh, and when live verification is required.

## Required Fields

Every packet includes:

- `source_of_truth`
- `owner`
- `source_fields`
- `cache_scope`
- `refresh_trigger`
- `invalidation_trigger`
- `live_verification_required`
- `blocked_write_surfaces`
- `next_owner`

## Safety Rules

- Cached context never authorizes writes.
- Use live verification before writes, readiness/status changes, governed-field
  changes, source-of-truth decisions, sharing changes, or production actions.
- Reference governance and standards instead of duplicating policy text.
- Keep packets narrow enough for the next owner to act without reloading full
  unit, lesson, repository, or workspace history.

## Templates

- `lesson-planning-context-packet.md`
- `teacher-modeling-context-packet.md`
- `slide-generation-context-packet.md`
- `worksheet-generation-context-packet.md`
- `classroom-production-context-packet.md`
- `github-implementation-context-packet.md`
- `notion-synchronization-context-packet.md`
