"""Pure-local WSC3 draft proposal ingestion."""

from .draft_ingestion import (
    PROPOSAL_VERSION,
    DraftTaskProposal,
    DraftTaskProposalResult,
    build_draft_task_proposals,
)

__all__ = [
    "PROPOSAL_VERSION",
    "DraftTaskProposal",
    "DraftTaskProposalResult",
    "build_draft_task_proposals",
]
