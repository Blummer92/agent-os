"""No-network adversarial controls for the isolated trusted status decision."""
import importlib.util
import json
import re
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publisher', ROOT/'scripts/agent_os_trusted_status_publisher.py')
pub = importlib.util.module_from_spec(SPEC)
sys.modules['publisher'] = pub
SPEC.loader.exec_module(pub)

REPO = 'Blummer92/agent-os'
SHA = 'a' * 40
RUN_ID = 123
ATTEMPT = 2
WORKFLOW_ID = 445


def source(**fields):
    j = dict(id=RUN_ID, run_attempt=ATTEMPT, workflow_id=WORKFLOW_ID,
             status='completed', conclusion='success', head_sha=SHA,
             head_branch='fix/ci', path=pub.SOURCE_PATH, event='pull_request',
             repository={'full_name':REPO})
    j.update(fields)
    return j


def pr(**fields):
    p = dict(number=42,state='open',draft=False,
             base={'ref':'main', 'repo':{'full_name':REPO}},
             head={'sha':SHA, 'ref':'fix/ci', 'repo':{'full_name':REPO}})
    p.update(fields)
    return p


def jobs():
    result=[]
    for n,name in enumerate(pub.JOBS):
        steps=[{'name': x,'conclusion':'success'} for x in pub.REQUIRED_STEPS.get(name, ())]
        result.append(dict(id=n+1,run_id=RUN_ID,run_attempt=ATTEMPT,name=name,conclusion='success',steps=steps))
    return result


def test_positive_result_requires_successful_jobs_and_steps():
    assert pub.evaluate(source(), jobs(), set())['state']=='success'


def _reuse_jobs():
    copy = jobs()
    aggregate = next(j for j in copy if j["name"] == "Run aggregate validation")
    aggregate["steps"] = [
        {"name": name, "conclusion": conclusion, "status": "completed"}
        for name, conclusion in pub.REUSE_STEP_CONCLUSIONS.items()
    ]
    return copy


def test_ready_reuse_is_pending_not_trusted_success():
    assert pub.evaluate(source(), _reuse_jobs(), set())["state"] == "pending"
    assert pub.evaluate(source(), _reuse_jobs(), {pub.SOURCE_PATH})["state"] == "pending"


def test_ready_reuse_requires_complete_unambiguous_provider_step_shape():
    for name in pub.REUSE_STEP_CONCLUSIONS:
        for mode in ("missing", "duplicate", "wrong_conclusion", "wrong_status"):
            copy = _reuse_jobs()
            aggregate = next(j for j in copy if j["name"] == "Run aggregate validation")
            steps = aggregate["steps"]
            target = next(s for s in steps if s["name"] == name)
            if mode == "missing":
                steps.remove(target)
            elif mode == "duplicate":
                steps.append(target.copy())
            elif mode == "wrong_conclusion":
                target["conclusion"] = "failure" if target["conclusion"] == "success" else "success"
            else:
                target["status"] = "in_progress"
            assert pub.evaluate(source(), copy, set())["state"] == "error", (name, mode)


def test_ready_reuse_rejects_extra_and_malformed_provider_entries():
    for step in (
        {"name": "Unexpected successful step", "conclusion": "success", "status": "completed"},
        {"name": "Unexpected failed step", "conclusion": "failure", "status": "completed"},
        {"name": "Unexpected skipped step", "conclusion": "skipped", "status": "completed"},
        {"name": "Post Check out repository", "conclusion": "success", "status": "completed"},
        {"name": "Unexpected step"},
        {"conclusion": "success"},
        {"name": None, "conclusion": "success"},
        {"name": ["not a name"], "conclusion": "success"},
        {"name": "Unexpected step", "conclusion": None},
        {"name": "Unexpected step", "conclusion": ["success"]},
        None,
        "not a step",
    ):
        copy = _reuse_jobs()
        aggregate = next(j for j in copy if j["name"] == "Run aggregate validation")
        aggregate["steps"].append(step)
        assert pub.evaluate(source(), copy, set())["state"] == "error", step


def test_ready_reuse_rejects_corrupted_required_step_fields():
    for field, value in (("name", None), ("name", []), ("conclusion", None), ("conclusion", [])):
        copy = _reuse_jobs()
        aggregate = next(j for j in copy if j["name"] == "Run aggregate validation")
        aggregate["steps"][0][field] = value
        assert pub.evaluate(source(), copy, set())["state"] == "error", (field, value)


def test_direct_execution_rejects_malformed_provider_step_instead_of_raising():
    for job_name in pub.REQUIRED_STEPS:
        for bad_step in (None, "not a step", {"name": [], "conclusion": "success"}):
            copy = jobs()
            job = next(j for j in copy if j["name"] == job_name)
            job["steps"].append(bad_step)
            assert pub.evaluate(source(), copy, set())["state"] == "error", (job_name, bad_step)


def test_malformed_job_entries_fail_closed_instead_of_raising():
    for bad_job in (None, "not a job", 42, ["Run validation plan"]):
        appended = jobs()
        appended.append(bad_job)
        assert pub.evaluate(source(), appended, set())["state"] == "error", bad_job
        replaced = jobs()
        replaced[0] = bad_job
        assert pub.evaluate(source(), replaced, set())["state"] == "error", bad_job


def test_reuse_steps_cover_every_named_aggregate_workflow_step():
    workflow = (ROOT / ".github/workflows/agent-os-validation.yml").read_text()
    aggregate = workflow.split("\n  validate:\n", 1)[1]
    aggregate = re.split(r"(?m)^  [A-Za-z0-9_-]+:\s*$", aggregate, maxsplit=1)[0]
    named_steps = {
        line.removeprefix("      - name: ").strip()
        for line in aggregate.splitlines()
        if line.startswith("      - name: ")
    }
    synthetic_steps = {"Set up job", "Complete job"}
    assert set(pub.REUSE_STEP_CONCLUSIONS) == named_steps | synthetic_steps


def test_ready_reuse_cannot_hide_failed_source_or_required_jobs():
    assert pub.evaluate(source(conclusion="failure"), _reuse_jobs(), set())["state"] == "failure"
    for name in pub.JOBS:
        copy = _reuse_jobs()
        next(j for j in copy if j["name"] == name)["conclusion"] = "failure"
        assert pub.evaluate(source(), copy, set())["state"] == "failure", name


def test_ready_reuse_does_not_accept_unproven_mixed_execution():
    copy = _reuse_jobs()
    aggregate = next(j for j in copy if j["name"] == "Run aggregate validation")
    next(s for s in aggregate["steps"] if s["name"] == "Run aggregate validation")["conclusion"] = "success"
    assert pub.evaluate(source(), copy, set())["state"] == "error"


def test_non_success_source():
    assert pub.evaluate(source(conclusion='failure'), jobs(), set())['state']=='failure'


def test_missing_or_skipped_job():
    for name in pub.JOBS:
        assert pub.evaluate(source(), [j for j in jobs() if j['name']!=name], set())['state']=='error'
        copy=jobs(); next(j for j in copy if j['name']==name)['conclusion']='skipped'
        assert pub.evaluate(source(),copy,set())['state']=='failure'


def test_duplicate_jobs_are_rejected():
    copy=jobs();copy.append(copy[0].copy())
    assert pub.evaluate(source(),copy,set())['state']=='error'


def test_missing_skipped_or_duplicate_required_step():
    for name,step_names in pub.REQUIRED_STEPS.items():
        for step in step_names:
            for mode in ('missing','skipped','duplicate'):
                copy=jobs();part=next(j for j in copy if j['name']==name)
                if mode=='missing': part['steps']=[s for s in part['steps'] if s['name']!=step]
                if mode=='skipped': next(s for s in part['steps'] if s['name']==step)['conclusion']='skipped'
                if mode=='duplicate': part['steps'].append(next(s for s in part['steps'] if s['name']==step).copy())
                assert pub.evaluate(source(),copy,set())['state']=='error', (name, step, mode)


def test_ckr6_gate_module_is_not_self_certifying():
    for module in ("ckr6_mutation_gate.py", "ckr6_gate_revalidate.py"):
        path = (
            "08_Tooling/agent-os-execution-service/src/"
            "agent_os_execution_service/" + module
        )
        assert path in pub.AUTHORITY_PATHS
        assert pub.touches_authority({path})
        outcome = pub.evaluate(source(), jobs(), {path})
        assert outcome["state"] == "pending"
        assert "not certified" in outcome["description"]


def test_critical_validation_source_edit_never_passes():
    for path in pub.AUTHORITY_PATHS | {"scripts/agent_os_ci_new.py", "scripts/agent_os_remote_validation/new.py", "tests/conftest.py", "08_Tooling/foo/tests/conftest.py", "pytest.ini", "pyproject.toml", "07_Agent_Tests/validate-repo-structure.sh"}:
        assert pub.evaluate(source(),jobs(),{path})['state']=='pending'


def fake_api(endpoint):
    if f'/commits/{SHA}/pulls?' in endpoint: return [pr()]
    if endpoint.endswith('/pulls/42'): return pr()
    if '/actions/workflows/' in endpoint: return {'workflow_runs':[dict(id=RUN_ID,run_attempt=ATTEMPT,created_at='2026-11-08T20:00:00Z',head_sha=SHA,event='pull_request',path=pub.SOURCE_PATH)]}
    if '/pulls/42/files?' in endpoint: return [{'filename':'src/safe.py'}]
    if '/jobs?' in endpoint: return {'jobs':jobs()}
    raise AssertionError('unexpected API '+endpoint)


def decide(s=None, api_fn=fake_api):
    with patch.object(pub,'api',side_effect=api_fn):
        return pub.decide({'workflow_run':s or source()},REPO)


def test_privileged_checkout_action_is_pinned_to_verified_release_commit():
    # Verified against actions/checkout refs/tags/v7.0.1 on GitHub on 2026-11-08.
    workflow = (ROOT / '.github/workflows/agent-os-trusted-status-pilot.yml').read_text()
    assert 'uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' in workflow
    assert 'uses: actions/checkout@v7' not in workflow
    assert 'persist-credentials: false' in workflow
    assert 'ref: ${{ github.event.repository.default_branch }}' in workflow


def test_workflow_installed_dependency_manifests_are_authority():
    # Each path is directly consumed by the validation workflow, regardless
    # of whether the changed source code and its tests are otherwise green.
    paths = {
        'requirements-dev.txt',
        '08_Tooling/workflow-scheduler/requirements.txt',
        '08_Tooling/instructional-materials-coach/pyproject.toml',
        '08_Tooling/notion-navigation-client/pyproject.toml',
        '08_Tooling/instructional-materials-coach/picture-perfect-coach/package.json',
        '08_Tooling/instructional-materials-coach/picture-perfect-coach/package-lock.json',
        '.github/actions/setup-python-dev/action.yml',
    }
    for path in paths:
        assert pub.touches_authority({path}), path
        assert pub.evaluate(source(), jobs(), {path})['state'] == 'pending', path


def test_unlisted_build_and_workflow_authority_configs_fail_closed():
    for path in (
        '08_Tooling/future-tool/requirements-test.txt',
        '08_Tooling/future-tool/pyproject.toml',
        '08_Tooling/future-tool/setup.py',
        '08_Tooling/future-tool/tox.ini',
        '08_Tooling/future-tool/package.json',
        '08_Tooling/future-tool/npm-shrinkwrap.json',
        '08_Tooling/future-tool/pnpm-lock.yaml',
        '08_Tooling/future-tool/yarn.lock',
        '08_Tooling/future-tool/uv.lock',
        '.github/workflows/another-validation.yml',
    ):
        assert pub.evaluate(source(), jobs(), {path})['state'] == 'pending', path
    assert pub.evaluate(source(), jobs(), {'src/domain_logic.py'})['state'] == 'success'
    assert pub.evaluate(source(), jobs(), {'docs/requirements-notes.md'})['state'] == 'success'


def test_source_event_has_to_be_actual_pr():
    assert decide(source(event='workflow_dispatch'))['state'] is None
    assert decide(source(status='in_progress'))['state'] is None
    assert decide(source(path='other.yml'))['state'] is None
    assert decide(source(repository={'full_name':'other/repo'}))['state'] is None
    assert decide(source(head_sha='not-a-sha'))['state'] is None
    assert decide(source(run_attempt=0))['state'] is None


def test_exact_ready_pr_binding():
    assert decide()['state']=='success'
    for bad in (pr(draft=True),pr(state='closed'),pr(head={'sha':'b'*40,'ref':'fix/ci','repo':{'full_name':REPO}})):
        def fake(endpoint):
            if f'/commits/{SHA}/pulls?' in endpoint: return [bad]
            return fake_api(endpoint)
        assert decide(api_fn=fake)['state'] is None


def test_pr_turning_draft_after_lookup_is_skipped():
    def fake(endpoint):
        if endpoint.endswith('/pulls/42'):return pr(draft=True)
        return fake_api(endpoint)
    assert decide(api_fn=fake)['state'] is None


def test_current_pr_branch_and_base_revalidated_after_association():
    for bad in (pr(base={'ref':'release','repo':{'full_name':REPO}}),
                pr(head={'sha':SHA,'ref':'renamed','repo':{'full_name':REPO}}),
                pr(base={'ref':'main','repo':{'full_name':'another/repo'}})):
        def fake(endpoint):
            if endpoint.endswith('/pulls/42'): return bad
            return fake_api(endpoint)
        assert decide(api_fn=fake)['state'] is None


def test_empty_changed_file_set_cannot_establish_authority():
    def fake(endpoint):
        if '/pulls/42/files?' in endpoint: return []
        return fake_api(endpoint)
    try: decide(api_fn=fake)
    except ValueError: pass
    else: raise AssertionError('empty changed-file set accepted')


def test_stale_attempt_is_not_written():
    def fake(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs':[dict(id=RUN_ID+1,run_attempt=1,created_at='2026-11-08T20:10:00Z',head_sha=SHA,event='pull_request',path=pub.SOURCE_PATH)]}
        return fake_api(endpoint)
    assert decide(api_fn=fake)['state'] is None


def test_missing_or_unverifiable_provider_records():
    def fake(endpoint):
        if '/jobs?' in endpoint: return {'jobs':jobs()[:-1]}
        return fake_api(endpoint)
    assert decide(api_fn=fake)['state']=='error'
    def malformed(endpoint):
        if '/jobs?' in endpoint:return {'jobs':{'forged':True}}
        return fake_api(endpoint)
    try: decide(api_fn=malformed)
    except ValueError: pass
    else: raise AssertionError('malformed jobs accepted')


def test_wrong_attempt_rejected_even_if_all_jobs_green():
    def fake(endpoint):
        if '/jobs?' in endpoint:
            j=jobs(); j[0]['run_attempt']=1
            return {'jobs':j}
        return fake_api(endpoint)
    assert decide(api_fn=fake)['state']=='error'


def test_no_network_or_publish_on_non_pr_event(tmp_path):
    path=tmp_path/'event.json';path.write_text(json.dumps({'workflow_run':source(event='push')}))
    with patch.object(pub,'api',side_effect=AssertionError('API should not be called')) as api, \
         patch.object(pub.subprocess,'run',side_effect=AssertionError('publish not allowed')) as run:
        assert pub.main(['--event',str(path),'--repository',REPO,'--publish'])==0
        api.assert_not_called();run.assert_not_called()


def test_authority_disposition_is_explicitly_non_certifying():
    changed = {'.github/workflows/agent-os-governed-invocation.yml'}
    outcome = pub.evaluate(source(), jobs(), changed)
    assert outcome['state'] == 'pending'
    assert outcome['state'] != 'success'
    assert outcome['context'] == pub.CONTEXT
    assert 'not certified' in outcome['description']


def test_authority_change_does_not_mask_actual_failed_or_missing_evidence():
    changed = {pub.SOURCE_PATH}
    for source_conclusion in ('failure', 'cancelled', 'skipped', None):
        assert pub.evaluate(source(conclusion=source_conclusion), jobs(), changed)['state'] == 'failure'
    for name in pub.JOBS:
        missing = [job for job in jobs() if job['name'] != name]
        assert pub.evaluate(source(), missing, changed)['state'] == 'error'
        skipped = jobs()
        next(job for job in skipped if job['name'] == name)['conclusion'] = 'skipped'
        assert pub.evaluate(source(), skipped, changed)['state'] == 'failure'
    duplicate = jobs()
    duplicate.append(duplicate[0].copy())
    assert pub.evaluate(source(), duplicate, changed)['state'] == 'error'
    for name, required_steps in pub.REQUIRED_STEPS.items():
        for step in required_steps:
            missing_step = jobs()
            job = next(job for job in missing_step if job['name'] == name)
            job['steps'] = [s for s in job['steps'] if s['name'] != step]
            assert pub.evaluate(source(), missing_step, changed)['state'] == 'error'
            skipped_step = jobs()
            job = next(job for job in skipped_step if job['name'] == name)
            next(s for s in job['steps'] if s['name'] == step)['conclusion'] = 'skipped'
            assert pub.evaluate(source(), skipped_step, changed)['state'] == 'error'


def test_pending_requires_current_exact_pr_and_attempt():
    def changed_files_api(endpoint):
        if '/pulls/42/files?' in endpoint:
            return [{'filename': '.github/workflows/agent-os-governed-invocation.yml'}]
        return fake_api(endpoint)

    assert decide(api_fn=changed_files_api)['state'] == 'pending'

    def stale_attempt_api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': [dict(
                id=RUN_ID + 1, run_attempt=1,
                created_at='2026-11-08T20:10:00Z',
                head_sha=SHA, event='pull_request', path=pub.SOURCE_PATH)]}
        return changed_files_api(endpoint)

    assert decide(api_fn=stale_attempt_api)['state'] is None


def test_publisher_emits_pending_not_success_for_authority_change(tmp_path):
    event_file = tmp_path / 'event.json'
    event_file.write_text(json.dumps({'workflow_run': source()}))

    def changed_files_api(endpoint):
        if '/pulls/42/files?' in endpoint:
            return [{'filename': '.github/workflows/agent-os-governed-invocation.yml'}]
        return fake_api(endpoint)

    completed = type('Completed', (), {'returncode': 0})()
    with patch.object(pub, 'api', side_effect=changed_files_api), \
         patch.object(pub.subprocess, 'run', return_value=completed) as posted:
        assert pub.main(['--event', str(event_file), '--repository', REPO, '--publish']) == 0
    posted.assert_called_once()
    command = posted.call_args.args[0]
    assert 'state=pending' in command
    assert 'state=success' not in command
    assert f'context={pub.CONTEXT}' in command
    assert f'repos/{REPO}/statuses/{SHA}' in command


def test_ckr6_gate_transitive_inputs_are_not_self_certifying():
    # The pull_request gate job installs and executes these packages from the
    # PR head. A PR modifying any of them (the gate's trusted-read layer, the
    # request-envelope parser, or any module they import transitively) changes
    # the gate's decision inputs and must stay non-certifying.
    representative = (
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/ckr6_github_reader.py",
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/ckr6_github_bridge.py",
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_facade.py",
        "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/coding_knowledge_selection.py",
        "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/single_issue_runtime.py",
        "scripts/agent_os_candidate_packet/compiler.py",
        "scripts/agent_os_execution_capabilities/models.py",
        "scripts/agent_os_execution_checkpoint/store.py",
        "scripts/agent_os_execution_interface/continuation_driver.py",
        "scripts/agent_os_github_git_objects/models.py",
        "scripts/agent_os_github_issue_provider/provider.py",
        "scripts/agent_os_issue_acceptance/policy.py",
    )
    for path in representative:
        assert pub.touches_authority({path}), path
        outcome = pub.evaluate(source(), jobs(), {path})
        assert outcome["state"] == "pending", (path, outcome)
        assert "not certified" in outcome["description"]


def test_ckr6_gate_import_closure_is_authority_covered(tmp_path):
    # Recompute the live import closure of both gate entry modules in a clean
    # interpreter and require every repo file it executes to be authority
    # covered. This fails (never skips) if a future dependency addition
    # reopens a self-certification path.
    import subprocess

    src_roots = (
        "08_Tooling/agent-os-execution-service/src",
        "08_Tooling/agent-memory-context-manager/src",
        "08_Tooling/workflow-scheduler/src",
        "08_Tooling/reusable-capability-registry/src",
        "src",
        ".",
    )
    env_pythonpath = ":".join(str(ROOT / r) for r in src_roots)
    program = (
        "import sys, os, json\n"
        "repo = os.path.abspath(sys.argv[1])\n"
        "import agent_os_execution_service.ckr6_mutation_gate\n"
        "import agent_os_execution_service.ckr6_gate_revalidate\n"
        "files = sorted({os.path.relpath(os.path.abspath(m.__file__), repo)\n"
        "    for m in sys.modules.values()\n"
        "    if getattr(m, '__file__', None)\n"
        "    and os.path.abspath(m.__file__).startswith(repo + os.sep)})\n"
        "print(json.dumps(files))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program, str(ROOT)],
        env={"PYTHONPATH": env_pythonpath, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    closure = json.loads(proc.stdout.strip().splitlines()[-1])
    # The closure must really contain the gate chain; a trivially empty or
    # broken closure can never satisfy this guard.
    for required in (
        "ckr6_mutation_gate.py", "ckr6_gate_revalidate.py",
        "ckr6_github_bridge.py", "ckr6_github_reader.py",
    ):
        assert any(p.endswith("/" + required) for p in closure), required
    assert len(closure) >= 100, len(closure)
    uncovered = [p for p in closure if not pub.touches_authority({p})]
    assert uncovered == [], uncovered
