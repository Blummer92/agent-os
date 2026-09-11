"""Bounded GitHub-controlled Notion read request path for #2283.

Architecture (locked):

```text
ChatGPT
-> GitHub MCP
-> bounded `/agent-os notion-read <request-id>` issue comment
-> existing governed issue_comment admission
-> GitHub Actions standard hosted runner
-> existing #936 read-only Notion adapter
-> sanitized bounded result on the public GitHub evidence surface
-> ChatGPT reads the result through GitHub MCP
```

This package adds admission, a finite repository-owned request vocabulary, and a
sanitized public projection. It adds no Notion client, curriculum context
engine, asset registry, scheduler, queue, proxy, cache, or source of truth, and
routine reads never require GCE.
"""

from .admission import (
    admit_notion_read_request,
    build_curriculum_read_request,
    required_logical_sources,
)
from .catalog import CATALOG_PATH, load_catalog, parse_catalog
from .execution import execute_admitted_notion_read
from .models import (
    CREDENTIAL_ENV_VAR,
    INGRESS_REASON,
    PUBLIC_PROJECTABLE_CONTENT_CLASSES,
    REQUEST_CLASSES,
    REQUEST_CLASS_INTENT,
    SCHEMA_VERSION,
    VERIFIED_STATE,
    CanonicalUnitBinding,
    NotionReadAdmission,
    NotionReadCatalog,
    NotionReadRequestError,
    NotionReadRequestRecord,
    NotionReadSource,
)
from .projection import RESULT_KIND, project_public_result, reject_credential_keys
from .runner import (
    DISPATCH_BLOCKED,
    DISPATCH_COMPLETED,
    DISPATCH_NOT_ACTIVATED,
    run_notion_read_request,
)

__all__ = [
    "CATALOG_PATH",
    "CREDENTIAL_ENV_VAR",
    "DISPATCH_BLOCKED",
    "DISPATCH_COMPLETED",
    "DISPATCH_NOT_ACTIVATED",
    "INGRESS_REASON",
    "PUBLIC_PROJECTABLE_CONTENT_CLASSES",
    "REQUEST_CLASSES",
    "REQUEST_CLASS_INTENT",
    "RESULT_KIND",
    "SCHEMA_VERSION",
    "VERIFIED_STATE",
    "CanonicalUnitBinding",
    "NotionReadAdmission",
    "NotionReadCatalog",
    "NotionReadRequestError",
    "NotionReadRequestRecord",
    "NotionReadSource",
    "admit_notion_read_request",
    "build_curriculum_read_request",
    "execute_admitted_notion_read",
    "load_catalog",
    "parse_catalog",
    "project_public_result",
    "reject_credential_keys",
    "required_logical_sources",
    "run_notion_read_request",
]
