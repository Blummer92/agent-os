"""#3257: producer revision-identity hardening (R1 producer repair).

The placement transport seam must preserve and enforce artifact revision
identity end to end:

- ``_request_payload`` refuses to build a request without the target's
  artifact revision id (fail closed; never send a revision-less request).
- ``AppsScriptPlacementTransport.insert_placement`` rejects the pre-repair
  synthetic ``docs-child-<index>`` element id (never a real persisted Docs
  inline object id) and requires the hardened reference's read-back
  post-placement revision evidence.

The reference Apps Script itself is covered by the Node conformance suite
(``apps-script/test/visual-placement-transport.conformance.test.mjs``);
these tests cover the Python adapter side with an injected fake
``googleapiclient``. No live Execution API call occurs.
"""
from __future__ import annotations

import sys
import types

import pytest

from instructional_materials_coach.placement_transport import (
    AppsScriptPlacementTransport,
    PlacementTransportError,
    _request_payload,
)
from instructional_materials_coach.visual_placement import PlacementRequest, PlacementTarget


def _target(revision: str = "r1") -> PlacementTarget:
    return PlacementTarget(
        artifact_type="docs",
        artifact_id="doc-1",
        artifact_revision_id=revision,
        role_id="figure",
        marker="{{visual:figure}}",
        container_id="body",
        element_id="body-child-0",
        index=0,
    )


def _request(revision: str = "r1") -> PlacementRequest:
    return PlacementRequest(
        asset_id="asset-1",
        drive_file_id="file-1",
        role_id="figure",
        source_plan_id="plan-1",
        target=_target(revision),
        content_identity={"sha256": "abc"},
    )


def _install_fake_googleapiclient(monkeypatch, result):
    """Inject a fake googleapiclient whose scripts().run().execute()
    returns an Execution API response carrying ``result``."""
    calls: dict = {}

    class _Scripts:
        def run(self, *, scriptId, body):
            calls["scriptId"] = scriptId
            calls["body"] = body
            return self

        def execute(self):
            return {"response": {"result": result}}

    class _Service:
        def scripts(self):
            return _Scripts()

    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = lambda *args, **kwargs: _Service()
    errors = types.ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        pass

    errors.HttpError = HttpError
    package = types.ModuleType("googleapiclient")
    package.__path__ = []
    package.discovery = discovery
    package.errors = errors
    monkeypatch.setitem(sys.modules, "googleapiclient", package)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)
    monkeypatch.setitem(sys.modules, "googleapiclient.errors", errors)
    return calls


def _transport() -> AppsScriptPlacementTransport:
    return AppsScriptPlacementTransport(script_id="script-1", credentials=object())


# ---------------------------------------------------------------------------
# _request_payload: revision identity is mandatory
# ---------------------------------------------------------------------------


def test_request_payload_carries_artifact_revision_id():
    payload = _request_payload(_request("r1"))
    assert payload["target"]["artifact_revision_id"] == "r1"


@pytest.mark.parametrize("revision", ["", "   "])
def test_request_payload_rejects_missing_revision_id(revision):
    with pytest.raises(PlacementTransportError, match="no artifact revision identity"):
        _request_payload(_request(revision))


# ---------------------------------------------------------------------------
# insert_placement: hardened result contract
# ---------------------------------------------------------------------------


def test_insert_placement_rejects_synthetic_element_id(monkeypatch):
    _install_fake_googleapiclient(
        monkeypatch,
        {
            "state": "placed",
            "inserted_element_id": "docs-child-0",
            "post_placement_revision_id": "r1-p",
        },
    )
    with pytest.raises(PlacementTransportError, match="synthetic"):
        _transport().insert_placement(request=_request("r1"))


def test_insert_placement_rejects_missing_revision_evidence(monkeypatch):
    _install_fake_googleapiclient(
        monkeypatch,
        {"state": "placed", "inserted_element_id": "kix.abc123"},
    )
    with pytest.raises(PlacementTransportError, match="no post-placement revision evidence"):
        _transport().insert_placement(request=_request("r1"))


def test_insert_placement_accepts_hardened_result_and_sends_revision(monkeypatch):
    calls = _install_fake_googleapiclient(
        monkeypatch,
        {
            "state": "placed",
            "inserted_element_id": "kix.abc123",
            "requested_revision_id": "r1",
            "post_placement_revision_id": "r1-p",
        },
    )
    result = _transport().insert_placement(request=_request("r1"))
    assert result["inserted_element_id"] == "kix.abc123"
    assert result["post_placement_revision_id"] == "r1-p"
    # The revision identity the request was validated against is what the
    # runtime received.
    sent = calls["body"]["parameters"][0]
    assert sent["target"]["artifact_revision_id"] == "r1"


def test_insert_placement_still_rejects_incomplete_results(monkeypatch):
    _install_fake_googleapiclient(
        monkeypatch,
        {"state": "placed", "inserted_element_id": "   "},
    )
    with pytest.raises(PlacementTransportError, match="not a completed placement"):
        _transport().insert_placement(request=_request("r1"))
