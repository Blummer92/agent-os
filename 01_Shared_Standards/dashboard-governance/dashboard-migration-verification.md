# Dashboard Migration Verification Standard

## Purpose

Use this standard when reviewing dashboard consolidation, retirement, schema cleanup,
or dashboard-to-dashboard migration proposals.

This standard is verification-only. It helps agents collect evidence, build dependency
coverage, classify risk, and produce handoff reports before any governed dashboard
change is approved.

## Source-of-Truth Rule

Local snapshots, dependency graphs, and validation outputs are evidence aids. They are
not the source of truth for Notion, Google Sheets, Drive, Apps Script, or other live
workspace systems.

Before any governed write, retirement, readiness change, status change, permission
change, schema change, or production migration, verify the live system of record and
obtain explicit approval.

## Safety Boundary

The verification toolkit must not:

- archive, delete, rename, merge, or update Notion data
- mutate Google Sheets, Drive, Docs, Apps Script, Gmail, Calendar, or production files
- create triggers, deployments, sharing changes, or permission changes
- treat placeholder snapshots as proof
- treat missing evidence as neutral evidence
- approve destructive changes while dependencies remain unknown

## Evidence Quality

Use these evidence statuses:

- `verified`: locally captured and currently trustworthy
- `inferred`: derived from partial evidence and not sufficient for retirement approval
- `stale`: previously captured but needs refresh
- `missing`: not yet captured
- `contradictory`: conflicting local evidence exists

Placeholder snapshots are scaffolding only. They are never verified evidence.

## Classification Rule

If evidence is incomplete, stale, missing, uncertain, placeholder-only, or
contradictory, classify the proposal as one of:

- `Requires manual review`
- `Blocked by missing information`

Do not classify destructive retirement, archive, merge, dependency cleanup, or schema
removal as safe while unique records, templates, buttons, automations, permissions,
synced databases, documentation references, formulas, rollups, relations, or active
workflows remain unknown.

## Required Report Sections

Human-readable validation reports must preserve these sections:

1. Executive Summary
2. Migration Readiness Table
3. Data Integrity Review
4. Dependency Review
5. Migration Tasks
6. Retirement Order
7. Items That Must Not Be Retired
8. Final Decision

Final Decision must be exactly one of:

- `Ready for Retirement`
- `Ready After Migration`
- `Do Not Retire Yet`

## Ownership

Primary owner: Modeling & Dashboard Governance Agent.

Support:

- QA / Test Agent for validation evidence and pass/fail reporting
- Google Workspace Automation Engineer for Workspace automation boundaries only
- GitHub Service Agent for repository implementation and pull requests

## Version

0.1.0
