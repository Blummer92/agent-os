# Agent OS Shadow Navigation action

This local composite action wraps the existing `scripts/agent-os-shadow-run.py`
production caller. It does not introduce another selector, scheduler, queue, or
routing vocabulary.

## Safety boundary

The action is read-only. The caller must provide a workflow token with read-only
repository permissions. The underlying shadow runner records zero-mutation
evidence in every report and keeps `execution_authorized=false` and
`side_effects_performed=false`.

This action may observe, rank, explain, and emit evidence. It does not authorize
issue execution, comments, labels, branches, pull-request changes, merges,
closures, or any external-system write.

## Inputs

- `repository` — repository in `owner/name` form.
- `campaign_id` — required shadow experiment identifier.
- `candidates` — optional comma-separated deterministic narrowing set.
- `narrowing_criterion` — required when `candidates` is supplied.
- `explicit_order` — optional explicit request order inside the candidate set.
- `mission_id` — optional finite-mission evidence-ledger identifier.

The output `report_path` points to the generated JSON experiment record.

## Scanner advisory evidence (#3429, record-only)

The CLI accepts a repeatable `--scanner-evidence PATH` flag, one advisory
producer JSON per flag (`jscpd-advisory.json` from #3688 or
`pyan3-advisory.json` from #3689). Artifacts are loaded **after selection
has returned** and rendered as an additive §14 `scanner_advisory` section in
the experiment record. Absent flags mean the section is `None`.

Provenance is preserved verbatim per source: tool, schema, version, head
SHA, scope, candidate count, and truncation flags. Each finding carries
`selection_input: false`, and the section carries
`execution_authorized: false` and `side_effects_performed: false`.

Section states, in precedence order:

- `ok` — successful scan, head SHA equals the run's live source revision.
- `ok-zero-findings` — successful scan with no findings; distinct from
  failure and from absence.
- `stale` — head SHA differs from the run's source revision; findings are
  kept but marked stale and must never be cited as current.
- `scanner-error` — unsupported schema/tool, malformed content, or a
  producer `status` other than `ok`; no findings are reported.
- `unavailable` — the artifact file is missing; the run still succeeds,
  because the flag is advisory by design.

Findings are advisory engineering context, never authority:

- jscpd clones are textual similarity only, not semantic equivalence.
- pyan3 candidates have no resolved static caller in scope, which is not
  proof of runtime unreachability; check tests, `__all__`, decorators,
  workflow YAML, and MCP registrations before any deletion judgment.
- A finding whose file lies outside the producer's declared scope is
  annotated `out_of_scope: true` (for example, Notion packages are not
  covered by either producer) — that means "not scanned," never "no
  duplication."

The section is never supplied to the selector, the candidate-evidence
reader, or the evidence-ledger inputs digest, and it never changes a
selection outcome or reason code. Candidate population completeness and
fail-closed selection are unchanged: missing `primary_claims` or
`approval_applicability` still fail closed with their named reasons.
Reviewed deletion or consolidation candidates go to the existing #1729
Wire-or-Retire audit; this section does not authorize, perform, or
recommend any deletion by itself.

The repository workflow `.github/workflows/agent-os-shadow-navigation.yml`
provides the installable manual GitHub Actions entry point and publishes both a
job summary and a retained JSON artifact.
