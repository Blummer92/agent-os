"""Bounded CLI seam for one #2283 GitHub-controlled Notion read.

The runner produces one deterministic evidence object for the smallest existing
approved public GitHub evidence surface (a bounded Actions artifact plus a job
summary), exactly like the existing governed ingress. It creates no new
persistence subsystem, writes nothing to Notion or Drive, and never turns issue
comments or repository files into a curriculum store.

Following the existing preflight convention, the runner never reads the system
clock: ``generated_at`` is caller-supplied so results stay reproducible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

from .admission import admit_notion_read_request
from .catalog import load_catalog
from .execution import SchedulerTaskExecutorFactory, execute_admitted_notion_read
from .models import SCHEMA_VERSION, NotionReadCatalog, NotionReadRequestError
from .projection import reject_credential_keys, project_public_result

MAX_TRANSPORT_BYTES = 262_144

#: Terminal dispatch states. ``not-activated`` is the honest state while the
#: source allowlist carries no verified binding: admission succeeded in shape but
#: live secret-backed access remains a separately authorized excluded surface.
DISPATCH_BLOCKED = "blocked"
DISPATCH_NOT_ACTIVATED = "not-activated"
DISPATCH_COMPLETED = "completed"


def run_notion_read_request(
    transport: object,
    *,
    expected_repository: str,
    expected_actor: str,
    generated_at: str,
    catalog: NotionReadCatalog | None = None,
    scheduler_task_executor_factory: SchedulerTaskExecutorFactory | None = None,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Admit, optionally execute, and project one bounded read as evidence."""
    resolved_catalog = catalog if catalog is not None else load_catalog()
    admission = admit_notion_read_request(
        transport,
        catalog=resolved_catalog,
        expected_repository=expected_repository,
        expected_actor=expected_actor,
    )

    evidence: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "admission": admission.to_dict(),
        "dispatch_status": DISPATCH_BLOCKED,
        "dispatch_reason": admission.reason_codes[0],
        "result": None,
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
    }

    if not admission.secret_dispatch_authorized:
        reject_credential_keys(evidence, "evidence")
        return evidence

    if scheduler_task_executor_factory is None:
        evidence["dispatch_status"] = DISPATCH_NOT_ACTIVATED
        evidence["dispatch_reason"] = "live-read-executor-not-configured"
        reject_credential_keys(evidence, "evidence")
        return evidence

    execution = execute_admitted_notion_read(
        admission,
        catalog=resolved_catalog,
        scheduler_task_executor_factory=scheduler_task_executor_factory,
        current_context=current_context,
    )
    evidence["dispatch_status"] = DISPATCH_COMPLETED
    evidence["dispatch_reason"] = "bounded-read-projected"
    evidence["result"] = project_public_result(
        admission,
        execution,
        catalog=resolved_catalog,
        generated_at=generated_at,
    )
    reject_credential_keys(evidence, "evidence")
    return evidence


def _read_transport(path: Path) -> object:
    if path.stat().st_size > MAX_TRANSPORT_BYTES:
        raise NotionReadRequestError("transport evidence exceeds byte bound")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    evidence = run_notion_read_request(
        _read_transport(args.transport),
        expected_repository=args.repository,
        expected_actor=args.allowed_actor,
        generated_at=args.generated_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
