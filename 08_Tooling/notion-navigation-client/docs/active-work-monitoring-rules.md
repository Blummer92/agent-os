# Active-Work Monitoring Rules

Use these rules when an agent is asked to create, review, or maintain a monitoring surface for current work in Notion. This is navigation and design guidance only; it does not authorize Notion writes or duplicate owner records.

## Purpose

Keep active work visible without creating a second owner database.

## Required fields for a lightweight summary surface

- Work item title.
- Owner.
- Routing status.
- Source-of-truth link.

## Rules

- Prefer linked views, rollups, synced references, or other reference-style surfaces over copied records.
- Keep the monitoring surface read-only unless the user explicitly asks for a different design and the underlying setup supports it.
- Do not duplicate owner database records just to show active work in another place.
- If direct row querying is limited, document the limitation and recommend the lightest non-duplicative workaround.
- Preserve a direct pointer back to the canonical source record whenever possible.

## Review checklist

- The surface has a clear owner or steward.
- Every active item points back to a canonical source record.
- Summary fields do not redefine owner decisions.
- Copied records are avoided unless a governed exception exists.
- Limitations and missing direct-query access are named rather than hidden.
