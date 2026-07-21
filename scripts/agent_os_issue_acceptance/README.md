# Agent OS Issue Automation

Pure-local contracts, evidence models, scanners, planners, handoffs, approvals, and reports used by Agent OS issue automation.

## Local acceptance usage

```bash
python -m scripts.agent_os_issue_acceptance.cli \
  --issue tests/agent_os_issue_acceptance/fixtures/issue_valid.md \
  --pr-body tests/agent_os_issue_acceptance/fixtures/pr_body_valid.md \
  --changed-files tests/agent_os_issue_acceptance/fixtures/changed_files_valid.txt \
  --diff tests/agent_os_issue_acceptance/fixtures/diff_clean.patch
```

Use `--format json` for stable machine-readable report fields.

## Canonical domains

| Domain | Canonical modules |
|---|---|
| IssuePlan scanning and compatibility projection | `issueplan_scanner.py`, `parse_issue.py` |
| Acceptance and readiness evidence | `policy.py`, `readiness.py`, `models.py`, `report.py` |
| Connected issue retrieval and pagination evidence | `issue_scanner.py`, `github_issue_source.py` |
| Batch graph, conflict checks, extensions, and planning | `batch_graph.py`, `batch_checks.py`, `batch_extensions.py`, `batch_planning.py`, related check modules |
| Scheduler planning-handoff contracts | `scheduler_handoff.py` |
| IssuePlan current-state evidence | `issueplan_current_state.py` |
| Approval records and approved-execution projection | `approval_records.py`, `approved_execution_projection.py` |
| Sprint governance and reporting | `sprint_dashboard.py` |

This map documents the current package; it does not create new APIs or authorize a physical split.

## Permitted dependency direction

```text
IssuePlan scanner -> acceptance/readiness and current-state evidence
acceptance primitives -> batch graph/planning -> Scheduler handoff
current-state + handoff + repository evidence -> approvals -> execution projection
Sprint reporting -> supplied immutable evidence only
Workflow Scheduler runtime -> stable public contracts only
```

Production modules must not reverse these directions. Scanner or retrieval code must not import planning, approval, projection, reporting, or Workflow Scheduler runtime code. Acceptance and readiness code must not import planning or Scheduler contracts. Planning must not create Scheduler tasks or execution state. Reporting must not mutate readiness, planning, approvals, Scheduler state, or canonical evidence. Compatibility code must not become a second parser or authority.

## Canonical IssuePlan scanning

`issueplan_scanner.py` is the only acceptance-block candidate discovery and YAML parsing implementation. It preserves source identity, revision, multiplicity, malformed candidates, unknown governed fields, profile compatibility, and identity findings.

`parse_issue_metadata()` is a temporary lossy compatibility facade. It calls the canonical scanner and contains no parser of its own. Removal requires a separately governed API migration after all callers consume scanner results directly.

Scanner validity, readiness, labels, and approvals never authorize execution.

## Linked-issue parsing

A linked issue resolves only when exactly one unique same-repository target is introduced by a supported closing keyword: `close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, or `resolved`. Optional colon and whitespace forms are supported.

Bare references and `Addresses #...` are non-authoritative. Fenced code, inline code, blockquotes, and HTML comments are masked. Critical consumers use `parse_linked_issue_result()`; `parse_linked_issue()` remains a lossy wrapper.

## Public-interface policy

Existing package exports remain supported until a separately governed compatibility migration proves removal safe. New interfaces use direct-module imports by default.

A package-level re-export requires all of:

- intentional stability;
- a verified operational consumer;
- focused tests;
- owner evidence;
- compatibility guidance;
- a registry-impact decision when applicable.

Facade growth is not justified by convenience alone. Private helpers and speculative interfaces remain internal.

## Physical-split threshold

A later package split requires current evidence of at least one of: circular dependency pressure, conflicting ownership, incompatible release requirements, repeated unrelated facade changes, inability to test or distribute a domain independently, or independently versioned operational consumers. Directory size or visual cleanliness is not sufficient.

## Metadata and issue scanning

`metadata_validation.py` evaluates MD2A fixture evidence offline and report-only. It never edits issues, labels, readiness fields, workflows, or external systems.

`issue_scanner.py` converts complete paginated retrieval into provenance-preserving records. `issue_scan_cli.py` provides an explicit local GitHub runner:

```bash
python -m scripts.agent_os_issue_acceptance.issue_scan_cli --repository OWNER/REPO
```

Incomplete retrieval exits nonzero. The runner performs no issue or label writes.

## Informational reuse evidence (optional adapter)

- `reuse_readiness.py` (RC5B / #470 under the #248 contract) attaches caller-supplied RC3 `DiscoveryResult` and corrected-RC4 `ValidationReport` evidence to a `ReadinessResult` as a strictly informational layer. Informational evidence never changes `ReadinessOutcome`, `overall_status`, ordinary checks, blockers, ordinary manual-review items, or `exit_code_for()`; it is carried only in `AcceptanceReport.informational_checks`, rendered in a separate section that is omitted when empty (legacy output stays byte-for-byte identical). Provenance is compared using caller-supplied `RegistryProvenance` values only (strict, version-aware); missing, mismatched, unsupported, failing, contradicted, conflicting, or malformed evidence suppresses positive reuse guidance while leaving base readiness unchanged.
- It is the sole cross-package boundary, never reads the registry or invokes `RegistryReader`/discovery/validation orchestration, and is not exported from `__init__.py`; `readiness.py` stays independent, so base readiness imports and runs without the reusable-capability package installed. No reuse evidence authorizes implementation, writes, readiness changes, or merge, and the adapter performs no registry, issue, label, readiness, workflow, Scheduler, credential, production, or external mutation.

## Workflow and write boundary

Metadata validation and scanning remain offline and report-only. Connected retrieval consumes caller-supplied readers and preserves provenance. The package does not authorize issue, label, readiness, workflow, Scheduler, credential, production, or external-system writes.

Outcome meaning remains governed by `01_Shared_Standards/github/issue-acceptance-automation.md`. Package boundaries and facade decisions are governed by issue #464 and the applicable Agent OS governance standards.
