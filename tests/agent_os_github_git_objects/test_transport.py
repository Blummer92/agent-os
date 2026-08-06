from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests.exceptions
from scripts.agent_os_github_git_objects.models import GitTreeEntry, MutationState
from scripts.agent_os_github_git_objects.transport import (
    GitObjectTransportError,
    GithubException,
    PyGithubGitObjectTransport,
)

REPO = "Blummer92/agent-os"
BRANCH = "agent/test"
SHA = "a" * 40
TREE = "b" * 40
PARENT = "c" * 40
BLOB = "d" * 40


def transport_with(response) -> tuple[PyGithubGitObjectTransport, MagicMock]:
    client = MagicMock()
    client.requester.requestJsonAndCheck.return_value = ({"Status": "200 OK"}, response)
    return PyGithubGitObjectTransport(client), client


def test_get_ref_parses_exact_target() -> None:
    transport, client = transport_with({"ref": "refs/heads/agent/test", "object": {"sha": SHA}})
    result = transport.get_ref(REPO, BRANCH)
    assert result.commit_sha == SHA
    args, kwargs = client.requester.requestJsonAndCheck.call_args
    assert args[:2] == ("GET", f"/repos/{REPO}/git/ref/heads/agent%2Ftest")
    assert kwargs["headers"]["X-GitHub-Api-Version"] == "2026-03-10"


def test_get_commit_exposes_tree_and_parents() -> None:
    transport, _ = transport_with(
        {"sha": SHA, "tree": {"sha": TREE}, "parents": [{"sha": PARENT}]}
    )
    result = transport.get_commit(REPO, SHA)
    assert result.sha == SHA
    assert result.tree_sha == TREE
    assert result.parent_shas == (PARENT,)


@pytest.mark.parametrize(
    "payload",
    [
        {"sha": SHA, "parents": [{"sha": PARENT}]},
        {"sha": SHA, "tree": {}, "parents": [{"sha": PARENT}]},
        {"sha": SHA, "tree": {"sha": TREE}, "parents": "bad"},
    ],
)
def test_get_commit_rejects_incomplete_response(payload) -> None:
    transport, _ = transport_with(payload)
    with pytest.raises((GitObjectTransportError, ValueError)):
        transport.get_commit(REPO, SHA)


def test_get_tree_returns_only_supported_ordinary_blob_entries() -> None:
    transport, _ = transport_with(
        {
            "sha": TREE,
            "truncated": False,
            "tree": [
                {"path": "a.py", "mode": "100644", "type": "blob", "sha": BLOB},
                {"path": "script.sh", "mode": "100755", "type": "blob", "sha": "e" * 40},
                {"path": "folder", "mode": "040000", "type": "tree", "sha": "f" * 40},
            ],
        }
    )
    result = transport.get_tree(REPO, TREE, recursive=True)
    assert result.entries == (GitTreeEntry("a.py", "100644", "blob", BLOB),)
    assert result.truncated is False


def test_get_blob_validates_size_and_identity() -> None:
    transport, _ = transport_with(
        {"sha": BLOB, "size": 12, "encoding": "base64", "content": "YWJj"}
    )
    result = transport.get_blob(REPO, BLOB)
    assert result.sha == BLOB
    assert result.size == 12
    assert result.encoding == "base64"


def test_create_tree_uses_exact_base_and_entries_once() -> None:
    transport, client = transport_with({"sha": TREE})
    entry = GitTreeEntry("a.py", "100644", "blob", BLOB)
    assert transport.create_tree(REPO, base_tree_sha=SHA, entries=(entry,)) == TREE
    args, kwargs = client.requester.requestJsonAndCheck.call_args
    assert args[:2] == ("POST", f"/repos/{REPO}/git/trees")
    assert kwargs["input"] == {
        "base_tree": SHA,
        "tree": [{"path": "a.py", "mode": "100644", "type": "blob", "sha": BLOB}],
    }
    assert client.requester.requestJsonAndCheck.call_count == 1


def test_create_commit_uses_one_parent() -> None:
    transport, client = transport_with({"sha": SHA})
    assert transport.create_commit(REPO, tree_sha=TREE, parent_sha=PARENT, message="message") == SHA
    _args, kwargs = client.requester.requestJsonAndCheck.call_args
    assert kwargs["input"] == {"message": "message", "tree": TREE, "parents": [PARENT]}


def test_compare_normalizes_file_evidence_and_statistics() -> None:
    transport, _ = transport_with(
        {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "total_commits": 1,
            "files": [
                {
                    "filename": "a.py",
                    "status": "modified",
                    "sha": BLOB,
                    "additions": 7,
                    "deletions": 2,
                    "previous_filename": None,
                }
            ],
        }
    )
    result = transport.compare(REPO, base_sha=PARENT, head_sha=SHA)
    assert result.status == "ahead"
    assert result.additions == 7
    assert result.deletions == 2
    assert result.changed_files[0].path == "a.py"
    assert result.changed_files[0].blob_sha == BLOB


def test_update_ref_always_submits_force_false() -> None:
    transport, client = transport_with({"object": {"sha": SHA}})
    result = transport.update_ref(REPO, branch=BRANCH, commit_sha=SHA, force=False)
    assert result.commit_sha == SHA
    args, kwargs = client.requester.requestJsonAndCheck.call_args
    assert args[:2] == ("PATCH", f"/repos/{REPO}/git/refs/heads/agent%2Ftest")
    assert kwargs["input"] == {"sha": SHA, "force": False}
    with pytest.raises(ValueError, match="force"):
        transport.update_ref(REPO, branch=BRANCH, commit_sha=SHA, force=True)


def test_read_retries_transient_server_error_but_not_not_found() -> None:
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = [
        GithubException(500, {"message": "temporary"}, {}),
        ({}, {"object": {"sha": SHA}}),
    ]
    transport = PyGithubGitObjectTransport(client, max_read_attempts=2)
    assert transport.get_ref(REPO, BRANCH).commit_sha == SHA
    assert client.requester.requestJsonAndCheck.call_count == 2

    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = GithubException(404, {"message": "missing"}, {})
    transport = PyGithubGitObjectTransport(client)
    with pytest.raises(GitObjectTransportError) as excinfo:
        transport.get_ref(REPO, BRANCH)
    assert excinfo.value.kind == "not-found"
    assert client.requester.requestJsonAndCheck.call_count == 1


@pytest.mark.parametrize(
    ("operation", "invoke"),
    [
        (
            "create-tree",
            lambda transport: transport.create_tree(
                REPO,
                base_tree_sha=TREE,
                entries=(GitTreeEntry("a.py", "100644", "blob", BLOB),),
            ),
        ),
        (
            "create-commit",
            lambda transport: transport.create_commit(
                REPO, tree_sha=TREE, parent_sha=PARENT, message="message"
            ),
        ),
        (
            "update-ref",
            lambda transport: transport.update_ref(
                REPO, branch=BRANCH, commit_sha=SHA, force=False
            ),
        ),
    ],
)
def test_malformed_write_success_response_is_uncertain(operation, invoke) -> None:
    transport, client = transport_with({})
    with pytest.raises(GitObjectTransportError) as excinfo:
        invoke(transport)
    assert excinfo.value.operation == operation
    assert excinfo.value.kind == "malformed-success-response"
    assert excinfo.value.mutation_state is MutationState.UNCERTAIN
    assert client.requester.requestJsonAndCheck.call_count == 1


def test_write_timeout_is_uncertain_and_never_retried() -> None:
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = requests.exceptions.Timeout("lost")
    transport = PyGithubGitObjectTransport(client)
    entry = GitTreeEntry("a.py", "100644", "blob", BLOB)
    with pytest.raises(GitObjectTransportError) as excinfo:
        transport.create_tree(REPO, base_tree_sha=TREE, entries=(entry,))
    assert excinfo.value.kind == "mutation-uncertain"
    assert excinfo.value.mutation_state is MutationState.UNCERTAIN
    assert client.requester.requestJsonAndCheck.call_count == 1


def test_write_client_rejection_is_failed_before_side_effect() -> None:
    client = MagicMock()
    client.requester.requestJsonAndCheck.side_effect = GithubException(422, {"message": "bad"}, {})
    transport = PyGithubGitObjectTransport(client)
    with pytest.raises(GitObjectTransportError) as excinfo:
        transport.create_commit(REPO, tree_sha=TREE, parent_sha=PARENT, message="message")
    assert excinfo.value.mutation_state is MutationState.FAILED_BEFORE_SIDE_EFFECT
    assert client.requester.requestJsonAndCheck.call_count == 1


def test_transport_has_no_generic_request_or_endpoint_parameter() -> None:
    public = {name for name in dir(PyGithubGitObjectTransport) if not name.startswith("_")}
    assert public == {
        "client",
        "compare",
        "create_commit",
        "create_tree",
        "get_blob",
        "get_commit",
        "get_ref",
        "get_tree",
        "max_read_attempts",
        "update_ref",
    }
    assert "request" not in public
    assert "graphql" not in public
