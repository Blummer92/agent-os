"""#3691: an admitted CKR6 request must receive one correlated infrastructure-failure receipt.

The existing workflow assertions check that the CKR6 workflow *contains* a
postback step and the substring ``always()``. Both hold while the receipt is
unreachable, because ``always()`` governs a step only inside a job that is
itself running: a job whose ``needs`` failed is skipped and runs no steps at
all. That is why the #3691 fail-silence survived a green suite, and it is why
this module evaluates the job graph instead of the file text.

The asserted contract is taken from #3691's own acceptance criteria, not from a
general invariant:

  * a classify-job infrastructure failure yields a correlated receipt
  * an execute-job infrastructure failure yields a correlated receipt, even
    when that failure broke the runtime the execute postback itself needs
  * an ordinary successful zero-read request yields exactly one receipt
  * skipped noncommands, unauthorized actors and PR comments yield none

A receipt only counts when the step *executes* a reporter (a mention of the
script name, or an ``echo`` of it, is inert) and its job can actually write an
issue comment (job ``permissions`` replace, not extend, the workflow level).
Every admitted outcome is asserted as exactly one receipt: two would be the
duplicate the reporter's dedupe exists to prevent.

Cancellation is deliberately NOT asserted. #3691 scopes the reporter to
"actual failed eligible requests" and warns against unrelated comment spam,
and the workflow sets ``cancel-in-progress: false``, so a cancelled run is a
deliberate act rather than an infrastructure failure. Whether a cancelled
admitted request is owed a receipt is an open owner decision, not a defect.

The simulator is local to this test: no production module, no fixture package,
no shared helper.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-ckr6.yml"

# The only shape accepted for a reporter step's `run`: strict mode, then one
# python command whose arguments are `--flag value` pairs. Nothing may follow
# the command on its line (`|| true`, `; exit 0`), precede it (an `exit 0` or a
# conditional), or wrap it (a heredoc, an `echo`).
_REPORTER_COMMAND = re.compile(
    r"(python3?\s+(?:scripts/ckr6_failure_postback\.py|-m\s+agent_os_execution_service\.ckr6_github_bridge))"
    r'((?:\s+--[\w-]+\s+(?:"[^"|;&\s]*"|[\w.-]+))+)'
)
_FLAG_PAIR = re.compile(r'(--[\w-]+)\s+("[^"|;&\s]*"|[\w.-]+)')
# Exact arguments of each reporter as the workflow passes them today. A flag
# that is added, repeated, repointed or replaced (`--help x`, `--event x`)
# means the reporter would not post what the requester is owed.
_EXPECTED_ARGS = {
    "scripts/ckr6_failure_postback.py": {
        "--event": '"$GITHUB_EVENT_PATH"', "--repository": '"$GITHUB_REPOSITORY"',
        "--allowed-actor": "Blummer92", "--api-url": '"$GITHUB_API_URL"',
    },
    "-m agent_os_execution_service.ckr6_github_bridge": {
        "--phase": "postback", "--event": '"$AGENT_OS_EVENT"',
        "--repository": '"$AGENT_OS_REPOSITORY"',
        "--result": '"$RUNNER_TEMP/agent-os-ckr6/result.json"', "--api-url": '"$GITHUB_API_URL"',
    },
}
# Keys a reporter step may carry. `shell`, `working-directory`,
# `continue-on-error` and `timeout-minutes` each change whether or where the
# command runs, so any of them makes the step unprovable here.
_STEP_KEYS = {"name", "if", "env", "run"}
_TOKENS = {"${{github.token}}", "${{secrets.GITHUB_TOKEN}}"}

_STATUS_FN = re.compile(r"\b(always|failure|cancelled)\s*\(")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# Loose detection: any line that starts a reporter, however it is wrapped.
_NAMES_REPORTER = re.compile(
    r"(?m)^\s*(?:if\b.*;\s*then\s+)?python3?\s+(?:scripts/ckr6_failure_postback\.py\b"
    r"|-m\s+agent_os_execution_service\.ckr6_github_bridge\b[^\n]*--phase\s+postback\b)"
)


def _names_reporter(step: dict) -> bool:
    return bool(_NAMES_REPORTER.search(re.sub(r"\\\n\s*", " ", str(step.get("run", "")))))


def _emits(step: dict) -> bool:
    """True when the step provably runs a reporter, not merely names one.

    This is deliberately a pinned shape, not a general Actions interpreter: it
    accepts the strict-mode spelling used today (`set -euo pipefail`), a step
    `if` that is absent or exactly `always()`, and the token spellings above.
    A legitimate respelling fails loudly here and is a one-line update; a
    spelling that could stop the reporter from posting must never pass.
    """
    lines = [
        line.strip()
        for line in re.sub(r"\\\n\s*", " ", str(step.get("run", ""))).splitlines()
        if line.strip()
    ]
    if len(lines) != 2 or lines[0] != "set -euo pipefail":
        return False
    match = _REPORTER_COMMAND.fullmatch(lines[1])
    if match is None:
        return False
    pairs = _FLAG_PAIR.findall(match.group(2))
    expected = _EXPECTED_ARGS[re.sub(r"\s+", " ", match.group(1)).split(" ", 1)[1]]
    condition = re.sub(r"\s", "", str(step["if"])) if "if" in step else None
    token = re.sub(r"\s", "", str(step.get("env", {}).get("GITHUB_TOKEN", "")))
    return (
        len(pairs) == len(expected)
        and dict(pairs) == expected
        and set(step) <= _STEP_KEYS
        and condition in (None, "${{always()}}")
        and token in _TOKENS
    )


def _can_comment(workflow: dict, job: dict) -> bool:
    return job.get("permissions", workflow.get("permissions", {})).get("issues") == "write"


def _needs(job: dict) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _defeats_success_gate(condition: str | None) -> bool:
    """Only a status function keeps a job alive when an upstream job failed."""
    return bool(condition) and bool(_STATUS_FN.search(condition))


def _evaluate(condition: str | None, results: dict[str, str], admitted: bool) -> bool:
    """Evaluate the subset of Actions expression syntax the CKR6 workflow uses."""
    if condition is None:
        return True
    expr = condition.strip()
    if expr.startswith("${{"):
        expr = expr[3:].rsplit("}}", 1)[0]
    # The admission guard is one fact for this simulation.
    expr = re.sub(r"github\.event\.issue\.pull_request\s*==\s*null", "ADMITTED", expr)
    expr = re.sub(r"github\.actor\s*==\s*'[^']*'", "ADMITTED", expr)
    expr = re.sub(r"startsWith\(github\.event\.comment\.body,\s*'[^']*'\)", "ADMITTED", expr)
    expr = re.sub(r"needs\.([\w-]+)\.result", lambda m: f"R[{m.group(1)!r}]", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ").replace("null", "None")
    namespace = {
        "R": results, "ADMITTED": admitted,
        "always": lambda: True,
        "failure": lambda: any(v == "failure" for v in results.values()),
        "cancelled": lambda: any(v == "cancelled" for v in results.values()),
        "success": lambda: all(v == "success" for v in results.values()),
    }
    return bool(eval(expr, {"__builtins__": {}}, namespace))  # noqa: S307 - fixed local grammar


def _schedule(workflow: dict, *, admitted: bool, outcomes: dict[str, str]) -> dict[str, str]:
    """Resolve each job to success / failure / skipped."""
    jobs = workflow["jobs"]
    results: dict[str, str] = {}
    pending = dict(jobs)
    while pending:
        ready = [n for n, j in pending.items() if all(d in results for d in _needs(j))]
        if not ready:
            break
        for name in ready:
            job = pending.pop(name)
            deps = _needs(job)
            condition = job.get("if")
            if deps and not _defeats_success_gate(condition):
                if any(results[d] != "success" for d in deps):
                    results[name] = "skipped"
                    continue
            runs = _evaluate(condition, {d: results[d] for d in deps}, admitted)
            results[name] = outcomes.get(name, "success") if runs else "skipped"
    for name in pending:
        results[name] = "skipped"
    return results


def _receipts(workflow: dict, results: dict[str, str], *,
              broken_job: str | None, runtime_broken: bool) -> list[str]:
    """Jobs that actually emit a receipt under this outcome set."""
    emitted = []
    for name, job in workflow["jobs"].items():
        if results.get(name) == "skipped":
            continue  # a skipped job runs no steps, whatever its steps say
        if not _can_comment(workflow, job):
            continue
        steps = job.get("steps", [])
        checkout = next(
            (i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout")),
            None,
        )
        for index, step in enumerate(steps):
            if not _emits(step) or checkout is None or index < checkout:
                continue
            if name == broken_job:
                # An earlier step failed: the step runs only with a status
                # function, and cannot post if that failure broke its runtime.
                if not _defeats_success_gate(step.get("if")) or runtime_broken:
                    continue
            emitted.append(f"{name}:{step.get('name')}")
    return emitted


# criterion, admitted, forced outcomes, job with a failed earlier step,
# whether that failure broke the receipt runtime, exact receipts required
ACCEPTANCE = [
    ("ac1-classify-infrastructure-failure", True, {"classify": "failure"}, None, False, 1),
    ("ac2-execute-infrastructure-failure", True, {"execute": "failure"}, "execute", True, 1),
    ("ac3-successful-zero-read", True, {}, None, False, 1),
    ("ac4-not-an-admitted-request", False, {}, None, False, 0),
]


@pytest.mark.parametrize(
    "criterion,admitted,outcomes,broken_job,runtime_broken,expected",
    ACCEPTANCE, ids=[case[0] for case in ACCEPTANCE],
)
def test_3691_acceptance_criteria_hold_over_the_job_graph(
    criterion, admitted, outcomes, broken_job, runtime_broken, expected
) -> None:
    workflow = _workflow()
    results = _schedule(workflow, admitted=admitted, outcomes=outcomes)
    receipts = _receipts(workflow, results,
                         broken_job=broken_job, runtime_broken=runtime_broken)
    state = ", ".join(f"{k}={v}" for k, v in sorted(results.items()))
    assert len(receipts) == expected, (
        f"[{criterion}] expected exactly {expected} correlated receipt(s), got "
        f"{receipts}. Job graph: {state}. Silence is indistinguishable from a lost "
        "result; a second receipt is the duplicate dedupe exists to prevent."
    )


def test_every_reporter_invocation_is_reliably_shaped() -> None:
    """A second or wrapped reporter must be seen, not ignored by the strict shape."""
    for name, job in _workflow()["jobs"].items():
        for step in job.get("steps", []):
            if _names_reporter(step):
                assert _emits(step), f"{name}:{step.get('name')} names a reporter it cannot be shown to run"


def test_execute_failure_with_a_working_runtime_has_two_emitters_so_dedupe_decides() -> None:
    """Not 'exactly one' by construction: the bridge may already have posted.

    When `execute` fails after the bridge runtime started, both its own
    postback step and `report-failure` run. That the requester then sees one
    receipt rests on the reporter's runtime lookup, covered in
    test_ckr6_failure_postback.py (dedupe) -- not on the job graph.
    """
    workflow = _workflow()
    results = _schedule(workflow, admitted=True, outcomes={"execute": "failure"})
    receipts = _receipts(workflow, results, broken_job="execute", runtime_broken=False)
    assert len(receipts) == 2, receipts


def test_a_receipt_job_survives_an_upstream_failure_on_its_own_condition() -> None:
    """The structural reason the defect was invisible to text assertions.

    A job that declares `needs` without a status function is skipped when that
    dependency fails, so any receipt step inside it is unreachable regardless
    of its own `if: always()`.
    """
    workflow = _workflow()
    survivors = []
    for name, job in workflow["jobs"].items():
        emits = any(_emits(step) for step in job.get("steps", []))
        if emits and (not _needs(job) or _defeats_success_gate(job.get("if"))):
            survivors.append(name)
    assert survivors, (
        "every receipt-emitting job is gated on its dependencies succeeding, so "
        "no receipt can be produced after an upstream failure. A step-level "
        "`if: always()` cannot rescue a job that is itself skipped."
    )


def test_failure_reporter_is_run_with_its_correlation_arguments() -> None:
    steps = [s for s in _workflow()["jobs"]["report-failure"]["steps"] if _emits(s)]
    assert len(steps) == 1
    for flag in ("--event", "--repository", "--allowed-actor", "--api-url"):
        assert flag in steps[0]["run"]


def test_top_level_permissions_stay_read_only() -> None:
    """Job permissions replace the workflow's, so widening the top level adds no
    receipt to the model above; it must be pinned on its own (#3691: no
    permissions broadening)."""
    assert _workflow()["permissions"] == {"contents": "read"}
