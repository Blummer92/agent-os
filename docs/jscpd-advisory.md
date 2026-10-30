# jscpd advisory duplicate-code scan (#3688)

This tool identifies **textual clone candidates**, not redundant governance decisions or safe-to-delete code. It creates no authority to change code, issue status, or merge/closure state.

Run from the repository root with Node.js/npm installed:

```bash
python -m scripts.jscpd_advisory --output tmp/jscpd-advisory
```

The runner invokes pinned `jscpd@4.0.5` through `npx --yes` and scans only `scripts/agent_os_issue_acceptance` and `08_Tooling/agent-os-execution-service/src`. Generated build files, caches, node_modules, tests, and fixtures are excluded. Independent QA verified `jscpd@4.0.5` against the npm registry on 2026-10-21 and confirmed that the actual pinned binary returns version `4.0.5`. Reverify version and integrity before changing the pin.

Outputs are `jscpd-advisory.json` and `jscpd-advisory.md`, including the git head SHA, version, scan scope, status, candidate count and first 100 clone records. The raw JSON report remains in the output's `raw/` directory. Findings and scanner errors do **not** change the command's exit status; inspect `status` to distinguish a clean scan from a failed scan. A missing or stale SHA must not be treated as authoritative.

A clone is not proof of equivalent behavior. Review production callers, dynamic entrypoints, and invariants before sending a candidate to the existing #1729 Wire-or-Retire audit. The #2502 retirement gate still applies.

The owner separately authorized the workflow integration for #3688 on 2026-10-21. The existing `.github/workflows/agent-os-validation.yml` invokes this same command in an isolated `jscpd-advisory` pull-request job with read-only `contents` permission and a seven-day artifact. No required check or existing aggregate dependency was modified. A green job alone does not establish scanner success: inspect the JSON artifact's `status` field.
