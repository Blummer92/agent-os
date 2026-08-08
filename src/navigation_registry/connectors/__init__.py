"""Navigation Registry contract adapters and compatibility shims.

``NotionContractAdapter`` is the canonical root normalization bridge.
``NotionReadOnlyConnector`` is retained only as an offline fixture compatibility
shim; it is not a cached lookup client or live Notion API reader.
"""

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion import NotionReadOnlyConnector
from .notion_contract_adapter import (
    CACHED_NOTION_INDEX_SOURCE,
    LIVE_NOTION_SOURCE,
    NOTION_SEARCH_RESULT_SOURCE,
    NotionContractAdapter,
)
from .notion_intent_context import (
    NotionIntentContext,
    NotionIntentContextError,
    NotionIntentEvidence,
    project_notion_intent_context,
)
from .scheduler_notion_evidence import SchedulerNotionEvidenceAdapter

__all__ = [
    "CACHED_NOTION_INDEX_SOURCE",
    "ConnectorError",
    "ConnectorErrorCode",
    "LIVE_NOTION_SOURCE",
    "NOTION_SEARCH_RESULT_SOURCE",
    "NotionContractAdapter",
    "NotionIntentContext",
    "NotionIntentContextError",
    "NotionIntentEvidence",
    "NotionReadOnlyConnector",
    "RegistryResource",
    "SchedulerNotionEvidenceAdapter",
    "project_notion_intent_context",
]
