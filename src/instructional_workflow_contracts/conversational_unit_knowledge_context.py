"""Candidate-specific read-only context adapter for conversational unit knowledge.

This module prepares already-resolved, bounded existing-knowledge evidence for the
Phase 1 conversational unit knowledge contract. It performs no provider reads,
semantic matching, persistence, or external writes.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

MAX_CANDIDATES = 32
VALID_RELATIONS = frozenset({"none", "identical", "conflicting", "supersedes"})
VALID_FRESHNESS = frozenset({"current", "stale", "unknown"})
_REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "candidate_id",
        "target_entity_ref",
        "existing_relation",
        "existing_ref",
        "freshness",
        "identity_verified",
    }
)


class ConversationalKnowledgeContextError(ValueError):
    """Fail-closed error for malformed or ambiguous supplied context evidence."""


def prepare_conversational_unit_knowledge_input(
    phase1_input: Mapping[str, Any],
    candidate_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a copied Phase 1 input enriched with exact candidate context evidence.

    ``candidate_evidence`` must contain exactly one verified record for every
    supplied candidate. The adapter never infers semantic equivalence: callers
    must supply an exact governed relation classification produced by the
    upstream read/normalization seam.
    """

    if not isinstance(phase1_input, Mapping):
        raise ConversationalKnowledgeContextError("phase1_input must be a mapping")
    if not isinstance(candidate_evidence, Sequence) or isinstance(candidate_evidence, (str, bytes)):
        raise ConversationalKnowledgeContextError("candidate_evidence must be a sequence")

    result = copy.deepcopy(dict(phase1_input))
    candidates = result.get("candidates")
    context = result.get("context")
    if not isinstance(candidates, list):
        raise ConversationalKnowledgeContextError("phase1_input.candidates must be a list")
    if len(candidates) > MAX_CANDIDATES:
        raise ConversationalKnowledgeContextError("candidate count exceeds bound")
    if not isinstance(context, dict):
        raise ConversationalKnowledgeContextError("phase1_input.context must be a mapping")
    if len(candidate_evidence) > MAX_CANDIDATES:
        raise ConversationalKnowledgeContextError("candidate evidence count exceeds bound")

    by_id: dict[str, dict[str, Any]] = {}
    for raw in candidate_evidence:
        if not isinstance(raw, Mapping):
            raise ConversationalKnowledgeContextError("candidate evidence record must be a mapping")
        evidence = dict(raw)
        if set(evidence) != _REQUIRED_EVIDENCE_FIELDS:
            raise ConversationalKnowledgeContextError("candidate evidence fields are not exact")

        candidate_id = _required_text(evidence["candidate_id"], "candidate_id")
        if candidate_id in by_id:
            raise ConversationalKnowledgeContextError("ambiguous duplicate candidate evidence")
        if evidence["identity_verified"] is not True:
            raise ConversationalKnowledgeContextError("candidate evidence identity is unverified")

        relation = _required_choice(evidence["existing_relation"], VALID_RELATIONS, "existing_relation")
        freshness = _required_choice(evidence["freshness"], VALID_FRESHNESS, "freshness")
        target = _required_text(evidence["target_entity_ref"], "target_entity_ref")
        existing_ref = evidence["existing_ref"]
        if relation == "none":
            if existing_ref is not None:
                raise ConversationalKnowledgeContextError("existing_ref requires an existing relation")
        else:
            existing_ref = _required_text(existing_ref, "existing_ref")

        by_id[candidate_id] = {
            "candidate_id": candidate_id,
            "target_entity_ref": target,
            "existing_relation": relation,
            "existing_ref": existing_ref,
            "freshness": freshness,
            "identity_verified": True,
        }

    candidate_ids: set[str] = set()
    preserved_existing: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ConversationalKnowledgeContextError("candidate must be a mapping")
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        if candidate_id in candidate_ids:
            raise ConversationalKnowledgeContextError("duplicate candidate_id in phase1_input")
        candidate_ids.add(candidate_id)

        evidence = by_id.get(candidate_id)
        if evidence is None:
            raise ConversationalKnowledgeContextError("missing candidate-specific context evidence")

        existing_target = candidate.get("target_entity_ref")
        if existing_target is not None and existing_target != evidence["target_entity_ref"]:
            raise ConversationalKnowledgeContextError("candidate target conflicts with verified context evidence")

        candidate["target_entity_ref"] = evidence["target_entity_ref"]
        candidate["existing_relation"] = evidence["existing_relation"]
        candidate["existing_ref"] = evidence["existing_ref"]
        candidate["freshness"] = evidence["freshness"]
        preserved_existing.append(
            {
                "candidate_id": candidate_id,
                "target_entity_ref": evidence["target_entity_ref"],
                "existing_relation": evidence["existing_relation"],
                "existing_ref": evidence["existing_ref"],
                "freshness": evidence["freshness"],
            }
        )

    unexpected = set(by_id) - candidate_ids
    if unexpected:
        raise ConversationalKnowledgeContextError("context evidence references an unknown candidate")

    current = context.get("current_entity_ref")
    if current is not None:
        for item in preserved_existing:
            if item["target_entity_ref"] != current:
                raise ConversationalKnowledgeContextError("verified target conflicts with current entity context")

    result["existing_knowledge"] = preserved_existing
    return result


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationalKnowledgeContextError(f"{field} must be non-empty text")
    return value.strip()


def _required_choice(value: object, choices: frozenset[str], field: str) -> str:
    text = _required_text(value, field)
    if text not in choices:
        raise ConversationalKnowledgeContextError(f"unsupported {field}")
    return text
