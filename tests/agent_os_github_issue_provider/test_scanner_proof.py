from __future__ import annotations

from dataclasses import fields

import scripts.agent_os_github_issue_provider.scanner_proof as proof


class Secrets:
    def private_key(self) -> str:
        return "test-private-key"


class SnapshotReader:
    def __init__(self, snapshot=None, *, complete=True, terminal=True, installation_id=proof.INSTALLATION_ID):
        self.snapshot = snapshot or {
            "repository_selection": "selected",
            "repositories": [{"id": 99, "full_name": proof.REPOSITORY}],
        }
        self.complete = complete
        self.terminal = terminal
        self.installation_id = installation_id
        self.clients = []

    def read(self, client):
        self.clients.append(client)
        return self.snapshot, self.complete, self.terminal, self.installation_id


class FakeClient:
    def __init__(self, payload=None):
        self.requester = self
        self.calls = []
        self.payload = [] if payload is None else payload

    def requestJsonAndCheck(self, method, url, parameters, headers):
        self.calls.append((method, url, dict(parameters)))
        return {}, self.payload


def _item(number, **extra):
    item = {
        "number": number,
        "title": f"record {number}",
        "state": "open",
        "body": "bounded fixture",
        "html_url": f"https://github.com/Blummer92/agent-os/issues/{number}",
        "created_at": "2026-09-13T20:00:00Z",
        "updated_at": "2026-09-13T20:01:00Z",
        "labels": [],
    }
    item.update(extra)
    return item


def test_fixed_contract_has_no_caller_selected_scope(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(proof, "build_installation_client", lambda config, secrets: client)
    reader = SnapshotReader()
    result = proof.run_scanner_proof(secrets=Secrets(), installation_snapshot_reader=reader)
    assert result.status == "success"
    assert result.repository == "Blummer92/agent-os"
    assert (result.page, result.per_page, result.state) == (1, 30, "open")
    assert result.same_invocation_identity is True
    assert reader.clients == [client]
    assert client.calls == [("GET", "/repos/Blummer92/agent-os/issues", {"page": 1, "per_page": 30, "state": "open"})]


def test_mixed_issue_and_pull_request_page_counts_only_issues(monkeypatch):
    client = FakeClient([_item(10), _item(11, pull_request={"url": "redacted"})])
    monkeypatch.setattr(proof, "build_installation_client", lambda config, secrets: client)
    result = proof.run_scanner_proof(
        secrets=Secrets(), installation_snapshot_reader=SnapshotReader()
    )
    assert result.status == "success"
    assert result.item_count == 1
    assert result.next_page is None
    assert result.terminal_page_proven is True
    assert len(client.calls) == 1


def test_duplicate_case_colliding_identity_fails_closed(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(proof, "build_installation_client", lambda config, secrets: client)
    reader = SnapshotReader({
        "repository_selection": "selected",
        "repositories": [
            {"id": 99, "full_name": "Blummer92/agent-os"},
            {"id": 100, "full_name": "blummer92/AGENT-OS"},
        ],
    })
    result = proof.run_scanner_proof(secrets=Secrets(), installation_snapshot_reader=reader)
    assert (result.status, result.reason) == ("blocked", "repository:duplicate")
    assert client.calls == []


def test_incomplete_installation_snapshot_fails_before_issue_read(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(proof, "build_installation_client", lambda config, secrets: client)
    result = proof.run_scanner_proof(secrets=Secrets(), installation_snapshot_reader=SnapshotReader(complete=False))
    assert (result.status, result.reason) == ("blocked", "pagination:incomplete")
    assert client.calls == []


def test_evidence_shape_cannot_carry_sensitive_or_authorizing_fields():
    names = {field.name for field in fields(proof.ScannerProofEvidence)}
    forbidden = {"token", "authorization", "link", "headers", "url", "title", "body", "labels", "payload", "private_key"}
    assert names.isdisjoint(forbidden)
    result = proof.ScannerProofEvidence(status="blocked", reason="test")
    assert result.external_side_effects_performed is False
    assert result.production_state_mutated is False
    assert result.execution_authorized is False
    assert result.publication_authorized is False
    assert result.complete_scan_authorized is False
    assert result.automatic_retry is False


def test_client_transport_is_single_attempt():
    source = proof.run_scanner_proof.__code__.co_names
    assert "PyGithubRestTransport" in source
    assert proof.PAGE == 1
    assert proof.PER_PAGE == 30
