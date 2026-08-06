"""Stable mutation-intent identity for at-most-once mutation safety.

``mutation_intent_id`` is stable across retries of the *same* intent and
different for different content, so a caller can prove -- via the canonical
pre-read and post-write rules documented in ``README.md`` -- whether a
mutation already took effect before ever attempting it again. This module
computes the identity only; it performs no I/O and executes no mutation.
"""

from __future__ import annotations

import re

from .identity import domain_digest
from .models import (
    _exact_text,
    _hex64,
    _positive_int,
    _repository,
    _sha256_id,
    _token,
)

MUTATION_INTENT_DOMAIN = "agent-os.mutation-intent"

_TARGET_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


def _target_ref(value: object) -> str:
    text = _exact_text(value, "target_ref", 255)
    if not _TARGET_REF_RE.fullmatch(text):
        raise ValueError("target_ref is malformed")
    return text


def compute_mutation_intent_id(
    *,
    repository: str,
    issue_number: int,
    execution_id: str,
    checkpoint_stage: str,
    target_ref: str,
    content_digest: str,
    parent_checkpoint_id: str | None,
) -> str:
    """Deterministic identity for one mutation attempt.

    Stable for repeated calls with identical arguments; different whenever
    ``content_digest`` (or any other bound field) differs. ``target_ref`` is
    a branch name, a PR head ref, or an equivalently bounded mutation
    target -- never a credential or URL.
    """

    payload = {
        "repository": _repository(repository),
        "issue_number": _positive_int(issue_number, "issue_number"),
        "execution_id": _token(execution_id, "execution_id"),
        "checkpoint_stage": _exact_text(checkpoint_stage, "checkpoint_stage", 64),
        "target_ref": _target_ref(target_ref),
        "content_digest": _hex64(content_digest, "content_digest"),
        "parent_checkpoint_id": (
            None
            if parent_checkpoint_id is None
            else _sha256_id(parent_checkpoint_id, "parent_checkpoint_id")
        ),
    }
    return domain_digest(MUTATION_INTENT_DOMAIN, payload)
