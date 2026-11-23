"""Contract and local execution tests for the advisory acceptance workflow."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.agent_os_issue_acceptance.checks.banned_patterns import check
from scripts.agent_os_issue_acceptance.models import IssueMetadata, Status

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-acceptance-report.yml"
VERIFY_REF = "Verify main dispatch"
CHECKOUT = "Check out trusted report evaluator"
VERIFY = "Verify trusted evaluator revision"
ROUTE = "Verify owner-authorized exact-file scope"
BUILD = "Build local acceptance fixtures from PR data"
CHECKER = "Run report-only issue acceptance checker"
SUMMARY = "Publish report summary"
FIXTURE_DIR = "tmp/agent_os_issue_acceptance_report"
PR_NUMBER = "23"
ORIGINAL_HEAD = "a" * 40
BASE = "b" * 40
EVALUATOR = "c" * 40
PR_FIXTURE = {
    "number": int(PR_NUMBER), "title": "Fixes #71", "body": "Fixes #71",
    "changedFiles": 1, "files": [{"path": "example.py"}],
    "headRefOid": ORIGINAL_HEAD, "baseRefOid": BASE,
}


@pytest.fixture
def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture
def workflow(workflow_text):
    # PyYAML defaults to YAML 1.1, where plain on would become True.
    text = re.sub(r"^on:", "'on':", workflow_text, flags=re.MULTILINE)
    return yaml.safe_load(text)


@pytest.fixture
def steps(workflow):
    report_steps = workflow["jobs"]["report"]["steps"]
    by_name = {step.get("name"): step for step in report_steps}
    assert len(by_name) == len(report_steps) and None not in by_name, report_steps
    for expected in (VERIFY_REF, CHECKOUT, VERIFY, ROUTE, BUILD, CHECKER, SUMMARY):
        assert expected in by_name, f"Missing workflow step {expected!r}: {list(by_name)}"
    return by_name


def test_dispatch_is_manual_read_only_and_advisory(workflow, steps):
    assert workflow["name"] == "Agent OS Issue Acceptance Report"
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["pr_number"]["required"] is False
    assert set(workflow["jobs"]) == {"report"}
    assert "needs" not in workflow["jobs"]["report"]
    assert workflow["permissions"] == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    assert steps[BUILD]["env"]["PR_NUMBER"] == "${{ inputs.pr_number }}"
    assert "Report-only boundary: this workflow does not approve, merge, label, close, or mutate" in steps[SUMMARY]["run"]


def test_only_trusted_dispatch_revision_supplies_checker(steps):
    checkout = steps[CHECKOUT]
    assert checkout.get("uses", "").startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False
    assert sum(step.get("uses", "").startswith("actions/checkout@") for step in steps.values()) == 1
    assert steps[VERIFY]["env"]["EXPECTED_EVALUATOR_SHA"] == "${{ github.sha }}"
    assert steps[VERIFY_REF]["env"]["EXPECTED_DISPATCH_REF"] == "${{ github.ref }}"
    setup_name = "Set up Python test environment"
    assert setup_name in steps, "Missing shared Python environment setup"
    assert steps[setup_name].get("uses") == "./.github/actions/setup-python-dev"
    expected = (VERIFY_REF, CHECKOUT, VERIFY, setup_name, ROUTE, BUILD, CHECKER)
    assert [name for name in steps if name in expected] == list(expected)
    assert "python -m scripts.agent_os_issue_acceptance.cli" in steps[CHECKER]["run"]
    tokens = {name: step["env"]["GH_TOKEN"] for name, step in steps.items()
              if "GH_TOKEN" in step.get("env", {})}
    assert tokens == dict.fromkeys((BUILD, CHECKER), "${{ github.token }}")
    assert {name for name, step in steps.items() if "GITHUB_TOKEN" in step.get("env", {})} == {ROUTE}
    assert steps[ROUTE]["env"] == {
        "GITHUB_TOKEN": "${{ github.token }}",
        "ROUTE_PR": "${{ inputs.pr_number }}",
        "ROUTE_HEAD": "${{ inputs.expected_head_sha }}",
    }


def test_no_write_command_or_failure_masking(workflow, workflow_text, steps):
    forbidden = (
        "gh issue edit", "gh issue close", "gh pr edit", "gh pr merge",
        "add-label", "remove-label", "set-label", "github.rest.issues.addLabels",
        "github.rest.issues.removeLabel", "github.rest.issues.setLabels", "github.rest.issues.update",
        "github.rest.pulls.update", "branch-protection", "updateBranchProtection",
    )
    assert not [pattern for pattern in forbidden if pattern in workflow_text]
    report = workflow["jobs"]["report"]
    for name, job_or_step in [("report", report), *steps.items()]:
        value = job_or_step.get("continue-on-error", False)
        assert value is False, f"{name!r} must not mask failures: {value!r}"
    primary = "steps.exact_file.outputs.route == 'issue-primary'"
    assert {name: step["if"] for name, step in steps.items() if "if" in step} == {
        BUILD: primary, CHECKER: primary, SUMMARY: "always()",
    }
    assert list(steps)[-1:] == [SUMMARY], "Summary must run after the checker"
    assert "PIPESTATUS" in steps[CHECKER]["run"]


def test_report_only_linkage_and_net_diff_contract(steps):
    build = steps[BUILD]["run"]
    assert "parse_linked_issue_result(" in build
    assert "report_only_issue_number(" in build
    assert "LinkedIssueParseStatus" not in build
    assert re.search(r'gh pr diff "\$PR_NUMBER" [^\n]*--color=never', build)
    assert 'gh pr diff "$PR_NUMBER" --patch' not in build
    assert "diff_retrieval_failed.txt" in build
    checker = steps[CHECKER]["run"]
    assert "--diff-retrieval-failed" in checker
    assert "--changed-files-incomplete" in checker
    assert checker.count("--documentation-advisory") == 1


def test_net_diff_still_rejects_new_secrets_and_not_removed_history():
    candidate = "se" + "cret" + " = " + repr("synthetic-test-canary-only")
    history = (
        "diff --git a/example.py b/example.py\n+status = 'old'\n+" + candidate
        + "\ndiff --git a/example.py b/example.py\n-" + candidate + "\n+status = 'safe'\n"
    )
    final_net_diff = "diff --git a/example.py b/example.py\n+status = 'safe'\n"
    metadata = IssueMetadata.empty()
    assert check(metadata, history).status == Status.FAIL
    assert check(metadata, final_net_diff).status == Status.PASS
    assert check(metadata, final_net_diff + "+" + candidate + "\n").status == Status.FAIL


@pytest.fixture
def runner(tmp_path, steps):
    """Execute Bash steps offline; only GitHub and the CLI's output are simulated."""
    stub = tmp_path / "stub"
    stub.write_text(f"#!{sys.executable}\n" + f'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
tool = Path(sys.argv[0]).name
if tool == "git":
    assert args == ["rev-parse", "HEAD"]
    print({EVALUATOR!r})
elif tool == "python":
    if args[:2] == ["-m", "scripts.agent_os_issue_acceptance.exact_file_draft_route"]:
        Path("route-args.json").write_text(json.dumps(args[2:]))
        sys.exit(int(os.environ["ROUTE_EXIT"]))
    if args[:2] == ["-m", "scripts.agent_os_issue_acceptance.cli"]:
        Path("checker-args.json").write_text(json.dumps(args[2:]))
        if os.environ.get("CHECKER_MODE") == "real":
            os.execv(sys.executable, [sys.executable, *args])
        if os.environ.get("CHECKER_MODE") == "exception":
            raise RuntimeError("synthetic checker error")
        verdict = os.environ.get("CHECKER_VERDICT", "manual-review")
        print("# Report\\n\\nFixture output\\nOverall result: " + verdict)
        sys.exit(int(os.environ.get("CHECKER_EXIT", 0)))
    if args[:2] == ["-m", "scripts.agent_os_issue_acceptance.build_merged_doc_evidence"]:
        Path(args[args.index("--output") + 1]).write_text("[]")
    else:
        os.execv(sys.executable, [sys.executable, *args])
else:
    log = Path("gh-calls")
    prior_calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    index = sum(call[:3] == args[:3] for call in prior_calls)
    with log.open("a") as stream:
        print(json.dumps(args), file=stream)
    kind, verb, number, repo_flag, repo, *options = args
    assert repo_flag == "--repo" and repo == os.environ["GITHUB_REPOSITORY"], args
    expected = os.environ["PR_NUMBER"] if kind == "pr" else "71"
    assert number == expected, args
    scenario = json.loads(Path("gh-responses.json").read_text())
    if verb == "diff":
        assert options == ["--color=never"], args
        print("diff --git a/example.py b/example.py")
        sys.exit(int(scenario["diff_failure"]))
    assert verb == "view" and len(options) == 2 and options[0] == "--json", args
    response = scenario[kind][index]
    if response == "unavailable":
        sys.exit(1)
    if response == "malformed":
        print("not JSON")
    elif response == "duplicate":
        for body in ("first fixture", "second fixture"):
            print(json.dumps(dict(number=71, body=body)))
    else:
        print(json.dumps({{key: response[key] for key in options[1].split(",") if key in response}}))
''', encoding="utf-8")
    stub.chmod(0o755)
    for name in ("gh", "python", "git"):
        (tmp_path / name).symlink_to(stub)

    env = dict(
        os.environ, PATH=f"{tmp_path}:{os.environ.get('PATH', os.defpath)}",
        PYTHONPATH=os.pathsep.join((str(ROOT), os.environ.get("PYTHONPATH", ""))),
        GH_TOKEN="local-test-only", PR_NUMBER=PR_NUMBER, GITHUB_PR_NUMBER=PR_NUMBER,
        ROUTE_PR=PR_NUMBER, ROUTE_HEAD=ORIGINAL_HEAD, ROUTE_EXIT="3",
        GITHUB_REPOSITORY="example/project", GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1",
        GITHUB_OUTPUT="output", GITHUB_STEP_SUMMARY="summary", REPORT_DIR=str(tmp_path / FIXTURE_DIR),
    )
    _configure(tmp_path)
    outcome = "skipped"

    def run(name, *, missing=(), **overrides):
        nonlocal outcome
        active = {key: val for key, val in (env | overrides).items() if key not in missing}
        if name == SUMMARY:
            output = tmp_path / env["GITHUB_OUTPUT"]
            values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
            active.update(ACCEPTANCE_ROUTE=values.get("route", ""),
                          CHECKER_STATE=values.get("checker_state", ""),
                          CHECKER_EXIT_CODE=values.get("checker_exit_code", ""),
                          CHECKER_OUTCOME=outcome)
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", steps[name]["run"]],
            cwd=tmp_path, env=active, text=True, capture_output=True, timeout=10,
        )
        if name == CHECKER:
            outcome = "success" if result.returncode == 0 else "failure"
        return result

    return run, tmp_path


def _configure(tmp, *, initial=None, fresh=None, issue=None, diff_failure=False):
    first = PR_FIXTURE if initial is None else initial
    (tmp / "gh-responses.json").write_text(json.dumps({
        "pr": [first, first if fresh is None else fresh],
        "issue": [{"number": 71, "body": "first issue body"}] * 2 if issue is None else issue,
        "diff_failure": diff_failure,
    }), encoding="utf-8")


def _args(tmp):
    return json.loads((tmp / "checker-args.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("number", "head", "verifier_exit", "route"),
    [
        ("4092", ORIGINAL_HEAD, "0", "exact-file"),
        ("4093", ORIGINAL_HEAD, "0", "exact-file"),
        (PR_NUMBER, "", "3", "issue-primary"),
        ("", "", "3", "issue-primary"),
        ("4092", "", "0", None),
        ("4093", "a" * 39, "0", None),
        ("4092", ORIGINAL_HEAD, "1", None),
        ("4093", ORIGINAL_HEAD, "2", None),
        ("-4093", ORIGINAL_HEAD, "0", None),
    ],
)
def test_exact_file_route_and_summary_fail_closed(runner, number, head, verifier_exit, route):
    run, tmp = runner
    checked = run(ROUTE, ROUTE_PR=number, ROUTE_HEAD=head, ROUTE_EXIT=verifier_exit)
    assert (checked.returncode == 0) == (route is not None), checked.stderr
    if number.isdecimal():
        assert json.loads((tmp / "route-args.json").read_text()) == [
            "--repository", "example/project", "--pr-number", number, "--expected-head", head,
        ]
    else:
        assert not (tmp / "route-args.json").exists()
    output = tmp / "output"
    assert output.exists() == (route is not None)
    if route is not None:
        assert output.read_text() == f"route={route}\n"
    assert run(SUMMARY, ROUTE_HEAD=head).returncode == 0
    summary = (tmp / "summary").read_text()
    if route == "exact-file":
        assert f"exact PR head: `{head}`" in summary
        assert "does not establish CKR6 admission" in summary
        assert "issue-primary checker was not run" in summary
    else:
        assert "Verified owner grant" not in summary
        assert "Checker status: NOT_RUN" in summary


def _option(args, key):
    exact = [i for i, arg in enumerate(args) if arg == key]
    attached = [arg[len(key) + 1:] for arg in args if arg.startswith(key + "=")]
    assert len(exact) + len(attached) == 1, args
    return attached[0] if attached else args[exact[0] + 1]


def _assert_ok(result):
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def _run_fixture_and_checker(run):
    for step in (BUILD, CHECKER):
        _assert_ok(run(step))


@pytest.mark.parametrize("ref,sha,expected", [
    ("refs/heads/main", EVALUATOR, 0),
    ("refs/heads/topic", EVALUATOR, 1),
    ("refs/heads/main", BASE, 1),
])
def test_dispatch_verifier_requires_main_and_exact_checkout(runner, ref, sha, expected):
    run, _ = runner
    first = run(VERIFY_REF, EXPECTED_DISPATCH_REF=ref)
    final = run(VERIFY, EXPECTED_EVALUATOR_SHA=sha) if first.returncode == 0 else first
    assert final.returncode == expected


def test_combines_pr_metadata_without_reusing_the_fresh_observation(runner):
    run, tmp = runner
    _run_fixture_and_checker(run)
    calls = [json.loads(line) for line in (tmp / "gh-calls").read_text().splitlines()]
    kinds = [tuple(call[:3]) for call in calls]
    assert kinds.count(("pr", "view", PR_NUMBER)) == 2, calls
    assert kinds.count(("pr", "diff", PR_NUMBER)) == 1, calls
    assert kinds.count(("issue", "view", "71")) == 2, calls
    args = _args(tmp)
    assert _option(args, "--transport-pr-number") == PR_NUMBER
    assert _option(args, "--transport-pr-head-sha") == ORIGINAL_HEAD
    assert _option(args, "--transport-fresh-pr-head-sha") == ORIGINAL_HEAD
    assert _option(args, "--transport-evaluator-sha") == EVALUATOR
    assert _option(args, "--transport-workflow-run-id") == "123"
    assert _option(args, "--transport-workflow-run-attempt") == "1"
    assert _option(args, "--transport-issue-number") == "71"
    assert "--transport-observed-at" in args


@pytest.mark.parametrize("title", ["  Padded title  ", "Résumé 日本語 $5", "--documentation-advisory", "x" * 256])
def test_title_is_one_unchanged_checker_argument(runner, title):
    run, tmp = runner
    _configure(tmp, initial={**PR_FIXTURE, "title": title})
    _run_fixture_and_checker(run)
    args = _args(tmp)
    assert _option(args, "--pr-title") == title


@pytest.mark.parametrize("bad", [
    "malformed", "unavailable", {}, {"number": 1},
    *[dict(PR_FIXTURE, title=title) for title in ("", "Title\nline two", "Title\rreturn", "Title\x07bell", "x" * 10000)],
])
def test_invalid_initial_metadata_cannot_run_checker(runner, bad):
    run, tmp = runner
    _configure(tmp, initial=bad)
    result = run(BUILD)
    assert result.returncode != 0
    if isinstance(bad, dict) and (title := bad.get("title")):
        assert title not in result.stdout + result.stderr
    assert not (tmp / "checker-args.json").exists()
    _assert_ok(run(SUMMARY))
    assert "NOT_RUN" in (tmp / "summary").read_text()


@pytest.mark.parametrize("change", [{"headRefOid": "d" * 40}, {"body": "A newer description"}, {"number": 8}])
def test_stale_or_mismatched_pr_metadata_never_looks_current(runner, change):
    run, tmp = runner
    _configure(tmp, fresh={**PR_FIXTURE, **change})
    _assert_ok(run(BUILD))
    result = run(CHECKER)
    if "headRefOid" in change:
        _assert_ok(result)
        args = _args(tmp)
        assert _option(args, "--transport-pr-head-sha") == ORIGINAL_HEAD
        assert _option(args, "--transport-fresh-pr-head-sha") == change["headRefOid"]
    else:
        assert result.returncode != 0
        assert not (tmp / "checker-args.json").exists()


@pytest.mark.parametrize("drift", ["stale-pr-head", "stale-issue"])
def test_workflow_and_real_checker_flag_stale_transport(runner, drift):
    run, tmp = runner
    fixtures = Path(__file__).parent / "fixtures"
    pr = {**PR_FIXTURE, "body": (fixtures / "pr_body_valid.md").read_text().replace("#164", "#71")}
    issue = (fixtures / "issue_valid.md").read_text()
    observed_issue = issue + "\nUpdated issue notes.\n" if drift == "stale-issue" else issue
    fresh = {**pr, "headRefOid": "d" * 40} if drift == "stale-pr-head" else pr
    _configure(tmp, initial=pr, fresh=fresh,
               issue=[{"number": 71, "body": body} for body in (issue, observed_issue)])
    _assert_ok(run(BUILD))
    run(CHECKER, CHECKER_MODE="real")
    _assert_ok(run(SUMMARY))
    report = (tmp / "summary").read_text()
    assert f"transport_state: {drift}" in report, report
    assert "execution_authorized: false" in report, report


@pytest.mark.parametrize("issue", [
    [{"number": 71, "body": "old"}, {"number": 71, "body": "new"}],
    ["unavailable", {"number": 71, "body": "new"}],
    ["duplicate", {"number": 71, "body": "new"}],
    [{"number": 71, "body": "old"}, "duplicate"],
    [{"number": 71, "body": "old"}, {"number": "71", "body": "wrong number type"}],
    [{"number": 71, "body": "old"}, "malformed"],
    [{"number": 71, "body": "old"}, {"number": 72, "body": "wrong issue"}],
])
def test_issue_reads_are_separate_and_failures_preserved(runner, issue):
    run, tmp = runner
    _configure(tmp, issue=issue)
    _run_fixture_and_checker(run)
    args = _args(tmp)
    if not isinstance(issue[0], dict) or not isinstance(issue[1], dict) or issue[1]["number"] != 71:
        assert "--transport-issue-body-retrieval-failed" in args
    else:
        initial = (tmp / _option(args, "--transport-issue-body-file")).read_text()
        fresh = (tmp / _option(args, "--transport-fresh-issue-body-file")).read_text()
        assert initial.strip() == "old" and fresh.strip() == "new"


@pytest.mark.parametrize("mode,exit_code,verdict,status", [
    ("", 1, "fail", "CHECKER_FAIL"),
    ("exception", 1, "fail", "EXECUTION_ERROR"),
    ("", 0, "manual-review", "MANUAL_REVIEW"),
])
def test_checker_failure_is_not_masked_and_summary_reports_verdict(runner, mode, exit_code, verdict, status):
    run, tmp = runner
    _assert_ok(run(BUILD))
    result = run(CHECKER, CHECKER_MODE=mode, CHECKER_EXIT=str(exit_code), CHECKER_VERDICT=verdict)
    assert result.returncode == exit_code
    _assert_ok(run(SUMMARY))
    rendered = (tmp / "summary").read_text()
    assert f"Checker status: {status}" in rendered and "NOT_RUN" not in rendered
    assert f"Checker exit code: {exit_code}" in rendered
    assert "Report-only boundary" in rendered
    if not mode:
        assert f"Overall result: {verdict}" in rendered


@pytest.mark.parametrize("failure", ["unset", "missing", "tee"])
def test_checker_setup_or_report_write_failure_is_nonzero(runner, failure):
    run, tmp = runner
    _assert_ok(run(BUILD))
    options = {}
    if failure == "unset":
        options["missing"] = ("GITHUB_RUN_ID",)
    if failure == "missing":
        (tmp / FIXTURE_DIR / "pr_title.txt").unlink()
    if failure == "tee":
        (tmp / FIXTURE_DIR / "report.txt").mkdir()
    assert run(CHECKER, **options).returncode != 0
    _assert_ok(run(SUMMARY))
    assert "Checker status: EXECUTION_ERROR" in (tmp / "summary").read_text()


@pytest.mark.parametrize("fresh", ["malformed", "unavailable", {}])
def test_invalid_fresh_pr_observation_fails_closed(runner, fresh):
    run, tmp = runner
    _configure(tmp, fresh=fresh)
    _assert_ok(run(BUILD))
    assert run(CHECKER).returncode != 0
    assert not (tmp / "checker-args.json").exists()
    _assert_ok(run(SUMMARY))
    assert "Checker status: EXECUTION_ERROR" in (tmp / "summary").read_text()


def test_missing_manual_dispatch_context_remains_explicit_manual_review(runner):
    run, tmp = runner
    _assert_ok(run(BUILD, PR_NUMBER=""))
    _assert_ok(run(CHECKER, GITHUB_PR_NUMBER=""))
    args = _args(tmp)
    assert "--transport-pr-number" not in args
    assert "did not provide a pull request number" in Path(_option(args, "--pr-body")).read_text()
    assert not (tmp / "gh-calls").exists()


def test_incomplete_paths_and_diff_failure_are_explicit_evidence_flags(runner):
    run, tmp = runner
    _configure(tmp, initial={**PR_FIXTURE, "changedFiles": 2}, diff_failure=True)
    _run_fixture_and_checker(run)
    args = _args(tmp)
    assert "--changed-files-incomplete" in args
    assert "--diff-retrieval-failed" in args
    assert Path(_option(args, "--diff")).read_text() == ""


@pytest.mark.parametrize("body,issue_expected", [
    ("Part of #71\n\nNon-closing: #71", True),
    ("Addresses #71 and #72", False),
])
def test_only_report_scoped_unambiguous_issue_is_fetched(runner, body, issue_expected):
    run, tmp = runner
    _configure(tmp, initial={**PR_FIXTURE, "body": body, "title": "Report"})
    _run_fixture_and_checker(run)
    args = _args(tmp)
    assert ("--transport-issue-number" in args) is issue_expected
