# RC6 Technical Pilot Runner

This package implements issue #500 as a deterministic, offline orchestration layer for the frozen RC6-TF v1.0 package from issue #499.

## Boundaries

- The frozen input is `tests/fixtures/rc6_technical_pilot/manifest.json` plus six ordered case-part files.
- The runner accepts only frozen SHA `ca980c38d74b8d3ab30ca67461a9f576281edc75`.
- RC3 discovery, RC4 validation, RC5 reuse evidence, readiness evaluation, and report rendering are imported from their existing implementations.
- The runner does not update GitHub, labels, issues, pull requests, registry records, readiness state, repository source files, Notion, Drive, Cloud Build, or production systems.
- Result artifacts are written only to the caller-provided output directory.
- A passing result is technical evidence only. It does not authorize implementation, repository writes, merge, deployment, or broader adoption.

## Validation-only preflight

Validation-only mode checks the package digest, exact T01-T24 order, required fields, frozen thresholds, and the tested checkout SHA without executing the package:

```bash
PYTHONPATH=08_Tooling/reusable-capability-registry/src \
python -m scripts.agent_os_rc6_technical_pilot.cli \
  --repository-root /path/to/frozen-checkout \
  --frozen-sha ca980c38d74b8d3ab30ca67461a9f576281edc75 \
  --validate-only
```

## Authorized manual execution

The `RC6 Technical Pilot` GitHub Actions workflow is `workflow_dispatch` only. It keeps the merged runner source separate from the exact frozen checkout, runs focused contract tests, executes T01-T24 twice, and uploads deterministic JSON and Markdown artifacts.

Do not dispatch the workflow until parent issue #249 separately authorizes technical pilot execution.
