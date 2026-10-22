# Pyan3 advisory call-graph scan (#3689)

This tool builds an **approximate static call graph** of the bounded scope to surface potentially disconnected governance code, redundant wrappers, and import cycles. It creates no authority to change code, issue status, or merge/closure state, and a statically unreferenced node is **never** proof that code is unreachable at runtime.

## Compatibility (verified 2026-10-21)

- Pyan3 **2.9.0** (PyPI, released 2026-10-06, Technologicat/pyan) is pinned. It declares Python `>=3.10,<3.16`, covering the validation workflow's Python 3.11 and local 3.12.
- Against the bounded scope below (140 files): every file parses, the analysis completes in about 9 seconds, and 696 of 714 source-evidenced intra-package direct calls (97.5%) resolve to graph edges. The remaining calls use patterns Pyan3 does not resolve (see Limitations).
- The runner refuses to analyze with any other Pyan3 version: a version mismatch is reported as `scanner-error` so report provenance stays exact.

## Run locally

With Python 3.11+ and the pinned tool installed (`pip install "pyan3==2.9.0"`), from the repository root:

```bash
python -m scripts.pyan3_advisory --output tmp/pyan3-advisory
```

The scan covers only `scripts/agent_os_issue_acceptance` and `08_Tooling/agent-os-execution-service/src`. Outputs are `pyan3-advisory.json` and `pyan3-advisory.md`, including the git head SHA, pinned version, scope, status, node/edge counts, unresolved-edge count and samples, import cycles, call cycles, test-only-referenced nodes, and the first 100 potentially disconnected candidates. The full normalized graph (defined modules, classes, functions, and methods with resolved edges) is in the output's `raw/pyan3-graph.json`, capped at 5,000 nodes / 10,000 edges with truncation flags. Findings and scanner errors do **not** change the command's exit status; inspect `status` to distinguish a completed scan from a failed one. A missing tool, a version mismatch, or an analysis exception is reported as `scanner-error`, never as a clean graph.

## Interpreting the graph

- A **resolved edge** means Pyan3 found a static call/use from one defined node to another. Direct calls and import aliases resolve reliably; the graph is still approximate.
- An **unresolved edge** is a call Pyan3 could not bind to a definition in scope: dynamic imports (`importlib.import_module`), attribute dispatch on objects of unknown type, builtins, and external-library calls all land here. A high unresolved count is expected and is itself the warning: those call sites are invisible to candidate analysis.
- **Import cycles** are computed from AST imports between in-scope modules, independently of Pyan3, and are exact for the analyzed files. They are static findings: a `TYPE_CHECKING`-only or function-level import can close a static cycle without creating a runtime import cycle (one such case exists in the execution service), so verify the import kind before treating a cycle as a runtime problem. **Call cycles** are strongly connected components of the resolved call graph (mutual recursion), reported separately.
- A **potentially disconnected candidate** is a defined function, method, or class with no incoming resolved edge from any analyzed caller, excluding modules, dunder methods, `main`, decorated definitions (possible plugin/registry entrypoints), and nodes referenced only from test files (reported separately as test-only referenced). Callers outside the bounded scope — other packages, scripts, the Apps Script/Node surfaces, MCP or plugin registration, and reflection — are not analyzed, so library-style code in the execution service will legitimately appear here.

## Limitations

Pyan3 is a static, approximate analyzer: it does not execute code, follow dynamic imports or `getattr` dispatch, resolve most attribute calls on instances, or see entrypoints invoked by frameworks, decorators, or external hosts. Never claim an unreferenced static node is safe to delete, and never use this report alone as deletion evidence.

One upstream quirk is normalized away: Pyan3 nondeterministically (hash order) can emit a bare, unnamespaced unresolved duplicate of a call it also resolved to a qualified node from the same caller. The runner drops exactly those duplicates (a bare name with no resolved counterpart from that caller stays unresolved), which makes the emitted reports deterministic across runs.

Review production callers, test callers, dynamic entrypoints, and invariants before sending a candidate to the existing #1729 Wire-or-Retire audit. The #2502 retirement gate still applies.

## CI status

Workflow integration is **not yet authorized**. Repository-only implementation is complete and locally reproducible; CI should later invoke this same command in the existing validation workflow as an isolated report-only job (read-only `contents` permission, seven-day artifact, no required check, no aggregate-gate dependency), mirroring the `jscpd-advisory` job added for #3688, pending the owner's separate workflow authorization.
