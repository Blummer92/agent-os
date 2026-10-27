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
- `scanner_evidence_jscpd` and `scanner_evidence_pyan3` — optional
  filesystem paths to existing producer JSON artifacts. The workflow supplies
  these automatically from the same checked-out revision.

The output `report_path` points to the generated JSON experiment record.

## Scanner advisory evidence (#3429, record-only)

The workflow runs the existing pinned jscpd (#3688) and pyan3 (#3689)
producers against its checked-out Git revision, then passes both generated
JSON paths to the composite action and the existing CLI. This avoids
cross-workflow PR-head artifacts, expiry-dependent supply, and extra storage.
A failure to install or start a scanner becomes `unavailable`; a producer's
own non-`ok` status becomes `scanner-error`. The CLI verifies artifact SHA
against the live main revision, preserving `stale` if main changes during the run.

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
Potential retirement candidates may be proposed to #1729 for owner review;
no #1729 scanner intake is established or implied. This section does not
authorize, perform, or recommend deletion.

## Actual GSA / QA review handoff

For each real shadow run, open the existing Actions job summary's **Scanner
advisory** table and the uploaded `shadow-navigation-report.json` artifact
in the same run (seven-day retention). Record the run URL, checkout SHA,
each source's `head_sha`, `status`, `state`, candidate and loaded counts,
truncation, scope, and any errors in the existing GSA implementation or
QA review packet. QA must compare these against the saved §14 JSON rather
than inferring success from a green workflow conclusion. An absent or stale
source cannot be cited as current. GSA may review file/line pointers as
engineering hypotheses, not as deletion approvals. This is the prescribed
review procedure; actual consumption is not proven until a reviewer retrieves
and cites a real run.

## Grouped engineering review pointers

The experiment record's §14 `scanner_advisory.review_groups` is a
**read-only engineering review index**. It groups findings only when their
repository-relative file and line ranges actually overlap and their source
revisions and currentness states match. Groups retain references to every
original `sources[source_index].findings[finding_index]` entry: no scanner
evidence is discarded or used to change issue selection or the ledger.
Different files, non-overlapping lines, or different revisions stay separate.
An unavailable or failed scanner produces no invented findings.

Each review group contains a stable run-local `review_id`, location spans,
source SHA/currentness, truncation and scope flags, and an `issue_linkage`
disposition. Raw scanner evidence **cannot prove canonical issue identity**;
groups therefore remain `unlinked` with `issue_number: null` until an
independent authorized issue-identity source establishes otherwise.
Do not infer a verified link from a matching path, function name, or a
GitHub PR closing-reference parser. No `verified` or `ambiguous` issue
association is claimed by this record-only implementation.

**GSA/QA review procedure:** Download the run's JSON report and inspect
`scanner_advisory.review_groups`. For one group, follow each `finding_refs`
index to the original source finding, check the actual source code and its
public/dynamic registrations, and record in the existing implementation/QA
packet the run URL, SHA, group ID, source finding pointers, reuse/extend/
investigate/reject judgment, and rationale. Mark stale, truncated,
out-of-scope, or unlinked findings as requiring manual review. No review
decision is automatically published or consumed by an execution engine.
Retirement candidates require the independent #1729/#2502 process.


The repository workflow `.github/workflows/agent-os-shadow-navigation.yml`
provides the installable manual GitHub Actions entry point and publishes both a
job summary and a retained JSON artifact.
