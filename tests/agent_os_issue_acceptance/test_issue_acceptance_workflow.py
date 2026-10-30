from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-acceptance-report.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_report_only_acceptance_workflow_exists_and_calls_checker():
    content = _content()

    assert "Agent OS Issue Acceptance Report" in content
    assert "pull_request:" in content
    assert "workflow_dispatch:" in content
    assert "actions/checkout@v7" in content
    assert "./.github/actions/setup-python-dev" in content
    assert "python -m scripts.agent_os_issue_acceptance.cli" in content
    assert "GITHUB_STEP_SUMMARY" in content


def test_report_only_acceptance_workflow_uses_shared_environment_after_checkout():
    content = _content()

    checkout = content.index("uses: actions/checkout@v7")
    shared_setup = content.index("uses: ./.github/actions/setup-python-dev")
    assert checkout < shared_setup
    assert "uses: actions/setup-python@v6" not in content
    assert "python -m pip install -r requirements-dev.txt" not in content


def test_report_only_acceptance_workflow_uses_observed_at_and_file_based_transport_inputs():
    content = _content()

    assert "--transport-issue-body-file" in content
    assert "--transport-fresh-issue-body-file" in content
    assert "--transport-observed-at" in content
    assert "tmp/agent_os_issue_acceptance_report/issue_recheck.md" in content
    assert "gh issue view \"$linked_issue\" --json body" in content
    assert '> "$out/issue.md" || :' not in content


def test_report_only_acceptance_workflow_uses_read_permissions():
    content = _content()

    assert "contents: read" in content
    assert "issues: read" in content
    assert "pull-requests: read" in content

    forbidden = [
        "contents: " + "write",
        "issues: " + "write",
        "pull-requests: " + "write",
        "statuses: " + "write",
        "checks: " + "write",
        "actions: " + "write",
    ]
    for pattern in forbidden:
        assert pattern not in content


def test_report_only_acceptance_workflow_has_no_mutation_paths():
    content = _content()

    forbidden = [
        "gh issue " + "edit",
        "gh issue " + "close",
        "gh pr " + "edit",
        "gh pr " + "merge",
        "add-" + "label",
        "remove-" + "label",
        "set-" + "label",
        "github.rest.issues." + "addLabels",
        "github.rest.issues." + "removeLabel",
        "github.rest.issues." + "setLabels",
        "github.rest.issues." + "update",
        "github.rest.pulls." + "update",
        "branch-" + "protection",
        "updateBranch" + "Protection",
    ]
    for pattern in forbidden:
        assert pattern not in content


def test_report_only_acceptance_workflow_collects_local_fixtures():
    content = _content()

    assert "tmp/agent_os_issue_acceptance_report/issue.md" in content
    assert "tmp/agent_os_issue_acceptance_report/pr_body.md" in content
    assert "tmp/agent_os_issue_acceptance_report/changed_files.txt" in content
    assert "tmp/agent_os_issue_acceptance_report/diff.patch" in content
    assert "gh pr view" in content
    assert "gh issue view" in content
    assert "parse_linked_issue_result" in content
    # E4 (#3506, D3): fixtures are collected for the report-only issue
    # number, so unambiguous non-closing PRs are evaluated too — the
    # RESOLVED-only gate is gone.
    assert "report_only_issue_number" in content
    assert (
        "from scripts.agent_os_issue_acceptance.parse_pr import "
        "report_only_issue_number" in content
    )
    assert "LinkedIssueParseStatus.RESOLVED" not in content
    assert "from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue\n" not in content


def test_report_only_acceptance_workflow_bounds_issue_lookup_to_resolved_result():
    # Name retained for continuity; the behaviour it pins is now the
    # E4 (#3506, D3) report-only contract: the single lookup is bounded
    # by report_only_issue_number, which returns the RESOLVED issue, or
    # the single unambiguous declared non-closing target for report-only
    # evaluation, and nothing (empty -> manual-review) for ambiguous or
    # unresolvable associations. It never grants closure.
    content = _content()

    assert content.count("result = parse_linked_issue_result(") == 1
    assert content.count("report_only_issue_number(result)") == 1
    assert "number = report_only_issue_number(result)" in content
    assert "print(number or \"\")" in content
    assert "if result.status == LinkedIssueParseStatus.RESOLVED:" not in content
    assert "print(result.issue_number" not in content
    # E3 (#3506, D3): the checker step must expose the child result —
    # a `fail` report (checker exit 1) fails this non-required check
    # instead of being masked by an unconditional green `exit 0`.
    assert 'exit "$checker_exit_code"' in content
    acceptance_tail = content.split("checker_exit_code=${PIPESTATUS[0]}", 1)[1]
    assert "\n          exit 0\n" not in acceptance_tail.split("Publish report summary", 1)[0]
    assert 'printf \'%s\\n\' "$linked_issue" > "$out/linked_issue.txt"' in content
    assert 'linked_issue="$(cat tmp/agent_os_issue_acceptance_report/linked_issue.txt 2>/dev/null || true)"' in content
    assert 'if [ -n "$linked_issue" ]; then' in content
    assert 'gh issue view "$linked_issue"' in content


def test_report_only_acceptance_workflow_preserves_initial_issue_lookup_failure():
    content = _content()

    marker = 'issue_body_retrieval_failed.txt'
    initial_lookup = 'if ! gh issue view "$linked_issue" --json body --jq \' .body // ""\''
    assert marker in content
    assert "printf '%s\\n' false > \"$out/issue_body_retrieval_failed.txt\"" in content
    assert "printf '%s\\n' true > \"$out/issue_body_retrieval_failed.txt\"" in content
    assert 'issue_body_retrieval_failed="$(cat tmp/agent_os_issue_acceptance_report/issue_body_retrieval_failed.txt)"' in content
    assert "--transport-issue-body-retrieval-failed" in content
    assert initial_lookup.replace("' ", "'") in content


def test_report_only_acceptance_workflow_publishes_report_without_gating():
    content = _content()

    assert "set +e" in content
    assert "PIPESTATUS[0]" in content
    assert "checker_exit_code=" in content
    assert "exit 0" in content
    assert "Report-only boundary" in content


def test_report_only_acceptance_workflow_summary_runs_when_checker_fails():
    # NB-2 (#3506, follow-up to D3): the "Publish report summary" step
    # must run even when the checker step fails (E3), so the failing
    # report is rendered instead of the step being skipped. The checker
    # step itself is unchanged: its non-zero exit still determines the
    # job/check result, and no other step gains `if: always()`.
    import yaml

    content = _content()
    workflow = yaml.safe_load(content)
    steps = workflow["jobs"]["report"]["steps"]
    by_name = {step["name"]: step for step in steps}

    summary = by_name["Publish report summary"]
    assert summary.get("if") == "always()"
    assert content.count("if: always()") == 1

    checker = by_name["Run report-only issue acceptance checker"]
    assert "if" not in checker
    assert 'exit "$checker_exit_code"' in checker["run"]

    # The summary consumes the report file defensively: a missing report
    # (earlier step failed before the checker ran) degrades to an
    # explicit notice instead of failing the step and truncating the
    # summary; a partial report is rendered as-is.
    assert (
        "if [ -f tmp/agent_os_issue_acceptance_report/report.txt ]; then"
        in summary["run"]
    )
    assert "cat tmp/agent_os_issue_acceptance_report/report.txt" in summary["run"]
    assert "Report output unavailable" in summary["run"]
    assert "Report-only boundary" in summary["run"]


def test_report_only_acceptance_workflow_declares_pr_number_dispatch_input():
    content = _content()

    assert "pr_number:" in content
    assert "PR_NUMBER: ${{ github.event.pull_request.number || inputs.pr_number }}" in content


def test_report_only_acceptance_workflow_binds_transport_provenance():
    content = _content()

    assert "--transport-repository" in content
    assert "--transport-issue-number" in content
    assert "--transport-issue-body-file" in content
    assert "--transport-pr-head-sha" in content
    assert "--transport-evaluator-sha" in content
    assert "--transport-workflow-run-id" in content
    assert "--transport-workflow-run-attempt" in content
    assert "--transport-fresh-pr-head-sha" in content
    assert "--transport-issue-body-retrieval-failed" in content


def test_report_only_acceptance_workflow_uses_live_provenance_fetches():
    content = _content()

    assert "git rev-parse HEAD" in content
    assert "gh pr view \"$GITHUB_PR_NUMBER\" --json headRefOid" in content
    assert "gh issue view \"$linked_issue\" --json body --jq '.body // \"\"'" in content
    assert "--transport-fresh-issue-body-file \"$fresh_issue_body_file\"" in content
    assert "--transport-fresh-pr-head-sha \"$fresh_pr_head_sha\"" in content


def test_report_only_acceptance_workflow_routes_missing_pr_number_to_manual_review():
    content = _content()

    assert 'if [ -z "${PR_NUMBER:-}" ]; then' in content
    assert "Manual workflow dispatch did not provide a pull request number." in content
    assert (
        "This report-only workflow should route missing pull request context "
        "to manual review or fail according to IA2 semantics."
    ) in content


def test_report_only_acceptance_workflow_reconciles_changed_file_count():
    content = _content()

    assert 'gh pr view "$PR_NUMBER" --json changedFiles --jq \'.changedFiles\'' in content
    assert 'retrieved_changed_files="$(wc -l < "$out/changed_files.txt"' in content
    assert 'if [ "$retrieved_changed_files" != "$authoritative_changed_files" ]; then' in content
    assert 'printf \'%s\\n\' true > "$out/changed_files_incomplete.txt"' in content
    assert "--changed-files-incomplete" in content


def test_report_only_acceptance_workflow_records_diff_retrieval_failure():
    content = _content()

    assert 'gh pr diff "$PR_NUMBER" --patch > "$out/diff.patch" || true' not in content
    assert 'if ! gh pr diff "$PR_NUMBER" --patch > "$out/diff.patch"; then' in content
    assert 'printf \'%s\\n\' true > "$out/diff_retrieval_failed.txt"' in content
    assert "--diff-retrieval-failed" in content


def test_report_only_acceptance_workflow_enables_documentation_advisory_before_transport():
    content = _content()

    advisory = content.index("--documentation-advisory")
    transport = content.index('"${transport_args[@]}"')
    assert advisory < transport
    assert content.count("--documentation-advisory") == 1


def test_report_only_acceptance_workflow_binds_token_for_every_gh_step():
    """Each report step that calls gh must receive the existing scoped token."""
    import yaml

    workflow = yaml.safe_load(_content())
    steps = workflow["jobs"]["report"]["steps"]
    gh_steps = [step for step in steps if "gh " in step.get("run", "")]

    assert {step["name"] for step in gh_steps} == {
        "Build local acceptance fixtures from PR data",
        "Run report-only issue acceptance checker",
    }
    for step in gh_steps:
        assert step.get("env", {}).get("GH_TOKEN") == "${{ github.token }}"


# ---------------------------------------------------------------------------
# M14 regression coverage (#3506): failure masking via `continue-on-error`.
#
# Mutation M14 inserts `continue-on-error: true` into the Issue Acceptance
# workflow's checker job/step. That turns a failing checker (E3: a `fail`
# report exits 1 and must surface as a red, non-required check) back into
# a green check, silently undoing E3/NB-2 (live run 39785092963). Before
# these tests, both the step-level and job-level forms of the mutation
# passed the whole workflow test file undetected (18 passed). Exit-code
# propagation itself is already pinned by
# test_report_only_acceptance_workflow_bounds_issue_lookup_to_resolved_result
# and test_report_only_acceptance_workflow_summary_runs_when_checker_fails;
# the tests below pin the masking surfaces those tests do not cover.
# ---------------------------------------------------------------------------


def _m14_workflow():
    import yaml

    return yaml.safe_load(_content())


def _m14_is_masking_continue_on_error(step_or_job) -> bool:
    """True if a job/step dict carries a masking continue-on-error value.

    Absent key and an explicit false/no are not masking. The boolean
    ``True`` (YAML ``true``/``yes``), the strings ``"true"``/``"True"``,
    and any GitHub expression string (which can evaluate to true) are.
    """
    if "continue-on-error" not in step_or_job:
        return False
    value = step_or_job["continue-on-error"]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "no", "0", ""}
    return bool(value)


def test_m14_checker_job_and_step_do_not_continue_on_error():
    workflow = _m14_workflow()
    report_job = workflow["jobs"]["report"]

    # Job-level masking (`jobs.report.continue-on-error: true`).
    assert not _m14_is_masking_continue_on_error(report_job)

    # Step-level masking on the checker step itself.
    steps = {step["name"]: step for step in report_job["steps"]}
    checker = steps["Run report-only issue acceptance checker"]
    assert not _m14_is_masking_continue_on_error(checker)

    # Raw-text backstop: catches spellings the YAML value check could
    # normalise away (quoted strings, expressions) on the target job.
    content = _content()
    assert "continue-on-error: true" not in content
    assert "continue-on-error: 'true'" not in content
    assert 'continue-on-error: "true"' not in content


def test_m14_no_job_or_step_in_workflow_continues_on_error():
    # No alternate masking boundary: no job and no step anywhere in the
    # workflow may soften a failure with continue-on-error. In
    # particular the summary step must not gain it either — its
    # `if: always()` (NB-2) is only safe because a successful summary
    # cannot change the checker step's failed conclusion, which is
    # exactly what continue-on-error would break.
    workflow = _m14_workflow()

    for job_name, job in workflow["jobs"].items():
        assert not _m14_is_masking_continue_on_error(job), job_name
        for step in job.get("steps", []):
            assert not _m14_is_masking_continue_on_error(step), (
                job_name,
                step.get("name"),
            )


def test_m14_checker_invocation_is_not_masked_by_or_true_or_exit_zero():
    workflow = _m14_workflow()
    steps = {step["name"]: step for step in workflow["jobs"]["report"]["steps"]}
    checker_run = steps["Run report-only issue acceptance checker"]["run"]

    # The checker CLI pipeline itself must not be masked: no `|| true`,
    # `|| :`, or `|| exit 0` swallowing its status. (Scoped to the CLI
    # invocation segment: the unrelated `cat ... || true` for the
    # optional linked_issue.txt lookup elsewhere in the script does not
    # touch the checker's exit code and is not a masking boundary.)
    cli_segment = checker_run[
        checker_run.index("python -m scripts.agent_os_issue_acceptance.cli") :
        checker_run.index("checker_exit_code=")
    ]
    assert "||" not in cli_segment
    assert "continue-on-error" not in checker_run

    # Non-zero exit is preserved, not swallowed (complements the E3
    # assertions in the pre-existing tests referenced above): the
    # PIPESTATUS capture is taken and the final meaningful line of the
    # step re-raises exactly that code; there is no unconditional
    # `exit 0` line anywhere in the checker step.
    assert "checker_exit_code=${PIPESTATUS[0]}" in checker_run
    stripped_lines = [line.strip() for line in checker_run.splitlines()]
    assert "exit 0" not in stripped_lines
    meaningful = [
        line
        for line in stripped_lines
        if line and not line.startswith("#")
    ]
    assert meaningful[-1] == 'exit "$checker_exit_code"'


def test_m14_summary_always_does_not_mask_checker_failure():
    # NB-2 semantics, pinned structurally as the pre-existing NB-2 test
    # models them: the summary is the ONLY `if: always()` step, it runs
    # after the checker, it carries no continue-on-error, and the
    # checker carries no `if` — so a successful summary renders the
    # report but cannot turn the failed checker step (and therefore the
    # job/check conclusion) green.
    workflow = _m14_workflow()
    content = _content()
    report_steps = workflow["jobs"]["report"]["steps"]
    by_name = {step["name"]: step for step in report_steps}

    summary = by_name["Publish report summary"]
    assert summary.get("if") == "always()"
    assert content.count("if: always()") == 1
    assert not _m14_is_masking_continue_on_error(summary)
    assert "GITHUB_STEP_SUMMARY" in summary["run"]

    checker = by_name["Run report-only issue acceptance checker"]
    assert "if" not in checker
    assert not _m14_is_masking_continue_on_error(checker)
    names = [step["name"] for step in report_steps]
    assert names.index("Run report-only issue acceptance checker") < names.index(
        "Publish report summary"
    )


def test_m14_workflow_remains_advisory_and_report_only():
    # Advisory/non-required is pinned the way the pre-existing tests pin
    # it: read-only permissions, the report-only boundary statement, and
    # no required-check or mutation machinery in the YAML (whether the
    # check is required lives in branch protection/rulesets, outside
    # this file — nothing here may claim or simulate it). The honest-red
    # behaviour above is what keeps that advisory check meaningful.
    workflow = _m14_workflow()
    content = _content()

    assert workflow["permissions"] == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert "Report-only boundary" in content
    assert (
        "this workflow does not approve, merge, label, close, or mutate"
        in content
    )
