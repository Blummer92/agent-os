"""ChatGPT-facing composition seam for canonical connected issue creation (#2363).

This module does not classify issues itself. It delegates managed-label planning to
the existing #1962 connected-creation owner and returns a non-authorizing host
projection suitable for the existing GitHub issue-create/readback flow.
"""

from __future__ import annotations

from pathlib import Path

from scripts.agent_os_issue_labels.connected_issue_creation import managed_labels_for_create


def plan_connected_issue_creation_for_host(
    *,
    repository: str,
    issue_body: str,
    issue_form_path: str | Path = ".github/ISSUE_TEMPLATE/agent-os-task.yml",
    label_map_path: str | Path = ".github/labeler/agent-os-issue-label-map.yml",
) -> dict[str, object]:
    """Return canonical create labels without creating readiness or write authority."""
    if type(repository) is not str or repository.count("/") != 1 or not all(repository.split("/")):
        raise ValueError("repository must use bounded owner/name syntax")
    if type(issue_body) is not str or not issue_body.strip():
        raise ValueError("issue_body must be non-empty canonical text")

    labels = managed_labels_for_create(
        issue_body,
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )
    return {
        "repository": repository,
        "proposed_labels": list(labels),
        "next_operation": "create-then-canonical-readback-and-converge",
        "reconciliation_owner": "#1962",
        "implementation_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "external_write_authorized": False,
        "side_effects_performed": False,
    }
