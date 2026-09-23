# Notion Record Update Safety

This standard names Notion write modes. Authorization remains owned by
`00_Governance/write-authorization-policy.md`; a mode never creates authority.

## Write Modes

### Draft Mode

Default when live-write scope is absent or incomplete. Produce local or copy-ready
content only and perform no live Notion mutation.

### Append-Only Safe Log Mode

May be used only when the applicable authorization policy separately authorizes the exact database and record class. Before each
write, verify all of the following are current and unambiguous:

- exact approved database identity and schema identity;
- database owner approval for the database and record class;
- create-new-record-only behavior with no update or deletion path;
- governed and prohibited fields are excluded;
- a visible `agent-generated` or `needs review` marker;
- a deterministic duplicate/idempotency key;
- bounded audit identity/evidence; and
- a disable or rollback path.

Missing, stale, ambiguous, contradictory, unsupported, or incomplete evidence
fails closed to Draft Mode or manual review. Ambiguous relation targets never
justify creating a related record.

### Canonical Update Mode

Updating an existing source-of-truth record requires explicit approval, exact
target, owner, field map, governed-field authorization when applicable, audit
evidence, and rollback plan. Append-Only Safe Log Mode cannot substitute for a
canonical update.

## Safety Boundary

Technical access, mode classification, readiness, or validation never authorizes a
write. Apply stricter agent overlays and shared standards when they block a write
that this standard describes.

## Version
0.2.0
