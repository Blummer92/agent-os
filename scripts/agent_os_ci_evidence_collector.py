"""Read-only CI evidence collector for Agent OS.

Pure classification functions are unit-tested; the network ``main`` is only
used by the ``workflow_run`` collector workflow on the trusted default branch
with ``actions: read`` / ``contents: read``. It never checks out PR code, never
imports or executes artifact content, and never writes to Sheets or any merge
authority. Downloaded artifacts are treated as hostile data: ZIP members are
validated (no traversal, symlinks, duplicates, or oversize expansion) before
any JSON/XML parsing, and only advisory JSON and JUnit XML are parsed.

Source identity always comes from the triggering ``workflow_run`` event and
the Actions API (run id, attempt, head SHA), never from the collector's own
``GITHUB_SHA`` and never from self-reported manifest fields.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import stat
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_os_ci_evidence_health import (  # noqa: E402
    AdvisoryReport,
    StreamObservation,
    classify_stream,
    validate_advisory_report,
    validate_junit,
)

import hashlib

# P0: the producing workflow names the Pyan artifact "pyan3-advisory-<PR>",
# not "pyan-advisory-<PR>". The ledger-facing stream key stays "pyan";
# only the provider artifact prefix is "pyan3". The old ("pyan", "jscpd")
# tuple made the pyan stream undetectable in the live path.
ARTIFACT_PREFIXES = {"pyan": "pyan3-advisory", "jscpd": "jscpd-advisory"}
HEALTH_PREFIXES = {"pyan": "pyan3-health", "jscpd": "jscpd-health"}
ADVISORY_JOB_NAMES = {
    "pyan": "pyan3 call-graph advisory",
    "jscpd": "jscpd duplicate-code advisory",
}
ADVISORY_REPORT_FILES = {"pyan": "pyan3-advisory.json", "jscpd": "jscpd-advisory.json"}
VALIDATION_WORKFLOW_PATH = ".github/workflows/agent-os-validation.yml"
AGGREGATE_STEP_NAME = "Run aggregate validation"
# Exact provider job->artifact binding is NOT available in the public REST
# API: artifact objects carry workflow_run id/head but no job id, and job
# objects carry no artifact ids. Job identity below is therefore BY NAME
# (the workflow gives each advisory job a distinct name and a distinct
# artifact prefix), and per_job_join stays NOT_IMPLEMENTED_EXACT. A stream
# classified EVIDENCE_VALID here means: artifact present, not expired, ZIP
# valid, provider digest matches where the provider supplies one, report
# schema/status/head valid, and the same-named job succeeded on the same
# attempt. It does not mean the provider proved that job produced that
# artifact. Downstream ingestion must not drop that distinction.
JOB_BINDING = "BY_NAME_DESIGN"


SCHEMA = "agent-os-ci-evidence-collector/1"
MAX_ARCHIVE_BYTES = 64_000_000
MAX_ARCHIVE_ENTRIES = 1_000


def validate_archive_member_names(names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        if not name or name.startswith("/") or "\\" in name:
            raise ValueError(f"unsafe archive member name: {name!r}")
        parts = name.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"unsafe archive member name: {name!r}")
        if name in seen:
            raise ValueError(f"duplicate archive member: {name!r}")
        seen.add(name)


def validate_archive_members(data: bytes, *, max_total_bytes: int = MAX_ARCHIVE_BYTES, max_entries: int = MAX_ARCHIVE_ENTRIES) -> list[str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid archive") from exc
    members = zf.infolist()
    if len(members) > max_entries:
        raise ValueError("archive entry count exceeds limit")
    total = 0
    for info in members:
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if stat.S_ISLNK(mode):
            raise ValueError(f"symlink archive member rejected: {info.filename!r}")
        total += info.file_size
        if total > max_total_bytes:
            raise ValueError("archive expansion exceeds limit")
    validate_archive_member_names([info.filename for info in members if not info.is_dir()])
    return [info.filename for info in members if not info.is_dir()]


def build_collector_receipt(
    *,
    source_run_id: int,
    source_run_attempt: int,
    source_head: str,
    collector_head: str,
    streams: list[dict],
    junit_files: dict[str, bytes],
    live_trigger: bool = False,
) -> dict:
    classified: dict[str, str] = {}
    for stream in streams:
        observation = StreamObservation(
            stream=str(stream["stream"]),
            obligation=str(stream["obligation"]),
            source_head=source_head,
            reported_head=str(stream["reported_head"]),
            run_attempt=source_run_attempt,
            artifact_attempt=int(stream["artifact_attempt"]),
            job_id=int(stream["job_id"]),
            artifact_job_id=int(stream["artifact_job_id"]),
            artifact_present=bool(stream["artifact_present"]),
            artifact_expired=bool(stream["artifact_expired"]),
            schema_valid=bool(stream["schema_valid"]),
            job_conclusion=str(stream["job_conclusion"]),
            scanner_status=str(stream.get("scanner_status", "completed")),
            artifact_bytes=b"",
            claimed_sha256=None,
        )
        classified[observation.stream] = classify_stream(observation)
    junit: dict[str, dict] = {}
    for name, data in junit_files.items():
        try:
            ids, counts = validate_junit(data)
            junit[name] = {"classification": "EVIDENCE_VALID", "counts": counts, "node_count": len(ids)}
        except ValueError as exc:
            junit[name] = {"classification": "REJECT_SCHEMA", "counts": None, "error": str(exc)}
    return {
        "schema": SCHEMA,
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_head": source_head,
        "collector_head": collector_head,
        "streams": classified,
        "junit": junit,
        "live_trigger": live_trigger,
        "sheets_written": False,
        "note": "Read-only receipt. A classification here is not a merge, Ready, or Sheets decision.",
    }



def verify_source_run(run: dict, *, expected_run_id: int, expected_head: str, expected_path: str = VALIDATION_WORKFLOW_PATH) -> None:
    """Fail closed on any source-run identity mismatch. Raises ValueError."""
    if int(run.get("id", -1)) != expected_run_id:
        raise ValueError("source run id mismatch")
    if run.get("head_sha") != expected_head:
        raise ValueError("source head mismatch")
    if run.get("path") != expected_path:
        raise ValueError("source workflow path mismatch")
    if run.get("status") != "completed":
        raise ValueError("source run is not completed")


def job_by_name(jobs: list[dict], name: str, *, expected_attempt: int | None = None) -> dict | None:
    """Return the job with this name (and attempt, when given). Duplicate
    identities for one name+attempt are a provider anomaly, not a choice."""
    matches = [j for j in jobs if j.get("name") == name and (expected_attempt is None or int(j.get("run_attempt", -1)) == expected_attempt)]
    if len(matches) > 1:
        raise ValueError(f"duplicate job identity for {name!r}")
    return matches[0] if matches else None


def aggregate_obligation(validate_job: dict | None) -> str:
    """Map the validate job to the aggregate stream obligation. A skipped
    job is a Draft deferral. A successful job whose aggregate step was
    skipped is the reused-aggregate case: the aggregate ran on another run,
    so this collector must not claim its evidence. Anything else is
    required."""
    if validate_job is None:
        return "not_applicable"
    if validate_job.get("conclusion") == "skipped":
        return "deferred"
    for step in validate_job.get("steps") or []:
        if step.get("name") == AGGREGATE_STEP_NAME and step.get("conclusion") == "skipped":
            return "reused"
    return "required"


def _attempt_suffix(name: str, prefix: str) -> int | None:
    """Attempt encoded by the revised workflow name '<prefix>-<PR>-attempt-<n>'.
    Legacy names without a suffix return None (attempt binding by job only)."""
    if not name.startswith(prefix + "-"):
        return None
    tail = name[len(prefix) + 1:]
    if "-attempt-" not in tail:
        return None
    try:
        return int(tail.rsplit("-attempt-", 1)[1])
    except ValueError:
        return None


def select_advisory_artifact(artifacts: list[dict], stream: str, *, source_attempt: int | None = None) -> dict | None:
    """Select one advisory artifact for a stream by its true provider
    prefix. A current-attempt suffix wins over a legacy name; a duplicate
    name is rejected rather than silently picked. Returns None when absent
    (missing evidence, not an error).

    Attempt fidelity (correction 2026-11-02): when a source attempt is
    bound, an artifact whose explicit '-attempt-N' suffix differs from it
    is NEVER returned as a fallback -- returning it would certify an
    older attempt's report as current evidence. A legacy (unsuffixed) name
    is returned only for source attempt 1, the explicit legacy policy:
    legacy names carry no attempt binding, so they are not evidence for
    attempt 2 or later. Callers that need to distinguish 'no artifact' from
    'only a mismatched-attempt artifact exists' use
    explicit_attempt_mismatch() / legacy_unbound() alongside this helper."""
    prefix = ARTIFACT_PREFIXES[stream]
    matches = [a for a in artifacts if isinstance(a, dict) and str(a.get("name", "")).startswith(prefix)]
    names = {str(a.get("name")) for a in matches}
    if len(matches) != len(names):
        raise ValueError(f"duplicate artifact identity for prefix {prefix!r}")
    if source_attempt is not None:
        exact = [a for a in matches if _attempt_suffix(str(a.get("name")), prefix) == source_attempt]
        if exact:
            if len(exact) > 1:
                raise ValueError(f"duplicate artifact identity for attempt {source_attempt}")
            return exact[0]
        legacy = [a for a in matches if _attempt_suffix(str(a.get("name")), prefix) is None]
        if legacy and source_attempt == 1:
            return legacy[0]
        # No current-attempt artifact: do not fall back to a suffixed
        # mismatch or to an unbound legacy name for attempt >= 2.
        return None
    return matches[0] if matches else None


def explicit_attempt_mismatch(artifacts: list[dict], stream: str, source_attempt: int) -> bool:
    """True when a non-expired artifact for this stream carries an
    explicit '-attempt-N' suffix different from the requested attempt.
    Used by receipt builders to report REJECT_WRONG_ATTEMPT instead of
    plain EVIDENCE_MISSING when selection returned None."""
    prefix = ARTIFACT_PREFIXES[stream]
    return any(
        isinstance(a, dict) and not a.get("expired")
        and str(a.get("name", "")).startswith(prefix)
        and _attempt_suffix(str(a.get("name")), prefix) not in (None, source_attempt)
        for a in artifacts
    )


def legacy_unbound(artifacts: list[dict], stream: str, source_attempt: int) -> bool:
    """True when only legacy (unsuffixed) artifacts exist for this stream
    and the requested attempt is >= 2, so no attempt-bound evidence
    exists for the requested attempt."""
    if source_attempt == 1:
        return False
    prefix = ARTIFACT_PREFIXES[stream]
    return any(
        isinstance(a, dict) and not a.get("expired")
        and str(a.get("name", "")).startswith(prefix)
        and _attempt_suffix(str(a.get("name")), prefix) is None
        for a in artifacts
    )


def _advisory_report_from_zip(zip_bytes: bytes, report_file: str) -> tuple[AdvisoryReport | None, str]:
    """Return (report, error). error is '' on success, 'invalid-zip' or
    'missing-report' or 'duplicate-report' or 'invalid-json' otherwise."""
    try:
        members = validate_archive_members(zip_bytes)
    except ValueError:
        return None, "invalid-zip"
    candidates = [m for m in members if m.split("/")[-1] == report_file]
    if not candidates:
        return None, "missing-report"
    if len(candidates) > 1:
        return None, "duplicate-report"
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        payload = json.loads(zf.read(candidates[0]).decode("utf-8"))
    except (ValueError, KeyError, zipfile.BadZipFile):
        return None, "invalid-json"
    if not isinstance(payload, dict):
        return None, "invalid-json"
    status, head_sha, schema = payload.get("status"), payload.get("head_sha"), payload.get("schema")
    if not isinstance(status, str) or not isinstance(head_sha, str) or not isinstance(schema, str):
        return None, "invalid-json"
    return AdvisoryReport(tool=report_file.split("-")[0], schema=schema, status=status, head_sha=head_sha), ""


def advisory_step_outcome(job: dict | None) -> str | None:
    """Outcome of the advisory generate step, before continue-on-error.

    ``steps.<id>.outcome`` is the step result before ``continue-on-error``
    is applied; ``steps.<id>.conclusion`` and the job conclusion are after.
    A failed generate step is scanner failure even when the job concludes
    success, which is exactly the #3756 pyan3 masking pattern.

    Provider fidelity (2026-11-02): ``outcome`` is an Actions expression
    context value, NOT a field of the REST workflow-jobs API, whose step
    objects carry only name/status/conclusion/number. This function
    therefore returns None for provider-shaped jobs -- callers must NOT
    infer an outcome from ``conclusion``. Scanner-cause provenance for
    REST-shaped jobs comes from the verified health receipt, which
    preserves the workflow's own generate outcome (see
    classify_advisory_artifact)."""
    if not isinstance(job, dict):
        return None
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if "Generate report-only" in str(step.get("name", "")):
            return str(step.get("outcome")) if step.get("outcome") is not None else None
    return None


def classify_advisory_artifact(*, stream: str, artifact: dict | None, zip_bytes: bytes | None, expected_head: str, job: dict | None, source_run_id: int, source_attempt: int, health_classification: str | None = None) -> dict:
    """One complete vertical slice for one advisory stream, from downloaded
    bytes. Ordering: incomplete job, scanner step failure, missing artifact,
    wrong head/attempt, expired, digest, schema, scanner report, then job
    conclusion. Job binding is BY_NAME (see JOB_BINDING); exact provider
    job binding stays NOT_IMPLEMENTED."""
    step_outcome = advisory_step_outcome(job)
    job_status = job.get("status") if isinstance(job, dict) else None
    result = {"stream": stream, "job_binding": JOB_BINDING, "digest_checked": False, "job_status": job_status, "step_outcome": step_outcome}
    if job_status in ("in_progress", "queued", "waiting"):
        # A job that has not finished cannot be a final pass, even when
        # its conclusion field already reads success (#3756 pyan3 pattern).
        return {**result, "classification": "INCOMPLETE"}
    if step_outcome == "failure":
        return {**result, "classification": "SCANNER_ERROR"}
    if artifact is not None:
        # Classifier-level attempt identity: the classifier itself must
        # validate the artifact it is handed, even when the caller did not
        # use select_advisory_artifact. A suffixed mismatch is a hard
        # reject; a legacy name is attempt-bound evidence only for
        # attempt 1 (see select_advisory_artifact).
        artifact_attempt = _attempt_suffix(str(artifact.get("name", "")), ARTIFACT_PREFIXES[stream])
        if artifact_attempt is not None and artifact_attempt != source_attempt:
            return {**result, "classification": "REJECT_WRONG_ATTEMPT"}
        if artifact_attempt is None and source_attempt != 1:
            return {**result, "classification": "EVIDENCE_MISSING",
                    "detail": "legacy artifact is not attempt-bound; source attempt > 1"}
    if artifact is None:
        # The verified health receipt is the only provenance that can
        # preserve the scanner failure when the report itself is absent:
        # the REST jobs API exposes steps[].conclusion, never the
        # Actions steps.<id>.outcome that records a failure hidden by
        # continue-on-error. Losing that cause to plain EVIDENCE_MISSING
        # was a defect, not a fail-closed outcome.
        if health_classification == "REJECT_SCANNER_ERROR":
            return {**result, "classification": "REJECT_SCANNER_ERROR", "missing_report": True,
                    "detail": "scanner error preserved from verified health receipt; report missing"}
        return {**result, "classification": "EVIDENCE_MISSING"}
    wr = artifact.get("workflow_run") or {}
    if wr and (int(wr.get("id", -1)) != source_run_id or wr.get("head_sha") != expected_head):
        return {**result, "classification": "REJECT_WRONG_HEAD"}
    if job is not None and int(job.get("run_attempt", -1)) != source_attempt:
        return {**result, "classification": "REJECT_WRONG_ATTEMPT"}
    if artifact.get("expired"):
        return {**result, "classification": "REJECT_EXPIRED"}
    if zip_bytes is None:
        if health_classification == "REJECT_SCANNER_ERROR":
            return {**result, "classification": "REJECT_SCANNER_ERROR", "missing_report": True,
                    "detail": "scanner error preserved from verified health receipt; report download unavailable"}
        return {**result, "classification": "PROVIDER_UNAVAILABLE"}
    digest = artifact.get("digest")
    if isinstance(digest, str) and digest.startswith("sha256:"):
        result["digest_checked"] = True
        if hashlib.sha256(zip_bytes).hexdigest() != digest[len("sha256:"):]:
            return {**result, "classification": "REJECT_DIGEST"}
    report, error = _advisory_report_from_zip(zip_bytes, ADVISORY_REPORT_FILES[stream])
    if error == "invalid-zip":
        return {**result, "classification": "REJECT_SCHEMA"}
    if error == "missing-report":
        return {**result, "classification": "EVIDENCE_MISSING"}
    if error in ("duplicate-report", "invalid-json"):
        return {**result, "classification": "REJECT_SCHEMA"}
    classification = validate_advisory_report(report, expected_head=expected_head)
    if classification != "EVIDENCE_VALID":
        return {**result, "classification": classification}
    if health_classification is not None and health_classification not in ("EVIDENCE_VALID",):
        return {**result, "classification": "REJECT_SCHEMA", "detail": "health receipt conflicts with report"}
    if job is None:
        return {**result, "classification": "EVIDENCE_MISSING", "detail": "producer job not found on this attempt"}
    if job.get("conclusion") != "success":
        return {**result, "classification": "REJECT_JOB_NOT_SUCCESS"}
    return {**result, "classification": "EVIDENCE_VALID"}



def health_classification_from_zip(zip_bytes: bytes, *, source_run_id: int | None = None,
                                   source_attempt: int | None = None, expected_head: str | None = None) -> str | None:
    """Read a health receipt's classification from a downloaded health
    artifact. Returns None when there is no usable health receipt, so the
    caller can record 'not checked' instead of inventing one.

    When source identity is supplied, the receipt is verified strictly
    against it (correction 2026-11-02, final gate): a receipt whose
    schema, run id, attempt, or head is missing, null, or different
    from the expected value is unverified and returns None -- a missing
    or null field must never satisfy verification, because an
    unattributed receipt cannot prove anything about this source run.
    Identity verification precedes the scanner-error override: a
    receipt that fails identity verification returns None even when
    it records a generate failure. A recorded generate_outcome of
    'failure' on a verified receipt is direct Actions outcome
    provenance and overrides the classification field with
    REJECT_SCANNER_ERROR, because the health writer's own
    classification is derived from the report, not from that outcome.
    When no identity is supplied at all (legacy callers), the original
    behavior is preserved exactly: the classification field is
    returned without verification and without the override."""
    try:
        members = validate_archive_members(zip_bytes)
    except ValueError:
        return None
    candidates = [m for m in members if m.split("/")[-1].endswith("-health.json")]
    if len(candidates) != 1:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        payload = json.loads(zf.read(candidates[0]).decode("utf-8"))
    except (ValueError, KeyError, zipfile.BadZipFile):
        return None
    if not isinstance(payload, dict):
        return None
    identity_requested = source_run_id is not None or source_attempt is not None or expected_head is not None
    if identity_requested:
        if payload.get("schema") != "agent-os-ci-evidence-health/1":
            return None
        if source_run_id is not None and payload.get("run_id") != source_run_id:
            return None
        if source_attempt is not None and payload.get("run_attempt") != source_attempt:
            return None
        if expected_head is not None and payload.get("head_sha") != expected_head:
            return None
        if payload.get("generate_outcome") == "failure":
            return "REJECT_SCANNER_ERROR"
    classification = payload.get("classification")
    return classification if isinstance(classification, str) else None


def classify_junit_artifact(zip_bytes: bytes) -> dict:
    """Validate a downloaded JUnit artifact: ZIP safety, every XML member
    valid, no duplicate node ids across files. Manifests and other members
    are ignored, not parsed."""
    try:
        members = validate_archive_members(zip_bytes)
    except ValueError:
        return {"classification": "REJECT_SCHEMA"}
    xml_members = [m for m in members if m.lower().endswith(".xml")]
    if not xml_members:
        return {"classification": "EVIDENCE_MISSING"}
    seen: set[str] = set()
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for member in xml_members:
            ids, counts = validate_junit(zf.read(member))
            if seen.intersection(ids):
                return {"classification": "REJECT_SCHEMA"}
            seen.update(ids)
            for key in totals:
                totals[key] += counts.get(key, 0)
    except ValueError:
        return {"classification": "REJECT_SCHEMA"}
    return {"classification": "EVIDENCE_VALID", "node_count": len(seen), "counts": totals}


def build_verified_receipt(*, source_run: dict, jobs: list[dict], artifacts: list[dict], downloads: dict[str, bytes], source_attempt: int, collector_head: str, live_trigger: bool) -> dict:
    """Pure verified receipt from already-fetched provider data. downloads
    maps artifact id (as str) to its downloaded zip bytes. Never executes
    artifact content; only advisory JSON and JUnit XML are parsed."""
    verify_source_run(source_run, expected_run_id=int(source_run["id"]), expected_head=str(source_run["head_sha"]))
    source_head = str(source_run["head_sha"])
    source_run_id = int(source_run["id"])
    streams: dict[str, dict] = {}
    for stream in ("pyan", "jscpd"):
        job = job_by_name(jobs, ADVISORY_JOB_NAMES[stream], expected_attempt=source_attempt)
        if job is None or job.get("conclusion") == "skipped":
            # NOT_APPLICABLE is not a pass, but downstream consumers must
            # distinguish an unexpectedly missing producer job from a
            # legitimately non-applicable stream.
            detail = "producer job absent on this attempt" if job is None else "producer job skipped on this attempt"
            streams[stream] = {"classification": "NOT_APPLICABLE", "job_binding": JOB_BINDING, "detail": detail}
            continue
        artifact = select_advisory_artifact(artifacts, stream, source_attempt=source_attempt)
        zip_bytes = downloads.get(str(artifact["id"])) if artifact else None
        health_candidates = [c for c in artifacts if isinstance(c, dict) and str(c.get("name", "")).startswith(HEALTH_PREFIXES[stream])]
        health_exact = [c for c in health_candidates if _attempt_suffix(str(c.get("name")), HEALTH_PREFIXES[stream]) == source_attempt]
        # Health artifacts follow the same attempt policy as advisory
        # artifacts: legacy names are attempt-bound evidence only for
        # attempt 1, never silently for a later attempt.
        health_legacy = [c for c in health_candidates if _attempt_suffix(str(c.get("name")), HEALTH_PREFIXES[stream]) is None] if source_attempt == 1 else []
        health_artifact = health_exact[0] if health_exact else (health_legacy[0] if health_legacy else None)
        health_classification = None
        if health_artifact is not None and str(health_artifact["id"]) in downloads:
            health_wr = health_artifact.get("workflow_run") or {}
            if not health_wr or (int(health_wr.get("id", -1)) == source_run_id and health_wr.get("head_sha") == source_head):
                health_classification = health_classification_from_zip(
                    downloads[str(health_artifact["id"])], source_run_id=source_run_id,
                    source_attempt=source_attempt, expected_head=source_head)
        stream_result = classify_advisory_artifact(
            stream=stream, artifact=artifact, zip_bytes=zip_bytes, expected_head=source_head,
            job=job, source_run_id=source_run_id, source_attempt=source_attempt,
            health_classification=health_classification,
        )
        if artifact is None and stream_result["classification"] == "EVIDENCE_MISSING":
            # Selection returned None for a missing report; refine the
            # reason. INCOMPLETE and other non-missing classifications
            # keep precedence -- a still-running job is not a rejection.
            if explicit_attempt_mismatch(artifacts, stream, source_attempt):
                stream_result = {**stream_result, "classification": "REJECT_WRONG_ATTEMPT",
                                 "detail": "only explicitly mismatched-attempt artifacts exist for this stream"}
            elif legacy_unbound(artifacts, stream, source_attempt):
                stream_result = {**stream_result, "detail": "legacy artifact is not attempt-bound; source attempt > 1"}
        streams[stream] = stream_result
    validate_job = job_by_name(jobs, "Run validation plan", expected_attempt=source_attempt)
    obligation = aggregate_obligation(validate_job)
    if obligation == "deferred":
        streams["aggregate"] = {"classification": "INTENTIONALLY_DEFERRED", "job_binding": JOB_BINDING}
    elif obligation == "reused":
        streams["aggregate"] = {"classification": "REUSED_SOURCE_REQUIRED", "job_binding": JOB_BINDING}
    elif obligation == "not_applicable":
        streams["aggregate"] = {"classification": "NOT_APPLICABLE", "job_binding": JOB_BINDING}
    else:
        junit_results: dict[str, dict] = {}
        for art in artifacts:
            name = str(art.get("name", ""))
            if name in (f"junit-aggregate-{source_attempt}", f"junit-plan-focused-{source_attempt}"):
                data = downloads.get(str(art["id"]))
                junit_results[name] = classify_junit_artifact(data) if data is not None else {"classification": "PROVIDER_UNAVAILABLE"}
        if not junit_results:
            streams["aggregate"] = {"classification": "EVIDENCE_MISSING", "job_binding": JOB_BINDING}
        elif all(r["classification"] == "EVIDENCE_VALID" for r in junit_results.values()):
            if validate_job is not None and validate_job.get("conclusion") != "success":
                streams["aggregate"] = {"classification": "REJECT_JOB_NOT_SUCCESS", "job_binding": JOB_BINDING}
            else:
                streams["aggregate"] = {"classification": "EVIDENCE_VALID", "job_binding": JOB_BINDING}
        else:
            streams["aggregate"] = {"classification": "REJECT_SCHEMA", "job_binding": JOB_BINDING}
        streams["junit"] = junit_results
    return {
        "schema": SCHEMA,
        "source_run_id": source_run_id,
        "source_run_attempt": source_attempt,
        "source_head": source_head,
        "collector_head": collector_head,
        "streams": streams,
        "live_trigger": live_trigger,
        "sheets_written": False,
        "per_job_join": "NOT_IMPLEMENTED_EXACT",
        "job_binding": JOB_BINDING,
        "note": "Read-only receipt. EVIDENCE_VALID here is content-valid with a same-named successful job on the same attempt; it is NOT a provider-verified job->artifact join.",
    }

def _api_get(url: str, token: str) -> tuple[object, dict[str, str]]:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "agent-os-ci-evidence-collector"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8")), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"provider request failed: {url} -> HTTP {exc.code}") from exc


def _api_get_bytes(url: str, token: str) -> bytes:
    """Download an artifact archive with a hard size cap. Returns bytes
    only; never parses or executes them here."""
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "agent-os-ci-evidence-collector"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"provider download failed: HTTP {exc.code}") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("artifact archive exceeds size cap")
    return data


def _paginate(url: str, token: str) -> list[dict]:
    items: list[dict] = []
    next_url: str | None = url
    while next_url:
        payload, headers = _api_get(next_url, token)
        if isinstance(payload, dict):
            items.extend(payload.get("artifacts") or payload.get("jobs") or [])
        link = headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--source-attempt", type=int, default=1)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repository:
        print("collector requires GITHUB_TOKEN and GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    base = f"https://api.github.com/repos/{repository}/actions/runs/{args.source_run_id}"
    run_payload, _ = _api_get(base, token)
    if not isinstance(run_payload, dict):
        print("provider run payload is not an object", file=sys.stderr)
        return 2
    try:
        verify_source_run(run_payload, expected_run_id=args.source_run_id, expected_head=args.source_head)
    except ValueError as exc:
        print(f"source run verification failed: {exc}", file=sys.stderr)
        return 2
    # Exact-attempt endpoint (documented GitHub REST route). The older
    # '?attempt_number=' query on the ordinary jobs endpoint is not the
    # documented attempt selector and must not be relied on.
    jobs = _paginate(f"{base}/attempts/{args.source_attempt}/jobs?per_page=100", token)
    if not jobs:
        print(f"provider returned no jobs for attempt {args.source_attempt}", file=sys.stderr)
        return 2
    for job in jobs:
        try:
            job_run_id = int(job.get("run_id")) if isinstance(job, dict) else None
            job_attempt = int(job.get("run_attempt")) if isinstance(job, dict) else None
        except (TypeError, ValueError):
            job_run_id = job_attempt = None
        if job_run_id != args.source_run_id or job_attempt != args.source_attempt:
            print("provider job identity does not match source run/attempt", file=sys.stderr)
            return 2
    artifacts = _paginate(f"{base}/artifacts?per_page=100", token)
    downloads: dict[str, bytes] = {}
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        name = str(art.get("name", ""))
        if name.startswith(tuple(ARTIFACT_PREFIXES.values()) + tuple(HEALTH_PREFIXES.values()) + ("junit-",)):
            try:
                data = _api_get_bytes(str(art.get("archive_download_url")), token)
            except RuntimeError as exc:
                print(f"artifact download failed for {name}: {exc}", file=sys.stderr)
                return 1
            downloads[str(art["id"])] = data
    receipt = build_verified_receipt(
        source_run=run_payload, jobs=jobs, artifacts=artifacts, downloads=downloads,
        source_attempt=args.source_attempt, collector_head=os.environ.get("GITHUB_SHA", ""),
        live_trigger=os.environ.get("COLLECTOR_LIVE_TRIGGER", "") == "true",
    )
    receipt["artifact_names_observed"] = sorted({str(a.get("name")) for a in artifacts if isinstance(a, dict)})
    receipt["advisory_artifact_present"] = {
        stream: select_advisory_artifact(artifacts, stream, source_attempt=args.source_attempt) is not None
        for stream in ("pyan", "jscpd")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
