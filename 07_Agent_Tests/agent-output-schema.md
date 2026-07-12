# Agent Output Schema

All agent responses to governance-gated tasks must include a machine-checkable output schema to enable self-verification of compliance.

## Required Output Keys

Every agent response must include these keys in a clearly marked "Output Summary" section:

```json
{
  "status": "pass|fail|blocked|deferred",
  "blockers": ["list", "of", "blocking", "conditions"],
  "checks_passed": ["what", "passed"],
  "checks_failed": ["what", "failed"],
  "next_owner": "Agent Name",
  "handoff_artifacts": ["link1", "link2"],
  "files_changed": ["file1", "file2"],
  "tests_run": "Test count and summary"
}
```

## Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | enum | Yes | Final outcome: `pass` (all checks), `fail` (fixable issue), `blocked` (stop condition triggered), `deferred` (handed off) |
| `blockers` | array | Yes | List of stop conditions or approval gates blocking execution (empty if none) |
| `checks_passed` | array | Yes | Which governance checks passed (governance rule compliance, stop condition checks, etc.) |
| `checks_failed` | array | Yes | Which governance checks failed (empty if all passed) |
| `next_owner` | string | Yes | Name of agent or human who handles next step; "None" if work is complete |
| `handoff_artifacts` | array | Yes | Links, file paths, or records to pass to next owner (empty if none) |
| `files_changed` | array | Yes | List of files modified by this work (empty if read-only) |
| `tests_run` | string | Yes | Summary of tests executed (e.g., "8 unit tests passed, 0 failed"; "N/A" if no tests) |

## Status Values

- **pass**: All governance checks passed, work complete, no handoff needed
- **fail**: Work cannot proceed due to fixable issue (e.g., invalid input, test failure)
- **blocked**: Stop condition triggered (ambiguous target, missing authorization, etc.) — human review required
- **deferred**: Work handed off to next owner — includes `next_owner` and `handoff_artifacts`

## Usage Example

### Example 1: Pass (Work Complete)

```
## Output Summary

{
  "status": "pass",
  "blockers": [],
  "checks_passed": [
    "Inherited standards verified",
    "Owned systems confirmed",
    "No writes to blocked surfaces",
    "No stop conditions triggered",
    "Final report format included"
  ],
  "checks_failed": [],
  "next_owner": "None",
  "handoff_artifacts": [],
  "files_changed": ["src/models.py", "tests/test_models.py"],
  "tests_run": "12 unit tests passed, 3 integration tests passed"
}
```

### Example 2: Blocked (Stop Condition Triggered)

```
## Output Summary

{
  "status": "blocked",
  "blockers": ["ambiguous_target"],
  "checks_passed": [
    "Inherited standards verified",
    "Owned systems confirmed"
  ],
  "checks_failed": [
    "Stop Condition: Ambiguous target detected"
  ],
  "next_owner": "Human reviewer",
  "handoff_artifacts": ["task_context.md"],
  "files_changed": [],
  "tests_run": "N/A - blocked before execution"
}
```

### Example 3: Deferred (Handoff)

```
## Output Summary

{
  "status": "deferred",
  "blockers": [],
  "checks_passed": [
    "Unit tests passed",
    "Handoff conditions met"
  ],
  "checks_failed": [],
  "next_owner": "Integration Manager",
  "handoff_artifacts": [
    "generated_files/dashboards/",
    "DEPLOYMENT_CHECKLIST.md"
  ],
  "files_changed": ["src/generators/dashboard.py"],
  "tests_run": "15 unit tests passed, 5 integration tests passed"
}
```

## Integration with Test Files

All test files in `07_Agent_Tests/<overlay>.tests.md` should reference this schema and validate that agent responses include all required keys.

**Update to test expectations:**

Old (natural language):
```
Expect: Reports files changed, tests run, docs updated, Notion updates
recommended, and memory recommendations, plus links to the generated
files and which template IDs were used.
```

New (schema-based):
```
Expect: Output Summary with schema keys:
- status: "pass"
- files_changed: [list of created/modified files]
- tests_run: [summary of tests]
- handoff_artifacts: [links and template IDs]
```

## Validation Rules

1. Every response must include an "Output Summary" section
2. Output Summary must contain valid JSON conforming to the schema
3. All required keys must be present (no omissions)
4. Array fields must be arrays, even if empty `[]`
5. Status must be one of: `pass`, `fail`, `blocked`, `deferred`
6. If status is `deferred`, `next_owner` must not be "None"
7. If status is `blocked`, `blockers` array must not be empty

## Benefits

- **Machine-checkable**: Agents can validate their own output programmatically
- **Consistent**: All agents use the same schema, enabling cross-agent validation
- **Complete**: Required fields prevent incomplete handoffs
- **Traceable**: Detailed logging of what passed/failed for audit trail
- **Extensible**: Schema can evolve with governance rules
