"""Pure #1203 binding from accepted issue-comment ingress to #1217 control input.

This module turns already-validated low-trust transport evidence into one bounded,
non-authorizing request for the existing #1217 GCE control path.  It performs no
GitHub, Google Cloud, credential, network, subprocess, Scheduler, lease, retry,
or persistence operation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from .gce_control_path import GceResourceTuple, validate_handoff_id
from .github_issue_comment_ingress import IssueCommentIngressResult

BINDING_SCHEMA_NAME = "agent-os-governed-invocation-binding"
BINDING_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedInvocationBinding:
    schema_name: Literal["agent-os-governed-invocation-binding"]
    schema_version: Literal["1.0"]
    binding_id: str
    repository: str
    issue_number: int
    handoff_id: str
    logical_trigger_id: str
    control_request_id: str
    resource: GceResourceTuple
    transport_status: str
    transport_reason: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_authorized_by_transport: Literal[False] = field(default=False, init=False)
    cloud_authorized_by_transport: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    retry_authorized: Literal[False] = field(default=False, init=False)
    arbitrary_command_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != BINDING_SCHEMA_NAME or self.schema_version != BINDING_SCHEMA_VERSION:
            raise ValueError("unsupported governed invocation binding schema")
        if not validate_handoff_id(self.handoff_id):
            raise ValueError("handoff_id must be canonical")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise ValueError("issue_number must be positive")
        for name in ("repository", "logical_trigger_id", "control_request_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value) > 512:
                raise ValueError(f"{name} must be bounded non-empty text")
        if self.transport_status != "accepted" or self.transport_reason != "accepted-envelope":
            raise ValueError("binding requires accepted ingress transport evidence")
        if self.binding_id != _binding_id(self):
            raise ValueError("binding_id does not match content")

    def to_dict(self) -> dict[str, object]:
        return _payload(self, include_id=True)


def _payload(value: GovernedInvocationBinding, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "repository": value.repository,
        "issue_number": value.issue_number,
        "handoff_id": value.handoff_id,
        "logical_trigger_id": value.logical_trigger_id,
        "control_request_id": value.control_request_id,
        "resource": {
            "project": value.resource.project,
            "zone": value.resource.zone,
            "instance": value.resource.instance,
        },
        "transport_status": value.transport_status,
        "transport_reason": value.transport_reason,
        "execution_authorized": False,
        "scheduler_authorized_by_transport": False,
        "cloud_authorized_by_transport": False,
        "github_writes_authorized": False,
        "retry_authorized": False,
        "arbitrary_command_authorized": False,
    }
    if include_id:
        payload["binding_id"] = value.binding_id
    return payload


def _binding_id(value: GovernedInvocationBinding) -> str:
    digest = hashlib.sha256(
        b"agent-os-governed-invocation-binding:v1\0"
        + json.dumps(
            _payload(value, include_id=False),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return f"governed-invocation-binding:{digest}"


def bind_ingress_to_gce(
    ingress: IssueCommentIngressResult,
    *,
    resource: GceResourceTuple,
) -> GovernedInvocationBinding:
    """Bind accepted transport to one fixed GCE resource and immutable handoff.

    The result is request data only.  It grants no cloud or execution authority;
    #1217 still validates OIDC claims and owns the external control attempt, while
    #1218/#758/#1202 own host reconstruction and Scheduler/lease admission.
    """
    if type(ingress) is not IssueCommentIngressResult:
        raise TypeError("ingress must be exact IssueCommentIngressResult")
    if type(resource) is not GceResourceTuple:
        raise TypeError("resource must be exact GceResourceTuple")
    if ingress.status != "accepted" or ingress.reason != "accepted-envelope":
        raise ValueError("only accepted ingress evidence may be bound")
    if ingress.issue_number is None or ingress.handoff_id_or_none is None:
        raise ValueError("accepted ingress is missing issue or handoff identity")
    if ingress.logical_trigger_id_or_none is None:
        raise ValueError("accepted ingress is missing logical trigger identity")
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot create a control binding")

    request_material = (
        f"{ingress.logical_trigger_id_or_none}\0{ingress.handoff_id_or_none}\0"
        f"{resource.project}\0{resource.zone}\0{resource.instance}"
    ).encode("utf-8")
    control_request_id = "gce-control-request:" + hashlib.sha256(request_material).hexdigest()
    provisional = GovernedInvocationBinding(
        schema_name=BINDING_SCHEMA_NAME,
        schema_version=BINDING_SCHEMA_VERSION,
        binding_id="governed-invocation-binding:" + "0" * 64,
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        handoff_id=ingress.handoff_id_or_none,
        logical_trigger_id=ingress.logical_trigger_id_or_none,
        control_request_id=control_request_id,
        resource=resource,
        transport_status=ingress.status,
        transport_reason=ingress.reason,
    )
    object.__setattr__(provisional, "binding_id", _binding_id(provisional))
    return provisional
