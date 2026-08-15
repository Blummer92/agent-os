"""Production ``RepositoryEvidenceReader`` with no live structured source.

There is currently no structured live source for dependency or validation
readiness anywhere in this repository (per #1155). Rather than guess, infer
from issue prose/labels/CI/branch state/repository files, or fabricate a
placeholder, ``LiveRepositoryEvidenceReader`` returns the existing canonical
``EvidenceStatus.UNAVAILABLE`` with an explicit, finite reason code -- the
same "no structured source" default already used by the CLI's fixture
reader (``scripts/agent_os_candidate_packet/cli.py``'s
``_FixtureRepositoryReader``), just under a distinct, adapter-specific reason
code so the two are never conflated in evidence.

Designing the future structured evidence source is out of scope for this
package; ``UNAVAILABLE`` is an acceptable, truthful terminal answer here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)

DEPENDENCY_NO_STRUCTURED_SOURCE_REASON = "dependency.no-structured-source-configured"
VALIDATION_NO_STRUCTURED_SOURCE_REASON = "validation.no-structured-source-configured"


@dataclass(frozen=True, slots=True)
class LiveRepositoryEvidenceReader:
    """Production ``RepositoryEvidenceReader`` that is truthfully always UNAVAILABLE."""

    execution_authorized: bool = field(default=False, init=False)

    def read_dependency_evidence(
        self, repository: str, issue_number: int
    ) -> DependencyEvidence:
        return DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=(DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,),
        )

    def read_validation_evidence(
        self, repository: str, issue_number: int
    ) -> ValidationEvidence:
        return ValidationEvidence(
            status=EvidenceStatus.UNAVAILABLE,
            reason_codes=(VALIDATION_NO_STRUCTURED_SOURCE_REASON,),
        )
