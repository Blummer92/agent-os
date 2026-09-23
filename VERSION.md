# Version

- Version: 0.1.1-draft
- Status: Draft canonical Agent OS standards and implementation baseline
- Scope: Governed repository source for Agent OS standards, overlays, registries,
  templates, tests, local tooling, and validation workflows.
- Implemented tooling: Workflow Scheduler, Workspace Automation Builder,
  Dashboard Migration Verification, Instructional Materials Coach,
  Notion Navigation Client, and Agent Memory local helpers are tracked in
  `04_Registry/module-version-map.md`.
- Validation: Repository validation is documented in `VALIDATION_REPORT.md` and
  runs through `./scripts/validate-all.sh` plus the self-hosted Agent OS
  Validation Gate.
- Live systems changed: none.
- Not supported: autonomous agents, issue-to-PR automation, production writes,
  live Google Drive writes, live Notion writes, governed-field updates,
  classroom artifact generation, or production deployment without separate
  explicit approval.
