"""Canonical refresh-authorization renderer (#3463).

The renderer is a thin entry point over the existing RefreshAuthorization
validation/identity computation and the existing serializer. It must
produce byte-identical output to the serializer for the same inputs,
refuse every incomplete/malformed/inconsistent input, and never post,
merge, or grant anything itself.
"""
from __future__ import annotations

import json

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_renderer import (
    main as renderer_main,
    render_refresh_authorization_comment,
    render_refresh_authorization_comment_from_mapping,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    AUTHORIZATION_MARKER,
    RefreshAuthorizationCommentSnapshot,
    RefreshAuthorizationSourceSnapshot,
    RefreshAuthorizationSourceStatus,
    reacquire_refresh_authorization_source,
    serialize_refresh_authorization_comment,
)

REPO = "Blummer92/agent-os"
HEAD = "a" * 40
MAIN = "b" * 40


def inputs(**overrides):
    values = dict(
        repository=REPO,
        pr_number=1363,
        expected_head_sha=HEAD,
        expected_main_sha=MAIN,
        allowed_changed_paths=("x.py",),
        forbidden_paths=(".github/workflows/x.yml",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=False,
        owner_decision_reference="github-owner-decision:1363",
        state=RefreshAuthorizationState.AUTHORIZED,
    )
    values.update(overrides)
    return values


def mapping(**overrides):
    values = dict(
        repository=REPO,
        pr_number=1363,
        expected_head_sha=HEAD,
        expected_main_sha=MAIN,
        allowed_changed_paths=["x.py"],
        forbidden_paths=[".github/workflows/x.yml"],
        required_validation_command_ids=["pytest:pr-branch-refresh"],
        branch_refresh_authorized=True,
        label_write_authorized=False,
        owner_decision_reference="github-owner-decision:1363",
        state="authorized",
    )
    values.update(overrides)
    return values


def test_renderer_matches_existing_serializer_byte_for_byte():
    rendered = render_refresh_authorization_comment(**inputs())
    direct = serialize_refresh_authorization_comment(
        RefreshAuthorization(schema_version="1.0", base_branch="main", **inputs())
    )
    assert rendered == direct
    marker, payload = rendered.split("\n", 1)
    assert marker == AUTHORIZATION_MARKER
    assert payload == json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":"))
    assert render_refresh_authorization_comment(**inputs()) == rendered
    assert render_refresh_authorization_comment(**inputs(state="authorized")) == rendered


def test_rendered_record_matches_september_known_valid_record_and_reacquires_current():
    # September's known-valid fixture shape (2026-09-03 source-test record):
    # same field values as the existing authorization-source test record.
    rendered = render_refresh_authorization_comment(**inputs())
    record = RefreshAuthorization(schema_version="1.0", base_branch="main", **inputs())
    assert rendered == serialize_refresh_authorization_comment(record)

    class Transport:
        def read_refresh_authorization_source(self, repository, pr_number):
            return RefreshAuthorizationSourceSnapshot(
                repository=REPO, pr_number=1363, owner_login="Blummer92", owner_type="User",
                comments_complete=True,
                comments=(
                    RefreshAuthorizationCommentSnapshot(
                        comment_id=1, author_login="Blummer92",
                        created_at="2026-09-03T18:00:01Z", body=rendered,
                    ),
                ),
            )

    result = reacquire_refresh_authorization_source(transport=Transport(), repository=REPO, pr_number=1363)
    assert result.status is RefreshAuthorizationSourceStatus.CURRENT
    assert result.records == (record,)
    assert result.side_effects_performed is False


def test_renderer_refuses_incomplete_and_extra_mapping_inputs():
    base = mapping()
    for key in ("repository", "pr_number", "expected_head_sha", "expected_main_sha",
                "allowed_changed_paths", "forbidden_paths", "required_validation_command_ids",
                "branch_refresh_authorized", "label_write_authorized",
                "owner_decision_reference", "state"):
        incomplete = {k: v for k, v in base.items() if k != key}
        with pytest.raises((TypeError, ValueError)):
            render_refresh_authorization_comment_from_mapping(incomplete)
    with pytest.raises(ValueError):
        render_refresh_authorization_comment_from_mapping({**base, "authorization_id": "refresh-authorization:" + "0" * 64})
    with pytest.raises(ValueError):
        render_refresh_authorization_comment_from_mapping({**base, "schema_version": "2.0"})
    with pytest.raises(TypeError):
        render_refresh_authorization_comment_from_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_renderer_refuses_malformed_inconsistent_or_unsupported_inputs():
    bad_cases = [
        inputs(repository="not-a-repo"),
        inputs(repository="Blummer92/agent-os", pr_number=0),
        inputs(repository="Blummer92/agent-os", pr_number=True),
        inputs(expected_head_sha="ZZZ"),
        inputs(expected_head_sha=HEAD.upper()),
        inputs(expected_main_sha="c" * 39),
        inputs(allowed_changed_paths="x.py"),  # a bare string is not a path list
        inputs(allowed_changed_paths=("x.py", "x.py")),  # duplicates
        inputs(allowed_changed_paths=("x.py", "")),
        inputs(forbidden_paths=("x.py", "x.py")),
        inputs(branch_refresh_authorized=1),  # exact bool required, not truthy int
        inputs(label_write_authorized="yes"),
        inputs(owner_decision_reference=""),
        inputs(owner_decision_reference="   "),
        inputs(state="bogus"),
        inputs(state="AUTHORIZED"),
        inputs(state=123),
    ]
    for bad in bad_cases:
        with pytest.raises((TypeError, ValueError)):
            render_refresh_authorization_comment(**bad)


def test_renderer_cli_prints_record_and_refuses_bad_input(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(mapping()), encoding="utf-8")
    assert renderer_main(["--input", str(good)]) == 0
    out = capsys.readouterr().out
    assert out == render_refresh_authorization_comment(**inputs()) + "\n"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(mapping(expected_head_sha="short")), encoding="utf-8")
    assert renderer_main(["--input", str(bad)]) == 2
    assert capsys.readouterr().out == ""

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"repository": REPO}), encoding="utf-8")
    assert renderer_main(["--input", str(missing)]) == 2

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert renderer_main(["--input", str(broken)]) == 2


def test_renderer_output_is_not_a_post_or_a_grant():
    # The rendered text is inert: it contains no GitHub API call, no merge
    # claim, and its authority fields are exactly the caller-supplied ones.
    rendered = render_refresh_authorization_comment(**inputs(label_write_authorized=False))
    assert "api.github.com" not in rendered
    assert "merge" not in rendered
    assert json.loads(rendered.split("\n", 1)[1])["label_write_authorized"] is False
    assert json.loads(rendered.split("\n", 1)[1])["side_effects_performed"] is False
