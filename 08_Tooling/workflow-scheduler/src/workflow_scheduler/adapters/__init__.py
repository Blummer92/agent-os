"""Adapters for task execution."""

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.adapters.fake_adapters import (
    FakeFailureAdapter,
    FakeMalformedReturnAdapter,
    FakeNeverCalledAdapter,
    FakeRaisingAdapter,
    FakeRetryableAdapter,
    FakeSlowAdapter,
    FakeSuccessAdapter,
)
from workflow_scheduler.adapters.github_pr_comment_adapter import (
    GitHubPRCommentAdapter,
    GitHubPRCommentAdapterError,
)
from workflow_scheduler.adapters.github_pr_label_adapter import (
    GitHubPRLabelAdapter,
    GitHubPRLabelAdapterError,
)
from workflow_scheduler.adapters.github_readonly_adapter import (
    GitHubReadOnlyAdapter,
    GitHubReadOnlyAdapterError,
)
from workflow_scheduler.adapters.github_ruleset_admin_adapter import (
    GitHubRulesetAdminAdapter,
    GitHubRulesetAdminAdapterError,
)
from workflow_scheduler.adapters.instructional_materials_dry_run_adapter import (
    InstructionalMaterialsDryRunAdapter,
)
from workflow_scheduler.adapters.noop_adapter import NoopAdapter
from workflow_scheduler.adapters.notion_readonly_adapter import (
    NotionReadOnlyAdapter,
    NotionReadOnlyAdapterError,
)
from workflow_scheduler.adapters.registry import available_adapters, resolve_adapter

__all__ = [
    "TaskAdapter",
    "NoopAdapter",
    "InstructionalMaterialsDryRunAdapter",
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
