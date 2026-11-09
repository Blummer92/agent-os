"""Negative controls for the trusted status publisher (PR #3829).

Local, deterministic, no-network controls. Every control names its trust
invariant, the input mutation, the expected publisher behaviour, and the
classification of the observed outcome:

- REJECTED_RED: an error/failure status was published for the exact head.
- REJECTED_NO_PUBLICATION: no status was created (state None, exit 0).
- PUBLICATION_FAILED: a status POST was attempted and the provider refused it.
- FALSE_GREEN: untrustworthy evidence produced a success status.
- UPSTREAM_GAP: the evidence defect lives in an upstream producer/gate the
  publisher intentionally trusts (provider job/step conclusions), not in the
  publisher itself; recorded separately, never silently relabelled as a
  publisher pass.
- RESIDUAL_RISK / LIMITATION: behaviour that is fail-closed locally but
  leaves a stale or time-of-check risk the publisher does not itself close.

The publisher's trust model, per docs/ci-trust/trusted-status-publisher-pilot.md:
provider-owned GitHub records only (workflow_run event identity, PR
association/current state, latest run/attempt, changed files, jobs/steps).
It does NOT read JUnit artifacts, test files, or any PR-controlled content.
Controls that assume JUnit verification therefore characterise that boundary
instead of asserting a publisher defect.
"""
import importlib.util
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publisher_nc", ROOT / "scripts/agent_os_trusted_status_publisher.py"
)
pub = importlib.util.module_from_spec(SPEC)
sys.modules["publisher_nc"] = pub
SPEC.loader.exec_module(pub)

REPO = "Blummer92/agent-os"
SHA = "a" * 40
SHA2 = "b" * 40
RUN_ID = 123
ATTEMPT = 2
WORKFLOW_ID = 445


def source(**fields):
    j = dict(
        id=RUN_ID, run_attempt=ATTEMPT, workflow_id=WORKFLOW_ID,
        status="completed", conclusion="success", head_sha=SHA,
        head_branch="fix/ci", path=pub.SOURCE_PATH, event="pull_request",
        repository={"full_name": REPO},
    )
    j.update(fields)
    return j


def pr(**fields):
    p = dict(
        number=42, state="open", draft=False,
        base={"ref": "main", "repo": {"full_name": REPO}},
        head={"sha": SHA, "ref": "fix/ci", "repo": {"full_name": REPO}},
    )
    p.update(fields)
    return p


def run_record(run_id=RUN_ID, attempt=ATTEMPT, created_at="2026-11-08T20:00:00Z", **fields):
    r = dict(
        id=run_id, run_attempt=attempt, created_at=created_at,
        head_sha=SHA, event="pull_request", path=pub.SOURCE_PATH,
    )
    r.update(fields)
    return r


def jobs(run_id=RUN_ID, attempt=ATTEMPT):
    result = []
    for n, name in enumerate(pub.JOBS):
        steps = [
            {"name": x, "conclusion": "success", "status": "completed"}
            for x in pub.REQUIRED_STEPS.get(name, ())
        ]
        result.append(
            dict(
                id=n + 1, run_id=run_id, run_attempt=attempt, name=name,
                conclusion="success", status="completed", steps=steps,
            )
        )
    return result


class FakeApi:
    """Deterministic provider stub with paged responses and call logging."""

    def __init__(self, *, assoc_pages=None, current=None, runs_pages=None,
                 files_pages=None, jobs_pages=None, raise_on=None):
        self.assoc_pages = assoc_pages if assoc_pages is not None else [[pr()]]
        self.current = current if current is not None else pr()
        self.runs_pages = runs_pages if runs_pages is not None else [[run_record()]]
        self.files_pages = files_pages if files_pages is not None else [[{"filename": "src/safe.py"}]]
        self.jobs_pages = jobs_pages if jobs_pages is not None else [jobs()]
        self.raise_on = raise_on or {}
        self.calls = []
        self.log = []  # shared order log with publication posts, when shared

    def _page(self, endpoint):
        qs = parse_qs(urlparse(endpoint).query)
        return int(qs.get("page", ["1"])[0])

    def _take(self, pages, endpoint):
        page = self._page(endpoint)
        return pages[page - 1] if 1 <= page <= len(pages) else []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        self.log.append(("api", endpoint))
        for needle, exc in self.raise_on.items():
            if needle in endpoint:
                raise exc
        if "/commits/" in endpoint and "/pulls" in endpoint:
            return self._take(self.assoc_pages, endpoint)
        if "/pulls/" in endpoint and "/files" in endpoint:
            return self._take(self.files_pages, endpoint)
        if "/pulls/" in endpoint:
            return self.current
        if "/actions/workflows/" in endpoint:
            return {"workflow_runs": self._take(self.runs_pages, endpoint)}
        if "/jobs?" in endpoint:
            return {"jobs": self._take(self.jobs_pages, endpoint)}
        raise AssertionError("unexpected API " + endpoint)


def decide_with(fake, src=None):
    with patch.object(pub, "api", side_effect=fake):
        return pub.decide({"workflow_run": src or source()}, REPO)


def run_main(tmp_path, fake, src=None, publish=True, post_rc=0):
    """Run the real main() with mocked provider + mocked POST.

    Returns (exit_code, stdout_json_dict_or_None, posts, order_log).
    SystemExit from main (e.g. rejected publication) is reported as its
    code; any other exception propagates to the caller.
    """
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"workflow_run": src or source()}))
    posts = []
    log = getattr(fake, "log", None)
    if log is None:
        log = []
    else:
        fake.log = log

    def fake_run(cmd, **kwargs):
        posts.append(list(cmd))
        log.append(("post", list(cmd)))
        return SimpleNamespace(returncode=post_rc, stdout="{}", stderr="")

    argv = ["--event", str(path), "--repository", REPO]
    if publish:
        argv.append("--publish")
    buf = io.StringIO()
    with patch.object(pub, "api", side_effect=fake), \
            patch.object(pub.subprocess, "run", side_effect=fake_run):
        try:
            with redirect_stdout(buf):
                code = pub.main(argv)
        except SystemExit as exc:
            code = exc.code
    try:
        out = json.loads(buf.getvalue())
    except Exception:
        out = None
    return code, out, posts, log


def post_cmd(posts, index=0):
    return posts[index]


# ---------------------------------------------------------------------------
# A. Test failure propagation
# ---------------------------------------------------------------------------

def test_A01_junit_failures_with_green_jobs_are_invisible_to_publisher():
    """UPSTREAM_GAP (NC09): publisher trusts provider job/step conclusions
    and takes no JUnit input at all. Green jobs -> success even though a
    JUnit report full of failures would contradict them. The defect lives
    in the upstream completeness/gate producer, not in this publisher."""
    assert pub.evaluate(source(), jobs(), set())["state"] == "success"
    params = inspect.signature(pub.evaluate).parameters
    assert "junit" not in params and "artifact" not in params
    params = inspect.signature(pub.decide).parameters
    assert "junit" not in params and "artifact" not in params


def test_A02_aggregate_gate_job_failure_is_failure():
    copy = jobs()
    next(j for j in copy if j["name"] == "Agent OS aggregate gate")["conclusion"] = "failure"
    assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "failure"


def test_A03_frontend_job_failure_is_failure():
    copy = jobs()
    next(j for j in copy if j["name"] == "Run frontend checks")["conclusion"] = "failure"
    assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "failure"


def test_A04_job_conclusions_cancelled_neutral_timed_out_are_failure():
    for conclusion in ("cancelled", "neutral", "timed_out", "action_required"):
        copy = jobs()
        next(j for j in copy if j["name"] == "Run aggregate validation")["conclusion"] = conclusion
        assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "failure", conclusion


def test_A05_required_step_failure_is_error():
    copy = jobs()
    job = next(j for j in copy if j["name"] == "Run aggregate validation")
    next(s for s in job["steps"] if s["name"] == "Run aggregate validation")["conclusion"] = "failure"
    assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "error"


def test_A06_plan_job_failure_is_failure_even_without_required_steps():
    copy = jobs()
    next(j for j in copy if j["name"] == "Run validation plan")["conclusion"] = "failure"
    assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "failure"


# ---------------------------------------------------------------------------
# B. Exact-head and attempt provenance
# ---------------------------------------------------------------------------

def test_B01_current_pr_head_moved_after_association_is_no_publish():
    fake = FakeApi(current=pr(head={"sha": SHA2, "ref": "fix/ci", "repo": {"full_name": REPO}}))
    assert decide_with(fake)["state"] is None


def test_B02_associated_pr_on_other_branch_is_no_publish():
    bad = pr(head={"sha": SHA, "ref": "other-branch", "repo": {"full_name": REPO}})
    assert decide_with(FakeApi(assoc_pages=[[bad]]))["state"] is None


def test_B03_pr_closed_between_reads_is_no_publish():
    fake = FakeApi(current=pr(state="closed"))
    assert decide_with(fake)["state"] is None


def test_B04_newer_attempt_on_same_run_supersedes():
    runs = [run_record(run_id=RUN_ID, attempt=ATTEMPT, created_at="2026-11-08T20:00:00Z"),
            run_record(run_id=RUN_ID, attempt=ATTEMPT + 1, created_at="2026-11-08T20:10:00Z")]
    assert decide_with(FakeApi(runs_pages=[runs]))["state"] is None


def test_B05_newer_run_wins_on_created_at_then_id():
    older = run_record(run_id=RUN_ID, attempt=ATTEMPT, created_at="2026-11-08T20:00:00Z")
    newer = run_record(run_id=RUN_ID + 1, attempt=1, created_at="2026-11-08T20:10:00Z")
    assert decide_with(FakeApi(runs_pages=[[older, newer]]))["state"] is None
    # Tie on created_at: the higher run id is newest, so the event run wins.
    tied_older = run_record(run_id=RUN_ID, attempt=ATTEMPT, created_at="2026-11-08T20:00:00Z")
    tied_newer = run_record(run_id=RUN_ID + 1, attempt=1, created_at="2026-11-08T20:00:00Z")
    assert decide_with(
        FakeApi(runs_pages=[[tied_older, tied_newer]],
                jobs_pages=[jobs(run_id=RUN_ID + 1, attempt=1)]),
        src=source(id=RUN_ID + 1, run_attempt=1))["state"] == "success"


def test_B06_stale_success_is_overwritten_by_later_failed_attempt(tmp_path):
    code, out, posts, _ = run_main(tmp_path, FakeApi(), src=source(conclusion="failure"))
    assert code == 1
    assert out["state"] == "failure"
    assert len(posts) == 1
    cmd = post_cmd(posts)
    assert f"repos/{REPO}/statuses/{SHA}" in cmd
    assert "state=failure" in cmd
    assert f"context={pub.CONTEXT}" in cmd
    assert f"target_url=https://github.com/{REPO}/actions/runs/{RUN_ID}" in cmd


def test_B07_unverifiable_later_attempt_publishes_nothing(tmp_path):
    """RESIDUAL_RISK: provider failure after an earlier success leaves the
    stale success displayed; the publisher mints nothing from incomplete
    evidence (exit 0, state None, no POST)."""
    fake = FakeApi(raise_on={"/jobs?": RuntimeError("provider down")})
    code, out, posts, _ = run_main(tmp_path, fake)
    assert code == 0
    assert out["state"] is None
    assert posts == []


def test_B08_no_revalidation_between_decision_and_publication(tmp_path):
    """LIMITATION (TOCTOU): main() publishes from the decide-time snapshot;
    it performs no second provider read between decide() and the POST, so a
    PR/attempt change inside that window is not re-checked before minting."""
    fake = FakeApi()
    code, out, posts, log = run_main(tmp_path, fake)
    assert code == 0 and out["state"] == "success" and len(posts) == 1
    post_index = next(i for i, e in enumerate(log) if e[0] == "post")
    assert all(e[0] == "api" for e in log[:post_index])
    assert not any(e[0] == "api" for e in log[post_index + 1:])


# ---------------------------------------------------------------------------
# C. Malformed or incomplete provider evidence
# ---------------------------------------------------------------------------

def test_C01_api_malformed_json_is_runtime_error():
    with patch.object(pub.subprocess, "run",
                      return_value=SimpleNamespace(returncode=0, stdout="not json")):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            pub.api("repos/x/y")


def test_C02_api_nonzero_exit_is_runtime_error():
    with patch.object(pub.subprocess, "run",
                      return_value=SimpleNamespace(returncode=1, stdout="", stderr="403")):
        with pytest.raises(RuntimeError, match="provider request failed"):
            pub.api("repos/x/y")


def test_C03_api_timeout_propagates():
    with patch.object(pub.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=45)):
        with pytest.raises(subprocess.TimeoutExpired):
            pub.api("repos/x/y")


def test_C04_jobs_pagination_incomplete_raises_and_publishes_nothing(tmp_path):
    filler = [dict(id=1000 + i, run_id=RUN_ID, run_attempt=ATTEMPT, name=f"Filler-{i}",
                   conclusion="success", status="completed", steps=[]) for i in range(100)]
    fake = FakeApi(jobs_pages=[filler] * 20)
    with pytest.raises(ValueError, match="pagination incomplete"):
        decide_with(fake)
    code, out, posts, _ = run_main(tmp_path, FakeApi(jobs_pages=[filler] * 20))
    assert code == 0 and out["state"] is None and posts == []


def test_C05_files_pagination_incomplete_raises(tmp_path):
    filler = [[{"filename": f"src/f{i}.py"} for i in range(100)]] * 20
    fake = FakeApi(files_pages=filler)
    with pytest.raises(ValueError, match="pagination incomplete"):
        decide_with(fake)
    code, out, posts, _ = run_main(tmp_path, FakeApi(files_pages=filler))
    assert code == 0 and out["state"] is None and posts == []


def test_C06_latest_attempt_misses_newer_run_beyond_first_page():
    """REGRESSION (pre-repair FALSE_GREEN): latest_attempt reads a single
    page of at most 100 runs. With 100 older runs on page 1 and a newer run
    on page 2, the stale event run is mistaken for newest and success is
    minted for a superseded attempt."""
    page1 = [run_record(run_id=1000 + i, attempt=1, created_at="2026-11-08T20:00:00Z")
             for i in range(100)]
    # The event run is the newest run visible on page 1.
    page1[-1] = run_record(run_id=1099, attempt=ATTEMPT, created_at="2026-11-08T20:00:00Z")
    page2 = [run_record(run_id=2000, attempt=1, created_at="2026-11-08T21:00:00Z")]
    fake = FakeApi(runs_pages=[page1, page2], jobs_pages=[jobs(run_id=1099, attempt=ATTEMPT)])
    assert decide_with(fake, src=source(id=1099, run_attempt=ATTEMPT))["state"] is None


def test_C07_associated_pr_beyond_first_page_is_found():
    """REGRESSION (pre-repair false negative): lookup_pr reads a single
    page of at most 100 associated PRs. A matching PR on page 2 was missed
    and no status was minted for a valid Ready PR."""
    page1 = [pr(number=1000 + i, head={"sha": "c" * 40, "ref": "fix/ci", "repo": {"full_name": REPO}})
             for i in range(100)]
    fake = FakeApi(assoc_pages=[page1, [pr()]])
    assert decide_with(fake)["state"] == "success"


def test_C08_missing_fields_are_rejected():
    # Job without a name matches no required job.
    copy = jobs()
    del copy[0]["name"]
    assert pub.evaluate(source(), copy, set())["state"] == "error"
    # Job without a conclusion is not success.
    copy = jobs()
    del copy[0]["conclusion"]
    assert pub.evaluate(source(), copy, set())["state"] == "failure"
    # Step without a conclusion is not proven.
    copy = jobs()
    del copy[1]["steps"][0]["conclusion"]
    assert pub.evaluate(source(), copy, set())["state"] == "error"
    # Newest run without an id is malformed.
    bad_run = run_record()
    del bad_run["id"]
    with pytest.raises(ValueError, match="malformed"):
        decide_with(FakeApi(runs_pages=[[bad_run]]))
    # Associated PR without a number is malformed.
    bad_pr = pr()
    del bad_pr["number"]
    with pytest.raises(ValueError, match="malformed"):
        decide_with(FakeApi(assoc_pages=[[bad_pr]]))


def test_C09_wrong_typed_provider_objects_do_not_publish(tmp_path):
    """REGRESSION (pre-repair): wrong-typed provider objects raised
    uncaught AttributeError/TypeError out of main() instead of the designed
    no-publication path (exit 0, state None, no POST)."""
    cases = {
        "assoc base is null": FakeApi(assoc_pages=[[pr(base=None)]]),
        "assoc head is null": FakeApi(assoc_pages=[[pr(head=None)]]),
        "current base is a string": FakeApi(current=pr(base="main")),
        "job record is a string": FakeApi(jobs_pages=[["not-a-dict"] + jobs()]),
        "run created_at is an int": FakeApi(runs_pages=[[
            run_record(run_id=RUN_ID, attempt=ATTEMPT, created_at=12345),
            run_record(run_id=RUN_ID + 1, attempt=1, created_at="2026-11-08T20:10:00Z"),
        ]]),
        "event repository is a string": None,  # handled by src override below
    }
    for name, fake in cases.items():
        if fake is None:
            code, out, posts, _ = run_main(
                tmp_path, FakeApi(), src=source(repository="not-a-dict"))
        else:
            code, out, posts, _ = run_main(tmp_path, fake)
        assert code == 0, name
        assert out is not None and out["state"] is None, name
        assert posts == [], name


def test_C10_job_belongs_to_wrong_run_is_error():
    copy = jobs()
    copy[0]["run_id"] = 999
    assert decide_with(FakeApi(jobs_pages=[copy]))["state"] == "error"


def test_C11_incomplete_job_status_with_success_conclusion_is_error():
    """REGRESSION (pre-repair success): a required job reporting
    conclusion=success while status=in_progress was trusted on its
    conclusion alone. Incomplete evidence must not mint success."""
    copy = jobs()
    next(j for j in copy if j["name"] == "Run aggregate validation")["status"] = "in_progress"
    assert pub.evaluate(source(), copy, set())["state"] == "error"


def test_C12_incomplete_step_status_with_success_conclusion_is_error():
    copy = jobs()
    job = next(j for j in copy if j["name"] == "Run aggregate validation")
    job["steps"][0]["status"] = "queued"
    assert pub.evaluate(source(), copy, set())["state"] == "error"


def test_C13_duplicate_job_across_pages_is_error():
    page1 = jobs() + [
        dict(id=1000 + i, run_id=RUN_ID, run_attempt=ATTEMPT, name=f"Filler-{i}",
             conclusion="success", status="completed", steps=[]) for i in range(96)
    ]
    assert len(page1) == 100
    page2 = [jobs()[0]]
    assert decide_with(FakeApi(jobs_pages=[page1, page2]))["state"] == "error"


def test_C14_authority_file_on_second_changed_files_page_is_error():
    page1 = [{"filename": f"src/f{i}.py"} for i in range(100)]
    page2 = [{"filename": "scripts/agent_os_trusted_status_publisher.py"}]
    assert decide_with(FakeApi(files_pages=[page1, page2]))["state"] == "error"


def test_C15_files_payload_malformed_is_rejected():
    with pytest.raises(ValueError, match="malformed"):
        decide_with(FakeApi(files_pages=[[{"filename": 42}]]))
    with pytest.raises(ValueError, match="malformed"):
        with patch.object(pub, "api", side_effect=lambda e: {"files": []} if "/files" in e else FakeApi()(e)):
            pub.decide({"workflow_run": source()}, REPO)


# ---------------------------------------------------------------------------
# D. Unauthorized execution and authority changes
# ---------------------------------------------------------------------------

def test_D01_fork_pr_head_repo_is_no_publish():
    bad = pr(head={"sha": SHA, "ref": "fix/ci", "repo": {"full_name": "someone/agent-os"}})
    assert decide_with(FakeApi(assoc_pages=[[bad]]))["state"] is None


def test_D02_renamed_authority_file_is_error():
    files = [[{"filename": "src/safe.py",
               "previous_filename": "scripts/agent_os_trusted_status_publisher.py"}]]
    assert decide_with(FakeApi(files_pages=files))["state"] == "error"


def test_D03_root_conftest_is_authority():
    """REGRESSION (pre-repair success): a repo-root conftest.py escaped
    touches_authority -- it is neither tests/conftest.py, nor does it end
    with '/conftest.py'. Pytest loads ancestor conftest.py files, so a root
    collection hook is the same authority class as any other conftest.py."""
    assert pub.touches_authority({"conftest.py"})
    assert pub.evaluate(source(), jobs(), {"conftest.py"})["state"] == "error"


def test_D04_publisher_never_reads_artifacts_or_executes_pr_code():
    src_text = (ROOT / "scripts/agent_os_trusted_status_publisher.py").read_text()
    assert "importlib" not in src_text
    assert "exec(" not in src_text and "eval(" not in src_text
    assert "download-artifact" not in src_text
    assert src_text.count("subprocess.run") == 2  # api() read + status POST only
    workflow = (ROOT / ".github/workflows/agent-os-trusted-status-pilot.yml").read_text()
    assert "download-artifact" not in workflow
    assert "actions/checkout@" in workflow
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow


def test_D05_composite_action_and_validator_prefix_changes_are_error():
    for path in ("scripts/agent_os_ci_validation.py",
                 ".github/actions/setup-python-dev/action.yml",
                 "scripts/agent_os_remote_validation/main_health.py"):
        assert pub.evaluate(source(), jobs(), {path})["state"] == "error", path


def test_D06_fork_head_repo_in_current_read_is_no_publish():
    fake = FakeApi(current=pr(head={"sha": SHA, "ref": "fix/ci", "repo": {"full_name": "someone/agent-os"}}))
    assert decide_with(fake)["state"] is None


# ---------------------------------------------------------------------------
# E. Publication and GitHub status semantics (real main --publish path)
# ---------------------------------------------------------------------------

def test_E01_publish_success_exact(tmp_path):
    code, out, posts, _ = run_main(tmp_path, FakeApi())
    assert code == 0
    assert out == {"context": pub.CONTEXT, "description": "Trusted pilot: source jobs and steps passed on exact PR head", "state": "success"}
    assert len(posts) == 1
    assert post_cmd(posts) == [
        "gh", "api", "-X", "POST", f"repos/{REPO}/statuses/{SHA}",
        "-f", f"context={pub.CONTEXT}",
        "-f", "state=success",
        "-f", "description=Trusted pilot: source jobs and steps passed on exact PR head",
        "-f", f"target_url=https://github.com/{REPO}/actions/runs/{RUN_ID}",
    ]


def test_E02_publish_failure_on_source_failure(tmp_path):
    code, out, posts, _ = run_main(tmp_path, FakeApi(), src=source(conclusion="failure"))
    assert code == 1
    assert out["state"] == "failure"
    assert len(posts) == 1 and "state=failure" in post_cmd(posts)


def test_E03_publish_error_on_missing_required_job(tmp_path):
    copy = jobs()[:-1]
    code, out, posts, _ = run_main(tmp_path, FakeApi(jobs_pages=[copy]))
    assert code == 1
    assert out["state"] == "error"
    assert len(posts) == 1 and "state=error" in post_cmd(posts)


def test_E04_no_publish_on_non_pr_event(tmp_path):
    code, out, posts, _ = run_main(tmp_path, FakeApi(), src=source(event="push"))
    assert code == 0
    assert out["state"] is None
    assert posts == []


def test_E05_no_publish_when_provider_unavailable(tmp_path):
    fake = FakeApi(raise_on={"/jobs?": RuntimeError("provider down")})
    code, out, posts, _ = run_main(tmp_path, fake)
    assert code == 0
    assert out["state"] is None
    assert posts == []


def test_E06_publication_rejected_is_system_exit(tmp_path):
    code, out, posts, _ = run_main(tmp_path, FakeApi(), post_rc=1)
    assert code == "Provider rejected trusted status publication"
    assert out["state"] == "success"
    assert len(posts) == 1  # PUBLICATION_FAILED: attempted once, refused


def test_E07_no_publish_on_stale_attempt(tmp_path):
    runs = [run_record(run_id=RUN_ID + 1, attempt=1, created_at="2026-11-08T20:10:00Z")]
    code, out, posts, _ = run_main(tmp_path, FakeApi(runs_pages=[runs]))
    assert code == 0
    assert out["state"] is None
    assert posts == []


def test_E08_exit_zero_without_publication_is_not_success(tmp_path):
    # Provider error + --publish: exit 0, but the printed state is None and
    # no status was created. Exit 0 here means "nothing minted", not "green".
    fake = FakeApi(raise_on={"/pulls/42/files?": RuntimeError("provider down")})
    code, out, posts, _ = run_main(tmp_path, fake)
    assert code == 0
    assert out == {"context": pub.CONTEXT,
                   "description": "Provider evidence unavailable: no status published",
                   "state": None}
    assert posts == []


def test_E09_pending_is_never_a_published_state():
    src_text = (ROOT / "scripts/agent_os_trusted_status_publisher.py").read_text()
    assert '"pending"' not in src_text
    states = set()
    for outcome in (
        pub.evaluate(source(), jobs(), set()),
        pub.evaluate(source(conclusion="failure"), jobs(), set()),
        pub.evaluate(source(), jobs()[:-1], set()),
        decide_with(FakeApi()),
    ):
        states.add(outcome["state"])
    assert states <= {"success", "failure", "error", None}
    assert "pending" not in states


def test_C16_single_run_malformed_timestamp_fails_closed(tmp_path):
    """A single matching run must validate created_at before trusted publication."""
    for bad in (None, 12345, "", "not-a-date", "2026-99-08T20:00:00Z",
                "2026-11-08T20:00:00", "2026-11-08T20:00:00+00:00"):
        fake = FakeApi(runs_pages=[[run_record(created_at=bad)]])
        with pytest.raises(ValueError, match="created_at is malformed"):
            decide_with(fake)
        code, out, posts, _ = run_main(
            tmp_path, FakeApi(runs_pages=[[run_record(created_at=bad)]]))
        assert code == 0 and out["state"] is None and posts == [], repr(bad)


def test_C17_malformed_older_run_cannot_be_ignored(tmp_path):
    """Even a run that cannot win the ordering must have valid provenance."""
    valid = run_record(created_at="2026-11-08T20:00:00Z")
    bad = run_record(run_id=RUN_ID + 1, attempt=1, created_at="invalid")
    fake = FakeApi(runs_pages=[[valid, bad]])
    with pytest.raises(ValueError, match="created_at is malformed"):
        decide_with(fake)
    code, out, posts, _ = run_main(tmp_path, FakeApi(runs_pages=[[valid, bad]]))
    assert code == 0 and out["state"] is None and posts == []


def test_C18_timestamp_ordering_is_chronological():
    """Validated ISO UTC timestamps retain the existing newest-run semantics."""
    older = run_record(created_at="2026-11-08T20:00:00Z")
    newer = run_record(run_id=RUN_ID + 1, attempt=1,
                       created_at="2026-11-08T21:00:00Z")
    assert decide_with(FakeApi(runs_pages=[[older, newer]]))["state"] is None
