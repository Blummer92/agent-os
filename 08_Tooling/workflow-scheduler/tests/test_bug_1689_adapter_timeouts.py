"""Regression coverage for #1689."""

import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.adapters.github_pr_comment_adapter import GitHubPRCommentAdapter
from workflow_scheduler.adapters.github_pr_label_adapter import GitHubPRLabelAdapter
from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter


ADAPTERS = (GitHubReadOnlyAdapter, GitHubPRCommentAdapter, GitHubPRLabelAdapter, NotionReadOnlyAdapter)


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf")])
def test_adapter_constructor_rejects_invalid_timeout(adapter_cls, timeout):
    with pytest.raises((TypeError, ValueError)):
        adapter_cls(timeout=timeout)


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
def test_adapter_constructor_accepts_positive_finite_timeout(adapter_cls):
    adapter = adapter_cls(timeout=1.5)
    assert adapter.timeout == 1.5
