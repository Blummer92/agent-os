"""Connected visual-placement transport boundary (#3257).

This module defines the seam between the repository-side placement
orchestration and the runtime that physically inserts an image into a
Google Doc/Slide. It creates no new placement architecture: the placement
request, marker, and receipt contracts are owned by ``visual_placement``
(#2087 lineage), and the reference insertion runtime is the Apps Script
``VisualPlacementTransport`` (``apps-script/VisualPlacementTransport.gs``),
which reads the private Drive file by exact file ID as a blob -- no sharing
change, no public URL, no re-selection, no generation.

A Python-direct insertion of a *private* Drive file is not possible: the
Docs/Slides APIs require a publicly accessible image URI, and making a
governed asset public would be a sharing change outside this issue's
authorization boundary. The connected runtime is therefore the Apps Script
seam, invoked here through the Apps Script Execution API.

Activation of that runtime (deploying the script as an API executable,
granting execution) is separately governed. Until it is activated, any
build with a non-empty visual selection fails closed with the explicit
``placement-runtime-unavailable`` blocked state -- never "final", never a
visual gap, never a generation handoff (#1753 fail-closed behavior).

Repository tests inject fake transports; this module performs no live call
unless ``AppsScriptPlacementTransport`` is constructed with a real script
deployment id and credentials.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .visual_placement import PlacementRequest


class PlacementRuntimeUnavailable(RuntimeError):
    """No verified image-placement runtime is available for this build."""


class PlacementTransportError(RuntimeError):
    """The placement runtime failed with an explicit placement-scoped reason.

    Never a visual gap, never absence, never generation permission: the
    reason names the placement failure so the caller can fail the build
    closed with that exact state.
    """


@runtime_checkable
class PlacementTransport(Protocol):
    """Insert one placement request's exact asset at its exact target.

    Returns the RAW transport result mapping (untrusted). The caller
    verifies the end state against the persisted artifact and accepts the
    result only through ``visual_placement.verify_placement_receipt``.

    Implementations must raise ``PlacementRuntimeUnavailable`` when the
    runtime cannot act at all, and ``PlacementTransportError`` (or a
    subclass) with an explicit placement-scoped reason for any other
    failure. They must never translate a placement failure into absence
    or authorize new visual creation.
    """

    def insert_placement(self, *, request: PlacementRequest) -> Mapping[str, Any]:
        ...


def _request_payload(request: PlacementRequest) -> dict[str, Any]:
    target = request.target
    return {
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "source_plan_id": request.source_plan_id,
        "content_identity": dict(request.content_identity),
        "target": {
            "artifact_type": target.artifact_type,
            "artifact_id": target.artifact_id,
            "artifact_revision_id": target.artifact_revision_id,
            "marker": target.marker,
            "container_id": target.container_id,
            "element_id": target.element_id,
            "index": target.index,
            "bounds": dict(target.bounds) if target.bounds is not None else None,
            "fit_mode": target.fit_mode,
        },
    }


class AppsScriptPlacementTransport:
    """Invoke the deployed #2087 Apps Script placement transport.

    Calls the script's ``placeVisual`` function through the Apps Script
    Execution API. The script itself performs the blob read
    (``DriveApp.getFileById(drive_file_id).getBlob()``) and the insertion;
    this client only ferries the governed request and returns the remote
    result for repository-side verification.

    Requires the separately governed activation: the reference script must
    be deployed as an API executable and execution granted to the build
    identity. Without that activation this transport must not be
    constructed for a real run -- construct nothing and let the caller
    raise ``PlacementRuntimeUnavailable`` instead.
    """

    FUNCTION = "placeVisual"

    def __init__(self, *, script_id: str, credentials: Any) -> None:
        script_id = script_id.strip() if isinstance(script_id, str) else ""
        if not script_id:
            raise PlacementRuntimeUnavailable(
                "placement-runtime-unavailable: no Apps Script placement deployment is "
                "configured (placement script id is empty). Deploy the governed "
                "VisualPlacementTransport script as an API executable and grant "
                "execution under the separately governed live-build authorization; "
                "until then a build with selected visuals cannot complete."
            )
        if credentials is None:
            raise PlacementRuntimeUnavailable(
                "placement-runtime-unavailable: no credentials supplied for the "
                "Apps Script Execution API call."
            )
        self._script_id = script_id
        self._credentials = credentials

    @property
    def name(self) -> str:
        return "apps-script-execution-api"

    def insert_placement(self, *, request: PlacementRequest) -> Mapping[str, Any]:
        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise PlacementRuntimeUnavailable(
                "placement-runtime-unavailable: googleapiclient is required for the "
                "Apps Script placement transport."
            ) from exc
        service = build("script", "v1", credentials=self._credentials)
        body = {"function": self.FUNCTION, "parameters": [_request_payload(request)]}
        try:
            response = service.scripts().run(scriptId=self._script_id, body=body).execute()
        except HttpError as exc:
            raise PlacementTransportError(
                f"placement-transport-failed: Apps Script Execution API call failed: {exc}"
            ) from exc
        except Exception as exc:
            raise PlacementTransportError(
                f"placement-transport-failed: Apps Script Execution API call raised {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(response, dict):
            raise PlacementTransportError("placement-transport-failed: execution API returned no response object")
        error = response.get("error")
        if error:
            raise PlacementTransportError(
                f"placement-transport-failed: remote placeVisual reported {error}"
            )
        result = (response.get("response") or {}).get("result") if isinstance(response.get("response"), dict) else None
        if not isinstance(result, Mapping):
            raise PlacementTransportError(
                "placement-transport-failed: execution API returned no placement result"
            )
        state = result.get("state")
        inserted = result.get("inserted_element_id")
        if state != "placed" or not isinstance(inserted, str) or not inserted.strip():
            raise PlacementTransportError(
                f"placement-transport-failed: remote result is not a completed placement: {dict(result)}"
            )
        return result


def build_placement_transport(*, script_id: str | None, credentials: Any) -> PlacementTransport | None:
    """Build the configured placement transport, or None when none is configured.

    A None return is not an error here: the caller converts it into the
    explicit ``placement-runtime-unavailable`` blocked state before any
    connected write. Only a configured deployment id yields a transport.
    """
    script = script_id.strip() if isinstance(script_id, str) else ""
    if not script:
        return None
    return AppsScriptPlacementTransport(script_id=script, credentials=credentials)
