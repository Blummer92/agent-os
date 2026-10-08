# Vulture advisory dead-code scan (#3361)

Vulture reports possible unused Python symbols; its output is evidence for human review, **not deletion authority**. Run from the repository root after installing `requirements-dev.txt`:

```bash
python -m vulture scripts/agent_os_issue_acceptance --min-confidence 80
```

The initial bounded scope is `scripts/agent_os_issue_acceptance` only. Do not infer that symbols are unused in other repository packages, CLI entry points, dynamic imports, decorators, plugin registrations, serialization, or reflection. Investigate every candidate against current callers and tests before any separate removal proposal. A nonzero Vulture exit code means candidates were found, not that CI failed. This command is intentionally advisory and is not added as a blocking aggregate check or separate GitHub Actions workflow. No broad whitelist is configured.

The initial findings count and confidence/category breakdown require execution on a capable checkout and must not be claimed from static configuration alone. Expand scope only with separately reviewed evidence and narrow documented false-positive handling.

## Initial baseline (2026-10-08)

Executed on main `2c262c2a` with Vulture 2.16 (`vulture>=2.14,<3` from `requirements-dev.txt`):

* `python -m vulture scripts/agent_os_issue_acceptance --min-confidence 80` — **exit 0, zero findings.**
* `python -m vulture scripts/agent_os_issue_acceptance` (default min-confidence 60) — **exit 3, 141 candidates, all at 60% confidence** (Vulture's floor for "no static caller seen"; not a calibrated probability).

Scope: 68 Python files, ~21k executable lines. Every candidate is classified in `~/workspace/issue-3361-vulture/findings-classification.md` (repository files only; evidence directory, not shipped). Nothing is deleted, suppressed, or blocked on these findings under #3361.
