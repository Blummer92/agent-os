"""Canonical serialization and content-addressed identity primitives.

Reuses the byte-exact serialization rule from
``00_Governance/architecture-decisions/adr-0002-details-01b-serialization-and-digest.md``
verbatim -- this module does not restate a variant. Digests are SHA-256,
lowercase hex, domain-separated by a fixed string prefix so no two distinct
Agent OS identity domains can ever collide on the same hash.
"""

from __future__ import annotations

import hashlib
import json

CHECKPOINT_ID_DOMAIN = "agent-os.execution-checkpoint"
REUSE_KEY_DOMAIN = "agent-os.execution-checkpoint.reuse-key"
RESUME_PLAN_ID_DOMAIN = "agent-os.execution-checkpoint.resume-plan"


def canonical_json_bytes(payload: object) -> bytes:
    """The one canonical, byte-exact encoding (ADR-0002 details-01b)."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def domain_digest(domain: str, payload: object) -> str:
    """Domain-separated SHA-256 over a canonical JSON payload.

    Every distinct identity domain in this package (checkpoint id, reuse
    key, resume-plan id, mutation-intent id) goes through this single
    function with its own fixed domain string, so no two domains can ever
    collide on the same hash even given identical payload content.
    """

    material = domain.encode("utf-8") + b":v1\0" + canonical_json_bytes(payload)
    return f"{domain}:{hashlib.sha256(material).hexdigest()}"


def compute_checkpoint_id(identity_payload: dict[str, object]) -> str:
    """Domain-separated SHA-256 over one checkpoint's semantic identity."""

    return domain_digest(CHECKPOINT_ID_DOMAIN, identity_payload)


def compute_reuse_key(reuse_payload: dict[str, object]) -> str:
    """Domain-separated SHA-256 identifying interchangeable evidence.

    Two checkpoints from separate invocations that carry an identical
    reuse payload (same repository/issue/branch/SHA roles/dependency and
    environment fingerprints/command plan/stage) are interchangeable
    evidence, even though their own ``checkpoint_id`` values differ because
    ``invocation_id``/``execution_id`` are excluded here.
    """

    return domain_digest(REUSE_KEY_DOMAIN, reuse_payload)


def compute_resume_plan_id(plan_payload: dict[str, object]) -> str:
    """Domain-separated SHA-256 for one deterministic resume plan."""

    return domain_digest(RESUME_PLAN_ID_DOMAIN, plan_payload)
