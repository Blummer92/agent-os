"""Local-only, read-only Notion connection diagnostic."""
import json
import subprocess
import sys
from datetime import datetime, timezone

from workflow_scheduler.adapters.notion_readonly_adapter import (
    NotionReadOnlyAdapter,
    NOTION_VERSION,
)

def main():
    status = {
        "provider": "notion",
        "authenticated": False,
        "read_access": False,
        "write_authorized": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "api_version": NOTION_VERSION,
    }

    token = None
    try:
        token = subprocess.check_output(
            [
                "gcloud", "secrets", "versions", "access",
                "latest",
                "--secret=agent-os-notion-api-key",
                "--project=agent-os-502614",
            ],
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).decode().strip()

        if not token:
            raise RuntimeError("credential unavailable")

        adapter = NotionReadOnlyAdapter(token=token)
        result = adapter._get("/users/me")
        status["authenticated"] = result.get("object") == "user"
        status["read_access"] = status["authenticated"]

    except Exception:
        status["error"] = "notion-verification-unavailable"

    finally:
        token = None

    print(json.dumps(status, indent=2))
    return 0 if status["authenticated"] else 1

if __name__ == "__main__":
    sys.exit(main())
