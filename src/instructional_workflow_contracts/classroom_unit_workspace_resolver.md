# Classroom Unit Workspace Resolver

`classroom-unit-workspace-resolution-v1` verifies the exact Drive folder identities already recorded by `classroom-unit-workspace-v1` against injected current metadata.

The resolver is intentionally read-only and connector-neutral. Its `FolderMetadataReader` protocol accepts exact folder IDs only. It performs no folder-name search and no Drive, Notion, or network calls itself.

## Currentness

A cached `resolved`, `unverified`, or `stale` workspace binding is not current merely because its ID is present. The resolver asks the injected reader for that exact ID and verifies that it is accessible, not trashed, is a Google Drive folder, and—where applicable—still has the expected unit-root parent.

Renames are presentation changes: a different current display name does not cause drift when exact identity and structure remain valid. A child folder moved to another parent is reported as structural drift rather than silently accepted or replaced by a same-name sibling.

Roles intentionally marked `missing` are not searched by name and remain lazy/unresolved. Contradictory exact-ID metadata becomes bounded manual review.

## Authority

Resolver results grant no execution, external-write, approval, classroom-readiness, publication, or production authority. They do not create, move, rename, delete, share, or provision Drive content.

A later separately governed CW-DRIVE3 operations/provisioner layer may consume current resolver evidence before any external mutation. That later layer must retain its own write authorization and readback requirements.
