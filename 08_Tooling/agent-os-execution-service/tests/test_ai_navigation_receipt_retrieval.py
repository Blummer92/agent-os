"""Retrieved-receipt validation tests (local candidate, pure functions).

Real: the validator, ``verify_receipt`` and the module's own receipt producer.
Synthetic: every run object, listing and ZIP below is built here. No hosted AI Navigation run
exists. One test replays PUBLIC metadata of an unrelated governed-ingress run (43600640726,
read from the GitHub REST API today) as a negative control; its ZIP was not downloaded.
NOT exercised: ChatGPT's connector, any real receipt, authentic provenance (unproven).
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile

import pytest

import agent_os_execution_service.ai_navigation_actions_operation as op
import agent_os_execution_service.ai_navigation_receipt_retrieval as rr

REPO = "Blummer92/agent-os"
SHA = "c" * 40
RUN, ATT, ISSUE = 555, 1, 77


def _binding():
    return {"repository": REPO, "issue_number": ISSUE, "comment_id": 9, "run_id": RUN,
            "run_attempt": ATT, "source_sha": SHA, "actor": "Blummer92"}


def _receipt(**mut):
    r = op.run_readonly_discovery(_binding(), {})
    if mut:
        r = {k: v for k, v in r.items() if k != "receipt_digest"}
        r.update(mut)
        r["receipt_digest"] = op._digest(r)
    return r


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _transport(**over):
    """Transport produced by the REAL existing ingress parser (then optionally tampered)."""
    from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

    event = {"action": "created", "repository": {"full_name": REPO}, "issue": {"number": ISSUE},
             "comment": {"id": 9, "body": "/agent-os ai-navigation-discover", "user": {"login": "Blummer92"}},
             "sender": {"login": "Blummer92"}}
    base = admit_issue_comment_event(event, expected_repository=REPO, allowed_actor="Blummer92", run_attempt=ATT).to_dict()
    base.update(over)
    return base


def _good_zip(receipt=None, transport=None):
    return _zip([("transport.json", json.dumps(transport or _transport())), ("receipt.json", json.dumps(receipt or _receipt()))])


def _meta(**over):
    m = {"id": RUN, "run_attempt": ATT, "head_sha": SHA, "path": rr.WORKFLOW_PATH,
         "event": "issue_comment", "status": "completed", "conclusion": "success",
         "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO}}
    m.update(over)
    return m


def _listing(blob, **over):
    art = {"id": 1, "name": rr.ARTIFACT_NAME.format(run_id=RUN, attempt=ATT), "size_in_bytes": len(blob),
           "digest": "sha256:" + hashlib.sha256(blob).hexdigest(), "expired": False,
           "workflow_run": {"id": RUN, "head_sha": SHA}}
    art.update(over)
    return {"total_count": 1, "artifacts": [art]}


def _run(blob=None, meta=None, listing=None, **kw):
    blob = _good_zip() if blob is None else blob
    return rr.validate_retrieved_receipt(
        run_metadata=_meta() if meta is None else meta,
        listing=_listing(blob) if listing is None else listing,
        zip_bytes=blob, expected_binding=_binding(), **kw)


def test_happy_path_is_consistent_but_never_authentic():
    out = _run()
    assert out["status"] == "verified-consistent" and out["authentic"] is False
    assert out["receipt_status"] == "blocked" and out["receipt_reason_codes"] == ["store-root-not-configured"]


@pytest.mark.parametrize("meta,why,status", [
    (None, "blocked-by-workflow-run-metadata", "blocked"),
    ({k: v for k, v in _meta().items() if k != "path"}, "blocked-by-workflow-run-metadata", "blocked"),
    ({k: v for k, v in _meta().items() if k != "head_sha"}, "blocked-by-workflow-run-metadata", "blocked"),
    (_meta(id=556), "run-metadata-mismatch:run", "rejected"),
    (_meta(run_attempt=2), "run-metadata-mismatch:run", "rejected"),
    (_meta(head_sha="d" * 40), "run-metadata-mismatch:head_sha", "rejected"),
    (_meta(path=".github/workflows/agent-os-governed-invocation.yml"), "run-metadata-mismatch:workflow_path", "rejected"),
    (_meta(path=".github/workflows/agent-os-ai-navigation-discover.yml.bak"), "run-metadata-mismatch:workflow_path", "rejected"),
    (_meta(event="workflow_dispatch"), "run-metadata-mismatch:event", "rejected"),
    (_meta(conclusion="failure"), "run-not-completed-successfully", "rejected"),
    (_meta(status="in_progress", conclusion=None), "run-not-completed-successfully", "rejected"),
    (_meta(id=True), "run-metadata-malformed", "rejected"),
    (_meta(path=7), "run-metadata-malformed", "rejected"),
])
def test_run_metadata_must_come_from_github_and_match(meta, why, status):
    out = _run(meta=meta if meta is not None else "absent")
    assert (out["status"], out["reason"]) == (status, why)


def test_wrong_run_metadata_is_not_rescued_by_artifact_body():
    """Receipt body claims the right run; GitHub metadata says otherwise -> rejected."""
    assert _run(meta=_meta(id=999))["reason"] == "run-metadata-mismatch:run"


def test_public_metadata_of_unrelated_ingress_run_is_rejected():
    real = {"id": 43600640726, "run_attempt": 1, "head_sha": "0b3bd0d69b48dc4a81d3a0b3c5f125245ef93791",
            "path": ".github/workflows/agent-os-governed-invocation.yml", "event": "issue_comment",
            "status": "completed", "conclusion": "success",
            "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO}}
    b = {**_binding(), "run_id": 43600640726, "source_sha": real["head_sha"]}
    out = rr.validate_retrieved_receipt(run_metadata=real, listing={"total_count": 0, "artifacts": []},
                                        zip_bytes=b"", expected_binding=b)
    assert out["reason"] == "run-metadata-mismatch:workflow_path"


@pytest.mark.parametrize("over,why", [
    ({"name": "agent-os-ai-navigation-555-2"}, "artifact-absent"),
    ({"expired": True}, "artifact-expired-or-unknown"),
    ({"expired": None}, "artifact-expired-or-unknown"),
    ({"workflow_run": {"id": 556, "head_sha": SHA}}, "artifact-run-linkage-mismatch"),
    ({"workflow_run": {"id": RUN, "head_sha": "d" * 40}}, "artifact-run-linkage-mismatch"),
    ({"workflow_run": None}, "artifact-run-linkage-mismatch"),
    ({"digest": None}, "artifact-digest-missing"),
    ({"digest": "md5:abc"}, "artifact-digest-missing"),
    ({"size_in_bytes": 0}, "artifact-size-invalid"),
    ({"size_in_bytes": 10**9}, "artifact-size-invalid"),
])
def test_artifact_selection_negative_controls(over, why):
    blob = _good_zip()
    assert _run(blob, listing=_listing(blob, **over))["reason"] == why


def test_duplicate_artifact_and_incomplete_or_unprovable_listing():
    blob = _good_zip()
    one = _listing(blob)
    dup = {"total_count": 2, "artifacts": one["artifacts"] * 2}
    assert _run(blob, listing=dup)["reason"] == "artifact-duplicate"
    assert _run(blob, listing={"total_count": 5, "artifacts": one["artifacts"]})["reason"] == "listing-incomplete"
    no_total = {"artifacts": one["artifacts"]}
    out = _run(blob, listing=no_total)  # connector shape: first page, no total_count
    assert (out["status"], out["reason"]) == ("blocked", "listing-completeness-unprovable")
    assert _run(blob, listing=no_total, listing_proof={"page": 1, "has_next_page": False, "page_size": 30})["status"] == "verified-consistent"  # short page proves completeness
    full = {"artifacts": one["artifacts"] * 1}
    assert _run(blob, listing=full, listing_proof={"page": 1, "has_next_page": False, "page_size": 1})["reason"] == "listing-completeness-unprovable"  # page full -> unknown
    missing = rr.validate_retrieved_receipt(run_metadata=_meta(), listing=None, zip_bytes=blob, expected_binding=_binding())
    assert (missing["status"], missing["reason"]) == ("blocked", "listing-missing")
    assert _run(blob, listing={"total_count": True, "artifacts": one["artifacts"]})["reason"] == "listing-incomplete"


def test_zip_altered_or_malformed():
    blob = _good_zip()
    listing = _listing(blob)
    altered = blob[:-1] + bytes([blob[-1] ^ 1])
    assert _run(altered, listing=listing)["reason"] == "zip-digest-mismatch"
    assert _run(blob + b"x", listing=listing)["reason"] == "zip-size-mismatch"
    assert _run("text", listing=listing)["reason"] == "zip-size-mismatch"
    junk = b"not a zip" * 5
    assert _run(junk, listing=_listing(junk))["reason"] == "zip-malformed"


@pytest.mark.parametrize("members,why", [
    ([("transport.json", "{}")], "zip-unexpected-members"),
    ([("receipt.json", "{}")], "zip-unexpected-members"),
    ([("receipt.json", "{}"), ("extra.json", "{}")], "zip-unexpected-members"),
    ([("transport.json", "{}"), ("receipt.json", "{}"), ("extra.json", "{}")], "zip-unexpected-members"),
    ([("sub/receipt.json", "{}")], "zip-unexpected-members"),
    ([("../receipt.json", "{}")], "zip-unexpected-members"),
    ([("transport.json", "{}"), ("receipt.json", "not json")], "receipt-malformed"),
    ([("transport.json", "{}"), ("receipt.json", b"\xff\xfe")], "receipt-malformed"),
    ([("transport.json", "{}"), ("receipt.json", "x" * 70000)], "zip-member-invalid"),
])
def test_zip_member_rules(members, why):
    blob = _zip(members)
    assert _run(blob, listing=_listing(blob))["reason"] == why


def test_duplicate_member_names_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("receipt.json", json.dumps(_receipt()))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            zf.writestr("receipt.json", json.dumps(_receipt()))
    blob = buf.getvalue()
    assert _run(blob, listing=_listing(blob))["reason"] == "zip-duplicate-member"


@pytest.mark.parametrize("mut,why", [
    ({"status": "garbage"}, "receipt-status-unknown"),
    ({"status": "not-found", "reason_codes": ["no-matching-descriptor"], "matching_descriptor_count": 7, "handoff_present": False}, "receipt-not-found-inconsistent"),
    ({"run_id": 556}, "receipt-binding-mismatch:run_id"),
    ({"run_attempt": 2}, "receipt-binding-mismatch:run_attempt"),
    ({"source_sha": "d" * 40}, "receipt-binding-mismatch:source_sha"),
    ({"comment_id": 10}, "receipt-binding-mismatch:comment_id"),
    ({"execution_authorized": True}, "receipt-authority-flag-not-false"),
])
def test_receipt_content_failures_even_with_valid_zip_and_digest(mut, why):
    blob = _good_zip(_receipt(**mut))
    assert _run(blob, listing=_listing(blob))["reason"] == why


def test_forged_but_well_bound_receipt_still_passes_the_documented_limit():
    """Known, labeled limitation: a forger who knows the public binding and can make the artifact
    appear under the real run would pass. Hence `authentic` is always False."""
    forged = _receipt(status="not-found", reason_codes=["no-matching-descriptor"], matching_descriptor_count=0, handoff_present=False)
    blob = _good_zip(forged)
    out = _run(blob, listing=_listing(blob))
    assert out["status"] == "verified-consistent" and out["authentic"] is False


def test_expected_binding_malformed_and_no_io_surface():
    assert rr.validate_retrieved_receipt(run_metadata=_meta(), listing={}, zip_bytes=b"", expected_binding={})["reason"] == "expected-binding-malformed"
    import ast, pathlib
    src = pathlib.Path(rr.__file__).read_text()
    mods = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not mods & {"requests", "urllib", "subprocess", "socket", "http", "shutil", "os", "pathlib"}
    assert "open(" not in src.replace("zf.open(", "") and "write" not in src.replace("writestr", "")


# ---- repair after independent QA (ACTIONS6) ----
def _status(out):
    return out["status"], out["reason"]


def _zipped(transport_bytes, receipt=None):
    return _zip([("transport.json", transport_bytes), ("receipt.json", json.dumps(receipt or _receipt()))])


@pytest.mark.parametrize("tb,reason", [
    ("{", "transport-malformed"),
    ("[]", "transport-shape-invalid"),
    ("{}", "transport-shape-invalid"),
    (json.dumps(_transport(status="rejected")), "transport-refused"),
    (json.dumps(_transport(repository="evil/wrong")), "transport-refused"),
    (json.dumps(_transport(actor="mallory")), "transport-refused"),
    (json.dumps(_transport(issue_number=78)), "transport-refused"),
    (json.dumps(_transport(comment_id=10)), "transport-binding-mismatch"),
    (json.dumps(_transport(run_attempt=2)), "transport-binding-mismatch"),
    ('{"status":"rejected","status":"accepted"}', "transport-malformed"),
])
def test_transport_is_read_and_bound(tb, reason):
    assert _status(_run(_zipped(tb))) == ("rejected", reason)


def test_transport_oversized_and_symlink_and_missing():
    big = _zipped(" " * (rr.MAX_MEMBER_BYTES + 1) + json.dumps(_transport()))
    assert _run(big)["reason"] == "zip-member-invalid"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zi = zipfile.ZipInfo("transport.json")
        zi.external_attr = (0o120777 << 16)
        zf.writestr(zi, "x")
        zf.writestr("receipt.json", json.dumps(_receipt()))
    assert _run(buf.getvalue())["reason"] == "zip-member-invalid"
    assert _run(_zip([("receipt.json", json.dumps(_receipt()))]))["reason"] == "zip-unexpected-members"


@pytest.mark.parametrize("over", [
    {"repository": {"full_name": "evil/wrong"}},
    {"head_repository": {"full_name": "evil/wrong"}},
])
def test_wrong_repository_metadata_rejected(over):
    assert _status(_run(meta=_meta(**over))) == ("rejected", "run-metadata-mismatch:repository")


@pytest.mark.parametrize("drop", ["repository", "head_repository"])
def test_missing_repository_metadata_blocks(drop):
    m = _meta()
    del m[drop]
    assert _status(_run(meta=m)) == ("blocked", "blocked-by-workflow-run-metadata")
    m = _meta(**{drop: None})
    assert _status(_run(meta=m)) == ("blocked", "blocked-by-workflow-run-metadata")


@pytest.mark.parametrize("proof", [
    None, {}, {"page_size": 100}, {"page": 7, "has_next_page": True, "page_size": 100},
    {"page": 7, "has_next_page": False, "page_size": 100}, {"page": 1, "has_next_page": True, "page_size": 100},
    {"page": 1, "page_size": 100}, {"page": 1, "has_next_page": False}, {"page": True, "has_next_page": False, "page_size": 100},
])
def test_no_total_requires_explicit_first_page_without_continuation(proof):
    blob = _good_zip()
    listing = _listing(blob)
    listing.pop("total_count")
    assert _status(_run(blob, listing=listing, listing_proof=proof)) == ("blocked", "listing-completeness-unprovable")
    assert _run(blob, listing=listing)["reason"] == "listing-completeness-unprovable"


def test_corrupt_deflate_with_recomputed_digest_is_structured():
    good = bytearray(_good_zip())
    # corrupt the compressed stream of the first member, keep sizes; digest/size are recomputed by the helpers
    i = good.index(b"transport.json") + len("transport.json") + 4
    for k in range(i, i + 12):
        good[k] ^= 0xFF
    out = _run(bytes(good))
    assert out["status"] == "rejected" and out["authentic"] is False
    assert out["reason"] in ("zip-malformed", "zip-member-invalid", "transport-malformed", "zip-digest-mismatch")


def test_duplicate_conflicting_receipt_keys_refused():
    raw = json.dumps(_receipt()).replace('"status": "blocked"', '"status": "blocked", "status": "ready"', 1)
    assert raw.count('"status"') >= 2
    blob = _zip([("transport.json", json.dumps(_transport())), ("receipt.json", raw)])
    assert _status(_run(blob)) == ("rejected", "receipt-malformed")


def test_non_finite_constants_refused():
    blob = _zip([("transport.json", json.dumps(_transport())), ("receipt.json", '{"a": NaN}')])
    assert _run(blob)["reason"] == "receipt-malformed"


def test_nul_alias_member_name_refused():
    # Build with a placeholder byte, then patch it to NUL in local header and central directory
    # (zipfile truncates NUL names when writing, so the raw bytes must be crafted).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("transport.json", json.dumps(_transport()))
        zf.writestr("receipt.jsonXhidden", json.dumps(_receipt()))
    raw = buf.getvalue().replace(b"receipt.jsonXhidden", b"receipt.json\x00hidden")
    assert raw.count(b"receipt.json\x00hidden") == 2
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert any(i.orig_filename != i.filename for i in zf.infolist())  # the aliasing the QA probe found
    out = _run(raw)
    assert (out["status"], out["reason"]) == ("rejected", "zip-member-name-ambiguous")


def test_transport_shape_matches_real_producer_field_set():
    assert set(_transport()) == rr._TRANSPORT_KEYS  # drift guard against the ingress producer
    assert rr.transport_shape_ok(_transport())


@pytest.mark.parametrize("over", [
    {"execution_authorized": True}, {"scheduler_invoked": True}, {"side_effects_performed": True},
    {"execution_authorized": 0}, {"schema_version": "nonsense"}, {"schema_version": 1.0},
    {"handoff_id_or_none": "h1"}, {"merge_admission_pr_number_or_none": 5}, {"ready_recovery_source_run_id_or_none": 1},
    {"codespace_implementation_sha_or_none": "a" * 40}, {"extra_field": 1}, {"comment_id": True},
])
def test_noncanonical_transport_with_matching_digest_rejected(over):
    blob = _zipped(json.dumps(_transport(**over)))  # ZIP and listing digest are valid for these bytes
    assert _status(_run(blob)) == ("rejected", "transport-shape-invalid") or _run(blob)["reason"] == "transport-refused"
    assert _run(blob)["status"] == "rejected"


def test_transport_missing_field_rejected():
    tr = _transport()
    del tr["scheduler_invoked"]
    assert _status(_run(_zipped(json.dumps(tr)))) == ("rejected", "transport-shape-invalid")
