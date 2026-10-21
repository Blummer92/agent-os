# jscpd advisory duplicate-code scan (#3688)

This tool identifies **textual clone candidates**, not redundant governance decisions or safe-to-delete code. It creates no authority to change code, issue status, or merge/closure state.

Run from the repository root with Node.js/npm installed:

```bash
python -m scripts.jscpd_advisory --output tmp/jscpd-advisory
```

The runner invokes pinned `jscpd@4.0.5` through `npx --yes` and scans only `scripts/agent_os_issue_acceptance` and `08_Tooling/agent-os-execution-service/src`. Generated build files, caches, node_modules, tests, and fixtures are excluded. The exact version requires validation against the npm registry in a network-capable runner before adoption.

Outputs are `jscpd-advisory.json` and `jscpd-advisory.md`, including the git head SHA, version, scan scope, status, candidate count and first 100 clone records. The raw JSON report remains in the output's `raw/` directory. Findings and scanner errors do **not** change the command's exit status; inspect `status` to distinguish a clean scan from a failed scan. A missing or stale SHA must not be treated as authoritative.

A clone is not proof of equivalent behavior. Review production callers, dynamic entrypoints, and invariants before sending a candidate to the existing #1729 Wire-or-Retire audit. The #2502 retirement gate still applies.

The workflow integration is **not yet authorized**. CI should invoke the same command in an existing report-only step and upload its outputs, with no required check, new permissions, or independent scheduler.
