"""Regression coverage for #1689."""

import pytest

from workflow_scheduler.adapters.github_readonly_adapter import GitHubReadOnlyAdapter
from workflow_scheduler.adapters.github_pr_comment_adapter import GitHubPRCommentAdapter
from workflow_scheduler.adapters.github_pr_label_adapter import GitHubPRLabelAdapter
from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapter


ADAPTERS = (GitHubReadOnlyAdapter, GitHubPRCommentAdapter, GitHubPRLabelAdapter, NotionReadOnlyAdapter)

# bool is an int subclass, so True/False must be rejected by an explicit type
# guard rather than by the numeric range check alone.
NON_NUMERIC_TIMEOUTS = (True, False, "10", None, object())
OUT_OF_POLICY_TIMEOUTS = (0, 0.0, -1, -1.5, float("nan"), float("inf"), float("-inf"))


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
@pytest.mark.parametrize("timeout", NON_NUMERIC_TIMEOUTS)
def test_adapter_constructor_rejects_non_numeric_timeout(adapter_cls, timeout):
    with pytest.raises(TypeError):
        adapter_cls(timeout=timeout)


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
@pytest.mark.parametrize("timeout", OUT_OF_POLICY_TIMEOUTS)
def test_adapter_constructor_rejects_non_finite_or_non_positive_timeout(adapter_cls, timeout):
    with pytest.raises(ValueError):
        adapter_cls(timeout=timeout)


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
@pytest.mark.parametrize("timeout", [1, 30, 1.5, 0.001])
def test_adapter_constructor_accepts_positive_finite_timeout(adapter_cls, timeout):
    adapter = adapter_cls(timeout=timeout)
    assert adapter.timeout == timeout


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
def test_adapter_constructor_default_timeout_remains_valid(adapter_cls):
    assert adapter_cls().timeout == 10.0


@pytest.mark.parametrize("adapter_cls", ADAPTERS)
def test_adapter_constructor_preserves_injected_transport_timeout(adapter_cls):
    adapter = adapter_cls(token="t", timeout=7)
    assert adapter.timeout == 7
    assert adapter.token == "t"
