"""Adapters for task execution.

Adapter implementations are loaded lazily so importing one bounded adapter does
not require optional dependencies owned by unrelated adapters.  This preserves
the historical package-level public exports without turning package import into
an eager import of every provider integration.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

from workflow_scheduler.adapters.base_adapter import TaskAdapter

_LAZY_EXPORTS: Final[dict[str, tuple[str, str]]] = {
    "NoopAdapter": ("workflow_scheduler.adapters.noop_adapter", "NoopAdapter"),
    "InstructionalMaterialsDryRunAdapter": (
        "workflow_scheduler.adapters.instructional_materials_dry_run_adapter",
        "InstructionalMaterialsDryRunAdapter",
    ),
    "InstructionalMaterialsLiveAdapter": (
        "workflow_scheduler.adapters.instructional_materials_live_adapter",
        "InstructionalMaterialsLiveAdapter",
    ),
    "FakeSuccessAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeSuccessAdapter"),
    "FakeFailureAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeFailureAdapter"),
    "FakeRetryableAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeRetryableAdapter"),
    "FakeNeverCalledAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeNeverCalledAdapter"),
    "FakeSlowAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeSlowAdapter"),
    "FakeMalformedReturnAdapter": (
        "workflow_scheduler.adapters.fake_adapters",
        "FakeMalformedReturnAdapter",
    ),
    "FakeRaisingAdapter": ("workflow_scheduler.adapters.fake_adapters", "FakeRaisingAdapter"),
    "GitHubReadOnlyAdapter": (
        "workflow_scheduler.adapters.github_readonly_adapter",
        "GitHubReadOnlyAdapter",
    ),
    "GitHubReadOnlyAdapterError": (
        "workflow_scheduler.adapters.github_readonly_adapter",
        "GitHubReadOnlyAdapterError",
    ),
    "NotionReadOnlyAdapter": (
        "workflow_scheduler.adapters.notion_readonly_adapter",
        "NotionReadOnlyAdapter",
    ),
    "NotionReadOnlyAdapterError": (
        "workflow_scheduler.adapters.notion_readonly_adapter",
        "NotionReadOnlyAdapterError",
    ),
    "GitHubPRCommentAdapter": (
        "workflow_scheduler.adapters.github_pr_comment_adapter",
        "GitHubPRCommentAdapter",
    ),
    "GitHubPRCommentAdapterError": (
        "workflow_scheduler.adapters.github_pr_comment_adapter",
        "GitHubPRCommentAdapterError",
    ),
    "GitHubPRLabelAdapter": (
        "workflow_scheduler.adapters.github_pr_label_adapter",
        "GitHubPRLabelAdapter",
    ),
    "GitHubPRLabelAdapterError": (
        "workflow_scheduler.adapters.github_pr_label_adapter",
        "GitHubPRLabelAdapterError",
    ),
    "GitHubRulesetAdminAdapter": (
        "workflow_scheduler.adapters.github_ruleset_admin_adapter",
        "GitHubRulesetAdminAdapter",
    ),
    "GitHubRulesetAdminAdapterError": (
        "workflow_scheduler.adapters.github_ruleset_admin_adapter",
        "GitHubRulesetAdminAdapterError",
    ),
    "resolve_adapter": ("workflow_scheduler.adapters.registry", "resolve_adapter"),
    "available_adapters": ("workflow_scheduler.adapters.registry", "available_adapters"),
}


def __getattr__(name: str):
    """Resolve historical package-level adapter exports on first use."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "TaskAdapter",
    "NoopAdapter",
    "InstructionalMaterialsDryRunAdapter",
    "InstructionalMaterialsLiveAdapter",
    "FakeSuccessAdapter",
    "FakeFailureAdapter",
    "FakeRetryableAdapter",
    "FakeNeverCalledAdapter",
    "FakeSlowAdapter",
    "FakeMalformedReturnAdapter",
    "FakeRaisingAdapter",
    "GitHubReadOnlyAdapter",
    "GitHubReadOnlyAdapterError",
    "NotionReadOnlyAdapter",
    "NotionReadOnlyAdapterError",
    "GitHubPRCommentAdapter",
    "GitHubPRCommentAdapterError",
    "GitHubPRLabelAdapter",
    "GitHubPRLabelAdapterError",
    "GitHubRulesetAdminAdapter",
    "GitHubRulesetAdminAdapterError",
    "resolve_adapter",
    "available_adapters",
]
