"""No-network adversarial controls for the isolated trusted status decision."""
import importlib.util
import json
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


def test_critical_validation_source_edit_never_passes():
    for path in pub.AUTHORITY_PATHS | {"scripts/agent_os_ci_new.py", "scripts/agent_os_remote_validation/new.py", "tests/conftest.py", "08_Tooling/foo/tests/conftest.py", "pytest.ini", "pyproject.toml", "07_Agent_Tests/validate-repo-structure.sh"}:
        assert pub.evaluate(source(),jobs(),{path})['state']=='error'


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
