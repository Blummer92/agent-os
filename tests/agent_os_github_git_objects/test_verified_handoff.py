from __future__ import annotations

import pytest

from scripts.agent_os_github_git_objects.verified_handoff import (
    VerifiedHandoffEntry,
    VerifiedImplementationHandoff,
    atomic_request_from_verified_handoff,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
DIGEST = "d" * 64


def _handoff(**overrides):
    values = dict(
        repository="Blummer92/agent-os",
        branch="agent/example",
        expected_parent_sha=SHA_A,
        artifact_sha256=DIGEST,
        entries=(
            VerifiedHandoffEntry("z.txt", SHA_C),
            VerifiedHandoffEntry("a.txt", SHA_B),
        ),
        commit_message="Apply verified implementation handoff",
        invocation_id="handoff-1",
    )
    values.update(overrides)
    return VerifiedImplementationHandoff(**values)


def test_verified_handoff_projects_exact_parent_and_post_image_blobs():
    request = atomic_request_from_verified_handoff(_handoff())
    assert request.expected_head_sha == SHA_A
    assert request.allowed_paths == ("a.txt", "z.txt")
    assert tuple((entry.path, entry.sha) for entry in request.entries) == (
        ("a.txt", SHA_B),
        ("z.txt", SHA_C),
    )
    assert request.prior_fingerprints == ()


def test_verified_handoff_rejects_duplicate_paths():
    with pytest.raises(ValueError, match="duplicate paths"):
        _handoff(entries=(VerifiedHandoffEntry("a.txt", SHA_B), VerifiedHandoffEntry("a.txt", SHA_C)))


@pytest.mark.parametrize("digest", ["", "D" * 64, "d" * 63, "g" * 64, None])
def test_verified_handoff_rejects_invalid_artifact_digest(digest):
    with pytest.raises(ValueError, match="artifact_sha256"):
        _handoff(artifact_sha256=digest)


def test_bridge_rejects_untyped_handoff():
    with pytest.raises(TypeError, match="VerifiedImplementationHandoff"):
        atomic_request_from_verified_handoff({})
