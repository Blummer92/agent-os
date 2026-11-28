"""Offline closure execution and readback controls from the audit package."""
import test_3489_governed_closure_dispatch as fixture
import test_3489_session_closure_adapter as session_fixture

from scripts.agent_os_issue_acceptance import github_closure_dispatch as dispatch
from scripts.agent_os_issue_acceptance import session_closure_adapter as session


def test_session_new_ready_label_prevents_full_verification():
    setup = session_fixture.Setup()
    setup.snapshot = session_fixture.snapshot(lifecycle_labels=())
    plan = setup.make_plan()
    transport = session_fixture.FakeTransport(read_overrides={3: {'labels': ['status:ready']}})
    transport.labels = []
    result = session.execute_plan(plan, transport)
    assert result['status'] == 'closed-verified-label-reconciliation-required'
    assert len([x for x in transport.ops if x[0] == 'close']) == 1


def test_normalized_malformed_write_response_is_reconciled(monkeypatch):
    fake = fixture.FakeGitHub()
    fake.add(100)
    class Requester:
        def requestJsonAndCheck(self, method, path, **kwargs):
            _status, payload = fake(method, path, kwargs.get('input'))
            return (None if method == 'PATCH' else {}), payload
    class Client:
        requester = Requester()
    monkeypatch.setattr(dispatch, 'build_token_client', lambda *a, **kw: Client())
    transport = dispatch.github_api_transport('offline-test-placeholder')
    result = dispatch.run_closure_dispatch((fixture.request_obj(100),), transport)[0]
    assert result['status'] == 'closed-verified-after-uncertain-write'
    assert result['readback_verified'] is True
    assert len(fake.patch_calls) == 1
    assert fake.get_counts[100] >= 3


def test_concurrent_issue_body_change_blocks_all_closure_writes():
    fake = fixture.FakeGitHub()
    fake.add(100)
    fake.drift_on_first_read.add(100)
    result = dispatch.run_closure_dispatch((fixture.request_obj(100),), fake)[0]
    assert result['status'] == 'blocked'
    assert fake.patch_calls == []
    assert fake.post_calls == []
    assert fake.delete_calls == []

def test_ordinary_unrelated_comment_does_not_satisfy_receipt():
    plan = session_fixture.Setup().make_plan()
    transport = session_fixture.FakeTransport()
    transport.comments = ["An ordinary unrelated test note."]
    result = session.execute_plan(plan, transport)
    assert result["status"] == "closed-verified"
    assert transport.comments == ["An ordinary unrelated test note.", plan.comment_body]
    assert [op[0] for op in transport.write_ops()].count("post_comment") == 1


def test_existing_exact_comment_is_reused_during_authorized_recovery():
    plan = session_fixture.Setup().make_plan()
    transport = session_fixture.FakeTransport()
    transport.state, transport.state_reason = "closed", "completed"
    transport.comments = [plan.comment_body]
    result = session.execute_plan(plan, transport, recovery_authorized=True)
    assert result["status"] == "already-closed-recovered"
    assert [op[0] for op in transport.write_ops()] == ["remove_issue_label"]
