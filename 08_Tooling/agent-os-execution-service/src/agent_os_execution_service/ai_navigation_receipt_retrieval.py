"""Fail-closed validation of a retrieved AI Navigation discovery receipt (local candidate, pure).

Inputs are plain values the *caller* fetched through its GitHub route; this module does no I/O,
no network and no GitHub call. It decides whether a retrieved artifact may be treated as the
receipt of one expected hosted run, and then applies ``verify_receipt``.

Provenance model (what each check does and does not show):
* ``run_metadata`` must come from GitHub (run object: id, run_attempt, head_sha, path, event,
  status, conclusion). It is never read from the artifact body. If the route cannot supply the
  workflow ``path`` and ``head_sha`` the result is ``blocked-by-workflow-run-metadata``; nothing
  is accepted as authentic.
* The artifact listing entry is checked for exact name, one match, not expired, linkage to the same
  run id and head SHA, and a ``sha256:`` digest. The downloaded ZIP bytes must hash to that digest.
  This shows the bytes equal what GitHub lists for that run. It is not a signature of the receipt.
* The receipt digest is unkeyed (see ``verify_receipt``): consistency and binding only.
Whether ChatGPT's connector can supply every input (notably the run ``path``) is UNPROVEN.
No hosted AI Navigation run exists yet, so this has only been exercised on synthetic inputs and
on public metadata of an unrelated run.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any, Mapping

from .ai_navigation_actions_operation import ActionsOperationRefused, admit_transport, verify_receipt

WORKFLOW_PATH = ".github/workflows/agent-os-ai-navigation-discover.yml"
ARTIFACT_NAME = "agent-os-ai-navigation-{run_id}-{attempt}"
RECEIPT_MEMBER = "receipt.json"
TRANSPORT_MEMBER = "transport.json"
ALLOWED_MEMBERS = frozenset({"receipt.json", "transport.json"})
MAX_MEMBER_BYTES = 65536
MAX_ZIP_BYTES = 1_048_576
_SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
_META_KEYS = ("id", "run_attempt", "head_sha", "path", "event", "status", "conclusion")


def _is_int(value: object) -> bool:
    return type(value) is int


def _result(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "authentic": False, **extra}


def _full_name(meta: Mapping[str, Any], key: str) -> object:
    repo = meta.get(key)
    return repo.get("full_name") if isinstance(repo, Mapping) else None


def validate_run_metadata(meta: object, *, run_id: int, run_attempt: int, head_sha: str,
                          repository: str | None = None) -> tuple[bool, str]:
    if not isinstance(meta, Mapping) or any(key not in meta for key in _META_KEYS):
        return False, "blocked-by-workflow-run-metadata"
    if type(repository) is not str:
        return False, "expected-repository-missing"
    if _full_name(meta, "repository") is None or _full_name(meta, "head_repository") is None:
        return False, "blocked-by-workflow-run-metadata"  # repository origin not supplied by the route
    if _full_name(meta, "repository") != repository or _full_name(meta, "head_repository") != repository:
        return False, "run-metadata-mismatch:repository"
    if not (_is_int(meta["id"]) and _is_int(meta["run_attempt"]) and type(meta["path"]) is str
            and type(meta["head_sha"]) is str and _SHA_RE.fullmatch(head_sha)):
        return False, "run-metadata-malformed"
    if meta["id"] != run_id or meta["run_attempt"] != run_attempt:
        return False, "run-metadata-mismatch:run"
    if meta["head_sha"] != head_sha:
        return False, "run-metadata-mismatch:head_sha"
    if meta["path"] != WORKFLOW_PATH:
        return False, "run-metadata-mismatch:workflow_path"
    if meta["event"] != "issue_comment":
        return False, "run-metadata-mismatch:event"
    if meta["status"] != "completed" or meta["conclusion"] != "success":
        return False, "run-not-completed-successfully"
    return True, "run-metadata-ok"


def select_artifact(listing: object, *, run_id: int, run_attempt: int, head_sha: str,
                    listing_proof: Mapping[str, Any] | None = None) -> tuple[Mapping[str, Any] | None, str]:
    """Exactly one expected artifact in a listing proven complete; otherwise (None, reason)."""
    if not isinstance(listing, Mapping) or type(listing.get("artifacts")) is not list:
        return None, "listing-missing"
    items = listing["artifacts"]
    total = listing.get("total_count")
    if total is not None:
        if not _is_int(total) or total != len(items):
            return None, "listing-incomplete"
    else:
        # No total_count: only an explicit first-page + no-continuation assertion AND a short page is accepted.
        # The assertion is the caller's (from the connector's paging fields); it is never inferred from size alone.
        proof = listing_proof
        if not (isinstance(proof, Mapping) and proof.get("page") == 1 and type(proof.get("page")) is int
                and proof.get("has_next_page") is False and _is_int(proof.get("page_size"))
                and proof["page_size"] >= 1 and len(items) < proof["page_size"]):
            return None, "listing-completeness-unprovable"
    name = ARTIFACT_NAME.format(run_id=run_id, attempt=run_attempt)
    matches = [a for a in items if isinstance(a, Mapping) and a.get("name") == name]
    if len(matches) != 1:
        return None, "artifact-absent" if not matches else "artifact-duplicate"
    art = matches[0]
    if art.get("expired") is not False:
        return None, "artifact-expired-or-unknown"
    wr = art.get("workflow_run")
    if not isinstance(wr, Mapping) or wr.get("id") != run_id or type(wr.get("id")) is not int or wr.get("head_sha") != head_sha:
        return None, "artifact-run-linkage-mismatch"
    if type(art.get("digest")) is not str or not _DIGEST_RE.fullmatch(art["digest"]):
        return None, "artifact-digest-missing"
    if not _is_int(art.get("size_in_bytes")) or not (0 < art["size_in_bytes"] <= MAX_ZIP_BYTES):
        return None, "artifact-size-invalid"
    return art, "artifact-selected"


_TRANSPORT_NULL_FIELDS = frozenset({
    "handoff_id_or_none", "dev_validation_branch_or_none", "dev_validation_sha_or_none", "dev_validation_id_or_none",
    "ppux_projection_branch_or_none", "ppux_projection_sha_or_none", "ppux_projection_input_ref_or_none",
    "source_capsule_id_or_none", "first_run_candidate_sha_or_none", "notion_read_request_id_or_none",
    "diagnostic_id_or_none", "diagnostic_request_id_or_none", "ruleset_prestate_sha256_or_none",
    "codespace_implementation_handoff_id_or_none", "codespace_implementation_sha_or_none",
    "ready_admission_pr_number_or_none", "ready_admission_head_sha_or_none", "ready_admission_body_sha256_or_none",
    "merge_admission_pr_number_or_none", "merge_admission_head_sha_or_none", "merge_admission_body_sha256_or_none",
    "merge_admission_method_or_none", "draft_validation_pr_number_or_none", "draft_validation_head_sha_or_none",
    "ready_recovery_pr_number_or_none", "ready_recovery_head_sha_or_none", "ready_recovery_main_sha_or_none",
    "ready_recovery_workflow_sha_or_none", "ready_recovery_source_run_id_or_none",
})
_TRANSPORT_FALSE_FIELDS = ("execution_authorized", "scheduler_invoked", "side_effects_performed")
_TRANSPORT_KEYS = frozenset({
    "schema_version", "status", "reason", "repository", "issue_number", "comment_id", "actor", "run_attempt",
    "logical_trigger_id_or_none",
}) | _TRANSPORT_NULL_FIELDS | frozenset(_TRANSPORT_FALSE_FIELDS)  # mirrors the ingress producer's to_dict()


def transport_shape_ok(transport: object) -> bool:
    """Canonical ingress transport shape for the discovery envelope: exact field set (drift-guarded by a
    test against the real producer), version 1.0, false authority flags, every inapplicable selector null."""
    if not isinstance(transport, Mapping) or set(transport) != _TRANSPORT_KEYS:
        return False
    if transport["schema_version"] != "1.0":
        return False
    if any(transport[k] is not False for k in _TRANSPORT_FALSE_FIELDS):
        return False
    if any(transport[k] is not None for k in _TRANSPORT_NULL_FIELDS):
        return False
    return all(type(transport[k]) is str for k in ("status", "reason", "repository", "actor", "logical_trigger_id_or_none")) \
        and all(_is_int(transport[k]) for k in ("issue_number", "comment_id", "run_attempt"))


def _no_dupe_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite JSON constant")


def _strict_json(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"), object_pairs_hook=_no_dupe_keys, parse_constant=_no_constant)


def read_members_from_zip(blob: object, artifact: Mapping[str, Any]) -> tuple[tuple[Any, Any] | None, str]:
    """(receipt, transport) parsed with strict JSON; both members are required."""
    if type(blob) is not bytes or len(blob) != artifact["size_in_bytes"]:
        return None, "zip-size-mismatch"
    if "sha256:" + hashlib.sha256(blob).hexdigest() != artifact["digest"]:
        return None, "zip-digest-mismatch"
    parsed: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            if any(i.orig_filename != i.filename or "\x00" in i.orig_filename or "\x00" in i.filename for i in infos):
                return None, "zip-member-name-ambiguous"  # raw vs decoded name disagreement / NUL alias
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                return None, "zip-duplicate-member"
            if set(names) != ALLOWED_MEMBERS:
                return None, "zip-unexpected-members"
            for info in infos:
                if info.file_size > MAX_MEMBER_BYTES or info.is_dir() or (info.external_attr >> 28) == 0xA \
                        or info.flag_bits & 0x1:
                    return None, "zip-member-invalid"
                data = zf.open(info).read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES or len(data) != info.file_size:
                    return None, "zip-member-invalid"
                try:
                    parsed[info.filename] = _strict_json(data)
                except (UnicodeDecodeError, ValueError, RecursionError):
                    return None, f"{info.filename.split('.')[0]}-malformed"
    except Exception:  # corrupt streams (zlib.error, EOFError, BadZipFile, ...) fail closed, structured
        return None, "zip-malformed"
    return (parsed[RECEIPT_MEMBER], parsed[TRANSPORT_MEMBER]), "members-read"


def validate_retrieved_receipt(
    *, run_metadata: object, listing: object, zip_bytes: object,
    expected_binding: Mapping[str, Any], listing_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every check in order; the first failure stops. `authentic` is always False:
    a pass means GitHub-listed bytes for the expected run, well-formed and bound, nothing more."""
    run_id, attempt, sha = expected_binding.get("run_id"), expected_binding.get("run_attempt"), expected_binding.get("source_sha")
    if not (_is_int(run_id) and _is_int(attempt) and type(sha) is str):
        return _result("rejected", "expected-binding-malformed")
    repo = expected_binding.get("repository")
    ok, why = validate_run_metadata(run_metadata, run_id=run_id, run_attempt=attempt, head_sha=sha, repository=repo)
    if not ok:
        return _result("blocked" if why == "blocked-by-workflow-run-metadata" else "rejected", why)
    art, why = select_artifact(listing, run_id=run_id, run_attempt=attempt, head_sha=sha, listing_proof=listing_proof)
    if art is None:
        return _result("blocked" if why in ("listing-completeness-unprovable", "listing-incomplete", "listing-missing") else "rejected", why)
    members, why = read_members_from_zip(zip_bytes, art)
    if members is None:
        return _result("rejected", why)
    receipt, transport = members
    if not transport_shape_ok(transport):
        return _result("rejected", "transport-shape-invalid")
    try:
        bound = admit_transport(transport, expected_repository=repo, allowed_actor=expected_binding.get("actor"),
                                run_id=run_id, source_sha=sha, owning_issue=expected_binding.get("issue_number"))
    except (ActionsOperationRefused, TypeError):
        return _result("rejected", "transport-refused")
    if dict(bound) != dict(expected_binding):
        return _result("rejected", "transport-binding-mismatch")
    ok, why = verify_receipt(receipt, expected_binding=expected_binding)
    if not ok:
        return _result("rejected", f"receipt-{why}")
    return _result("verified-consistent", "run-bound-and-well-formed", receipt_status=receipt["status"],
                   receipt_reason_codes=receipt["reason_codes"])
