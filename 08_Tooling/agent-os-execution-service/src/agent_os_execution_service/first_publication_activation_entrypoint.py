"""Bounded production-host first-publication activation for #1239.

The caller supplies exactly one immutable #1412 source-capsule identity. This
module composes the already-owned #1930 trusted-host observation/#1428 source
activation boundary with the already-owned #1411 publication boundary, returns
one immutable ExecutorHandoff identity, and stops before Scheduler execution.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Callable, Literal

from .executor_routing import ExecutorHandoff, executor_handoff_id
from .first_publication_host_observation import (
    FirstPublicationActivationIdentity,
    activate_first_publication_from_host,
)
from .first_publication_producer import FirstPublicationProducerResult
from .production_handoff_publication import (
    ProductionHandoffPublicationIdentity,
    publish_production_handoff,
)

FIRST_PUBLICATION_ACTIVATION_SCHEMA_VERSION = "1.0"


class FirstPublicationActivationError(RuntimeError):
    """Current first-publication evidence cannot safely be published."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstPublicationActivationResult:
    schema_version: Literal["1.0"]
    source_capsule_id: str
    checkpoint_id: str
    resume_plan_id: str
    route_decision_id: str
    dependency_readiness_id: str
    pre_publication_evidence_id: str
    authorization_id: str
    source_sha: str
    tested_sha: str
    handoff_id: str
    publication_invoked: Literal[True] = True
    scheduler_invoked: Literal[False] = False
    execution_lease_acquired: Literal[False] = False
    resume_invoked: Literal[False] = False
    retry_attempted: Literal[False] = False
    provider_fallback_attempted: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_capsule_id": self.source_capsule_id,
            "checkpoint_id": self.checkpoint_id,
            "resume_plan_id": self.resume_plan_id,
            "route_decision_id": self.route_decision_id,
            "dependency_readiness_id": self.dependency_readiness_id,
            "pre_publication_evidence_id": self.pre_publication_evidence_id,
            "authorization_id": self.authorization_id,
            "source_sha": self.source_sha,
            "tested_sha": self.tested_sha,
            "handoff_id": self.handoff_id,
            "publication_invoked": True,
            "scheduler_invoked": False,
            "execution_lease_acquired": False,
            "resume_invoked": False,
            "retry_attempted": False,
            "provider_fallback_attempted": False,
        }


def activate_and_publish_first_handoff(
    identity: FirstPublicationActivationIdentity,
    *,
    activate: Callable[[FirstPublicationActivationIdentity], FirstPublicationProducerResult]
    = activate_first_publication_from_host,
    publish: Callable[[ProductionHandoffPublicationIdentity], ExecutorHandoff]
    = publish_production_handoff,
) -> FirstPublicationActivationResult:
    """Run #1930/#1428 once, publish through #1411 once, then stop."""
    if type(identity) is not FirstPublicationActivationIdentity:
        raise TypeError("identity must be an exact FirstPublicationActivationIdentity")
    try:
        producer = activate(identity)
        if type(producer) is not FirstPublicationProducerResult:
            raise FirstPublicationActivationError("producer-result-malformed")
        publication_identity = ProductionHandoffPublicationIdentity(
            capsule_id=producer.pre_publication_evidence_id,
            route_decision_id=producer.route_decision_id,
            dependency_readiness_id=producer.dependency_readiness_id,
        )
        handoff = publish(publication_identity)
        if type(handoff) is not ExecutorHandoff:
            raise FirstPublicationActivationError("publication-result-malformed")
        return FirstPublicationActivationResult(
            schema_version=FIRST_PUBLICATION_ACTIVATION_SCHEMA_VERSION,
            source_capsule_id=identity.source_capsule_id,
            checkpoint_id=producer.checkpoint_id,
            resume_plan_id=producer.resume_plan_id,
            route_decision_id=producer.route_decision_id,
            dependency_readiness_id=producer.dependency_readiness_id,
            pre_publication_evidence_id=producer.pre_publication_evidence_id,
            authorization_id=producer.authorization_id,
            source_sha=producer.source_sha,
            tested_sha=producer.tested_sha,
            handoff_id=executor_handoff_id(handoff),
        )
    except FirstPublicationActivationError:
        raise
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except (TypeError, ValueError, LookupError, OSError, RuntimeError) as exc:
        raise FirstPublicationActivationError(
            "first-publication-activation-failed-closed"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-capsule-id", required=True)
    args = parser.parse_args(argv)
    identity = FirstPublicationActivationIdentity(source_capsule_id=args.source_capsule_id)
    result = activate_and_publish_first_handoff(identity)
    print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
