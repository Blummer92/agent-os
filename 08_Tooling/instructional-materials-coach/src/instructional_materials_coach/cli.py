"""CLI: build a slide deck and worksheet for one lesson from an approved template pair."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .artifact_structure import PASS, validate_required_worksheet_sections
from .artifact_content_qa import DEFAULT_QA_EVIDENCE_DIR, TerminalQAExpectations
from .asset_slot_resolution import resolve_asset_slots
from .build_resume import DEFAULT_BUILD_RESUME_DIR
from .build_receipt import build_receipt_record, write_build_receipt_atomic
from .connected_visual_placement import plan_visual_placement_bindings
from .content_spec import load_lesson_content
from .docs_requests import build_docs_replace_requests
from .drive_client import build_drive_service, get_credentials, get_file_metadata
from .generation_context import compose_generation_context, curriculum_decision_token
from .lesson_record import LEARNING_TYPES, SEVERITIES, LessonRecord, lesson_from_exception, record_lesson
from instructional_workflow_contracts.current_curriculum_state import resolve_current_curriculum_state
from instructional_workflow_contracts.material_requirement import validate_material_requirement
from instructional_workflow_contracts.teacher_visual_decision import (
    canonical_candidate_set_fingerprint,
)
from .live_build import LiveBuildInput, build_live_materials
from .placement_transport import PlacementRuntimeUnavailable, build_placement_transport
from .slides_requests import build_slides_replace_requests
from .teacher_decisions import DEFAULT_TEACHER_DECISIONS_DIR, load_teacher_decisions
from .template_resolution import TemplateCandidate, resolve_approved_template_pair
from .visual_reuse import GovernedVisualReusePlan, plan_governed_visual_reuse
from .workspace_clients import build_docs_service, build_slides_service

DEFAULT_LESSONS_DIR = "reports/lessons"
DEFAULT_PLACEMENT_RECEIPTS_DIR = "reports/placement-receipts"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build instructional materials from an approved template, or log a lesson learned.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build a slide deck and worksheet from an approved template and lesson content.")
    build.add_argument("--content", required=True)
    build.add_argument("--receipt-out", default="", help="Optional local JSON build evidence (not authorization).")
    build.add_argument("--slides-template", default="")
    build.add_argument("--doc-template", default="")
    build.add_argument("--template-candidates", default="")
    build.add_argument("--target-folder", required=True)
    build.add_argument("--material-requirement", default="")
    build.add_argument("--current-curriculum-evidence", default="")
    build.add_argument("--artifact-manifests", default="")
    build.add_argument("--visual-candidates", default="")
    build.add_argument("--visual-source-revision", default="")
    build.add_argument("--changed-dependency-keys", default="")
    build.add_argument("--impact-map", default="")
    build.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", ""))
    build.add_argument("--token-path", default=os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", ""))
    build.add_argument("--lessons-dir", default=DEFAULT_LESSONS_DIR)
    build.add_argument("--teacher-decisions-dir", default=DEFAULT_TEACHER_DECISIONS_DIR,
                       help="Directory of teacher visual-decision records honored by the governed reuse path.")
    build.add_argument("--resume-dir", default=DEFAULT_BUILD_RESUME_DIR,
                       help="Directory of build resume records enabling retry continuation.")
    build.add_argument("--placement-script-id", default=os.environ.get("IMC_PLACEMENT_SCRIPT_ID", ""),
                       help="Apps Script deployment id for the governed visual-placement transport (#3257). "
                            "Empty (the default) means no placement runtime is available: a build with a "
                            "non-empty visual selection then fails closed with placement-runtime-unavailable. "
                            "Deployment and execution are separately governed.")
    build.add_argument("--placement-receipts-dir", default=DEFAULT_PLACEMENT_RECEIPTS_DIR,
                       help="Directory of durable verified placement receipts (#3257/#3258 handoff).")
    build.add_argument("--qa-evidence-dir", default=DEFAULT_QA_EVIDENCE_DIR,
                       help="Directory of durable terminal-QA evidence (#3258). Verified QA "
                            "reports are recovered on retry while artifact revision and "
                            "expectations still match, and re-verified otherwise.")

    log_lesson = subparsers.add_parser("log-lesson")
    log_lesson.add_argument("--title", required=True)
    log_lesson.add_argument("--what-happened", required=True)
    log_lesson.add_argument("--what-to-do-next-time", default="")
    log_lesson.add_argument("--guardrail", default="")
    log_lesson.add_argument("--severity", default="Low", choices=SEVERITIES)
    log_lesson.add_argument("--learning-type", default="QA feedback", choices=LEARNING_TYPES)
    log_lesson.add_argument("--source-link", default="")
    log_lesson.add_argument("--lessons-dir", default=DEFAULT_LESSONS_DIR)
    return parser.parse_args(argv)


def _load_json(path: str, *, default: object) -> object:
    if not path:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def build_idempotency_key_v2(
    *,
    requirement_id: object,
    contract_version: object,
    record_revision: object,
    source_fingerprint: object,
    content_fingerprint: object,
    slides_template_id: object,
    slides_template_revision: object,
    doc_template_id: object,
    doc_template_revision: object,
    selected_visuals: object,
    candidate_set_fingerprint: object,
    visual_source_revision: object,
    target_folder: object,
    content_title: object,
) -> str:
    """Build the #3252 idempotency key over every consequential input.

    Covers: requirement identity, lesson content bytes, template IDs *and*
    revisions, selected visuals (asset + Lane-D content identity per role),
    candidate-set fingerprint, visual source revision, and run targeting.
    Any consequential change yields a new key (fresh copies, never
    contamination); byte-identical inputs reproduce the key (safe recovery).
    Run timestamps, actor identity, retry count, and lesson-record sidecars
    are not consequential and do not participate.
    """
    payload = {
        "requirement_id": requirement_id,
        "contract_version": contract_version,
        "record_revision": record_revision,
        "source_fingerprint": source_fingerprint,
        "content_fingerprint": content_fingerprint,
        "slides_template": {"id": slides_template_id, "revision": slides_template_revision},
        "doc_template": {"id": doc_template_id, "revision": doc_template_revision},
        "selected_visuals": selected_visuals,
        "candidate_set_fingerprint": candidate_set_fingerprint,
        "visual_source_revision": visual_source_revision,
        "target_folder": target_folder,
        "content_title": content_title,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _build_idempotency_key(args: argparse.Namespace, content_title: str, material_requirement: object) -> str:
    """Legacy entry point kept for backward compatibility.

    Delegates to the v2 key with empty consequential inputs not available
    to historical callers. New code must call :func:`build_idempotency_key_v2`.
    """
    identity = material_requirement.get("identity", {}) if isinstance(material_requirement, dict) else {}
    return build_idempotency_key_v2(
        requirement_id=identity.get("requirement_id"),
        contract_version=identity.get("contract_version"),
        record_revision=identity.get("record_revision"),
        source_fingerprint=identity.get("source_fingerprint"),
        content_fingerprint="",
        slides_template_id=args.slides_template,
        slides_template_revision="",
        doc_template_id=args.doc_template,
        doc_template_revision="",
        selected_visuals=[],
        candidate_set_fingerprint="",
        visual_source_revision="",
        target_folder=args.target_folder,
        content_title=content_title,
    )


def _lesson_content_fingerprint(content: object) -> str:
    """SHA-256 over the canonical lesson content (authored + governed context)."""
    try:
        payload = dataclasses.asdict(content)  # type: ignore[arg-type]
    except Exception:
        payload = {"repr": repr(content)}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _template_revision(drive_service: Any, template_id: str) -> str:
    """Best-effort Drive revision for a template; empty when unreadable."""
    try:
        meta = get_file_metadata(drive_service, template_id)
    except Exception:
        return ""
    revision = meta.get("headRevisionId") if isinstance(meta, dict) else None
    return revision if isinstance(revision, str) else ""


def _selected_visuals_for_key(visual_plan: GovernedVisualReusePlan) -> list[dict[str, Any]]:
    """Per-role selected visuals with Lane-D content identity for the key."""
    from instructional_workflow_contracts.asset_content_identity import (
        content_identity_from_fingerprint,
    )

    result = visual_plan.cohesive_visual_plan_result
    payload = result.record.to_dict() if result is not None and result.record is not None else {}
    visuals: list[dict[str, Any]] = []
    for key in ("required_role_assignments", "optional_role_assignments"):
        assignments = payload.get(key, ())
        if not isinstance(assignments, (list, tuple)):
            continue
        for assignment in assignments:
            if not isinstance(assignment, Mapping):
                continue
            candidate = assignment.get("selected_candidate")
            if not isinstance(candidate, Mapping):
                continue
            asset_reference = candidate.get("asset_reference")
            asset_id = (
                asset_reference.get("asset_id")
                if isinstance(asset_reference, Mapping)
                else None
            )
            fingerprint = (
                asset_reference.get("content_fingerprint")
                if isinstance(asset_reference, Mapping)
                else None
            )
            try:
                identity = (
                    content_identity_from_fingerprint(fingerprint)
                    if isinstance(fingerprint, str) and fingerprint
                    else None
                )
            except (ValueError, TypeError):
                identity = None
            visuals.append(
                {
                    "role": assignment.get("role_id"),
                    "asset_id": asset_id,
                    "content_identity": identity,
                }
            )
    visuals.sort(key=lambda item: _canonical_json(item))
    return visuals


def _require_visual_placement_support(
    selected_asset_ids: tuple[str, ...],
    placement_script_id: str | None = None,
) -> None:
    """#3257 admission gate: a non-empty selection needs a placement runtime.

    Replaces the old dead-end refusal. When governed reusable visuals were
    selected but no verified image-placement runtime is configured, fail
    before connected writes with the explicit ``placement-runtime-unavailable``
    blocked state -- never "final", never a visual gap, never generation
    permission (#1753 fail-closed behavior). When a runtime is configured,
    the selection proceeds into the connected placement path.
    """
    if not selected_asset_ids:
        return
    if placement_script_id and str(placement_script_id).strip():
        return
    identities = ",".join(selected_asset_ids)
    raise PlacementRuntimeUnavailable(
        "placement-runtime-unavailable: Governed reusable visuals were selected but no "
        "verified image-placement runtime is available to this build; refusing a "
        "false-success build before external write. "
        f"selected_asset_ids={identities}. "
        "Configure --placement-script-id with the separately governed Apps Script "
        "placement deployment to enable connected visual placement."
    )


def _selected_asset_drive_files(visual_plan: GovernedVisualReusePlan) -> dict[str, str | None]:
    """Map each selected asset ID to the candidate Drive file ID bound by the governed plan."""
    bound: dict[str, str | None] = {}
    result = visual_plan.cohesive_visual_plan_result
    payload = result.record.to_dict() if result is not None and result.record is not None else {}
    selected_candidates = payload.get("selected_candidates", ())
    if not isinstance(selected_candidates, (list, tuple)):
        selected_candidates = ()
    for item in selected_candidates:
        if not isinstance(item, Mapping):
            continue
        asset_reference = item.get("asset_reference")
        library_reference = item.get("library_reference")
        asset_id = asset_reference.get("asset_id") if isinstance(asset_reference, Mapping) else None
        if not isinstance(asset_id, str) or not asset_id:
            continue
        drive_file_id = library_reference.get("drive_file_id") if isinstance(library_reference, Mapping) else None
        bound[asset_id] = drive_file_id if isinstance(drive_file_id, str) and drive_file_id else None
    return {asset_id: bound.get(asset_id) for asset_id in visual_plan.selected_asset_ids}


def _selected_asset_content_identities(visual_plan: GovernedVisualReusePlan) -> dict[str, dict[str, Any] | None]:
    """Map each selected asset ID to its canonical content identity (#3256).

    The governed plan's selected candidates carry the approved bytes as a
    SHA-256 ``content_fingerprint`` on ``asset_reference``; lift it into the
    canonical content-identity shape so slot resolution verifies the live
    Drive bytes against what was reviewed.
    """
    from instructional_workflow_contracts.asset_content_identity import content_identity_from_fingerprint

    bound: dict[str, dict[str, Any] | None] = {}
    result = visual_plan.cohesive_visual_plan_result
    payload = result.record.to_dict() if result is not None and result.record is not None else {}
    selected_candidates = payload.get("selected_candidates", ())
    if not isinstance(selected_candidates, (list, tuple)):
        selected_candidates = ()
    for item in selected_candidates:
        if not isinstance(item, Mapping):
            continue
        asset_reference = item.get("asset_reference")
        asset_id = asset_reference.get("asset_id") if isinstance(asset_reference, Mapping) else None
        if not isinstance(asset_id, str) or not asset_id:
            continue
        fingerprint = asset_reference.get("content_fingerprint") if isinstance(asset_reference, Mapping) else None
        try:
            bound[asset_id] = content_identity_from_fingerprint(fingerprint) if fingerprint else None
        except (ValueError, TypeError):
            bound[asset_id] = None
    return {asset_id: bound.get(asset_id) for asset_id in visual_plan.selected_asset_ids}


def _require_asset_slot_resolution(visual_plan: GovernedVisualReusePlan, drive_service: object) -> None:
    """Fail before connected writes when a selected asset slot has no live Drive file (#3130).

    Also fails closed per asset when the live Drive bytes do not match the
    approved content identity (#3256): a ``content-identity-mismatch`` is never
    absence and never authorizes a generation handoff.
    """
    resolution = resolve_asset_slots(
        asset_slots=_selected_asset_drive_files(visual_plan),
        describe_drive_file=lambda file_id: get_file_metadata(drive_service, file_id),
        expected_content_identities=_selected_asset_content_identities(visual_plan),
    )
    if resolution.status != "resolved":
        mismatches = ", ".join(resolution.content_identity_mismatches)
        detail = f" content_identity_mismatches={mismatches}." if mismatches else ""
        outcomes = ", ".join(f"{slot}={outcome}" for slot, outcome in sorted(resolution.slot_outcomes.items()) if outcome != "resolved")
        raise RuntimeError(
            "Selected asset slots do not resolve to live Drive files; refusing a build "
            "that would ship labeled image placeholders instead of real images. "
            f"unresolvable_asset_slots={','.join(resolution.unresolvable_slots)}.{detail}"
            f" slot_outcomes={outcomes}."
        )


def _terminal_qa_summary(receipt: object) -> str:
    """Summarize terminal QA evidence for a non-final build report (#3258).

    Names the QA state per artifact plus the first failing finding, so an
    operator can see WHY "final" was refused without digging through JSON.
    ``persisted`` (metadata-verified, QA not passed) is distinguished from
    ``final`` explicitly.
    """
    parts: list[str] = []
    for role in ("slides", "worksheet"):
        artifact = getattr(receipt, role, None)
        if artifact is None:
            continue
        state = getattr(artifact, "terminal_qa_state", "not-run")
        persisted = getattr(artifact, "is_persisted", False)
        label = "persisted-not-final" if persisted else state
        detail = ""
        qa_report = getattr(receipt, "terminal_qa", None)
        if qa_report is not None:
            artifact_report = getattr(qa_report, role, None)
            findings = getattr(artifact_report, "findings", ()) or ()
            failing = [f for f in findings if getattr(f, "severity", "") == "fail"]
            if failing:
                first = failing[0]
                detail = f": {getattr(first, 'code', '')} {getattr(first, 'message', '')}"
        parts.append(f"{role}={label}{detail}")
    return "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "log-lesson":
        path = record_lesson(LessonRecord(lesson_learned=args.title, what_happened=args.what_happened, what_to_do_next_time=args.what_to_do_next_time, guardrail=args.guardrail, severity=args.severity, learning_type=args.learning_type, source_link=args.source_link), args.lessons_dir)
        print(f"Lesson recorded: {path}")
        return 0
    if os.environ.get("ALLOW_WRITE", "false").lower() != "true":
        print("Refusing to run: set ALLOW_WRITE=true to confirm this should write to Drive.", file=sys.stderr)
        return 1

    context = {"slides_template": args.slides_template, "doc_template": args.doc_template, "target_folder": args.target_folder, "content_path": args.content, "material_requirement_path": args.material_requirement, "current_curriculum_evidence_path": args.current_curriculum_evidence}
    build_input = None
    receipt = None
    requirement_identity = {}
    template_revisions = {}
    try:
        content = load_lesson_content(args.content)
        context["content_title"] = content.title
        if args.template_candidates:
            raw_candidates = _load_json(args.template_candidates, default=[])
            if not isinstance(raw_candidates, list):
                raise RuntimeError("template candidates must be a JSON list")
            candidates = tuple(TemplateCandidate(
                template_id=item["template_id"], kind=item["kind"],
                approval_state=item["approval_state"], access_state=item["access_state"],
                supported_placeholders=tuple(item.get("supported_placeholders", ())),
            ) for item in raw_candidates)
            pair = resolve_approved_template_pair(
                candidates, required_placeholders=tuple(sorted(content.placeholder_tokens()))
            )
            args.slides_template = pair.slides_template_id
            args.doc_template = pair.docs_template_id
        if not args.slides_template or not args.doc_template:
            raise RuntimeError("Provide both exact approved template IDs or --template-candidates governed evidence.")
        context["slides_template"] = args.slides_template
        context["doc_template"] = args.doc_template
        if not args.material_requirement:
            raise RuntimeError("Governed MaterialRequirement JSON is required before a connected build.")
        if not args.current_curriculum_evidence:
            raise RuntimeError("Governed current-curriculum evidence is required before a connected build.")
        material_requirement = _load_json(args.material_requirement, default=None)
        current_curriculum_evidence = _load_json(args.current_curriculum_evidence, default=None)
        current_asset_evidence = (
            current_curriculum_evidence.get("asset_evidence", [])
            if isinstance(current_curriculum_evidence, dict)
            else []
        )
        visual_candidates = _load_json(args.visual_candidates, default=[])
        # #3252: load governed teacher visual-decision records for this
        # requirement; the reuse path honors valid ones per role and blocks
        # invalid ones with an explicit reason code.
        requirement_identity = (
            material_requirement.get("identity", {})
            if isinstance(material_requirement, dict)
            else {}
        )
        teacher_decisions = load_teacher_decisions(
            args.teacher_decisions_dir,
            requirement_id=(
                requirement_identity.get("requirement_id")
                if isinstance(requirement_identity, dict)
                else None
            ),
        )
        visual_plan = plan_governed_visual_reuse(
            material_requirement,
            artifact_manifests=_load_json(args.artifact_manifests, default=[]),
            visual_candidates=visual_candidates,
            source_revision=args.visual_source_revision,
            changed_dependency_keys=_load_json(args.changed_dependency_keys, default=[]),
            impact_map=_load_json(args.impact_map, default={}),
            current_asset_evidence=current_asset_evidence,
            teacher_decisions=tuple(teacher_decisions),
        )
        context["visual_reuse_outcome"] = visual_plan.outcome
        context["selected_asset_ids"] = list(visual_plan.selected_asset_ids)
        if visual_plan.final_production_blocked:
            raise RuntimeError(f"Governed visual reuse gate blocked final production: {visual_plan.outcome}; image_gap_briefs={len(visual_plan.image_gap_briefs)}")
        _require_visual_placement_support(visual_plan.selected_asset_ids, args.placement_script_id)

        content = compose_generation_context(
            content,
            material_requirement=material_requirement,
            current_curriculum_evidence=current_curriculum_evidence,
            selected_asset_ids=tuple(visual_plan.selected_asset_ids),
            governed_visual_plan=visual_plan.cohesive_visual_plan_result,
        )
        context["generation_context_tokens"] = sorted(content.context_tokens)

        requirement_result = validate_material_requirement(material_requirement)
        requirement = requirement_result.record.to_dict() if requirement_result.record is not None else {}
        state_result = resolve_current_curriculum_state(current_curriculum_evidence)
        state = state_result.record.to_dict() if state_result.record is not None else {}
        decision_tokens = {
            item["decision_key"]: curriculum_decision_token(item["decision_key"])
            for item in state.get("owner_states", [])
            if isinstance(item.get("decision_key"), str)
        }
        # #1568 standard worksheet sections are guaranteed by the shared generation
        # context even when current curriculum evidence does not explicitly author
        # them. Existing governed values still win and are never duplicated.
        decision_tokens.setdefault("warm-up", "curriculum_warm_up")
        decision_tokens.setdefault("exit-ticket", "curriculum_exit_ticket")
        docs_requests = tuple(build_docs_replace_requests(content))
        worksheet_qa = validate_required_worksheet_sections(
            required_sections=requirement.get("instructional", {}).get("required_sections", ()),
            curriculum_decision_tokens=decision_tokens,
            docs_requests=docs_requests,
        )
        context["worksheet_generation_plan_qa"] = worksheet_qa.status
        if worksheet_qa.status != PASS:
            details = "; ".join(finding.message for finding in worksheet_qa.findings)
            raise RuntimeError(
                "Worksheet generation-plan completeness requires resolution before external write: "
                f"{worksheet_qa.status}; {details}"
            )

        credentials = get_credentials(args.client_secret, args.token_path)
        drive_service = build_drive_service(credentials)
        _require_asset_slot_resolution(visual_plan, drive_service)
        # #3257: plan connected visual placements from the governed selection.
        # Slot resolution above already proved every selected asset resolves to
        # a live Drive file whose bytes match the approved content identity;
        # the bindings below carry that exact identity into placement.
        visual_placements = (
            plan_visual_placement_bindings(visual_plan)
            if visual_plan.selected_asset_ids
            else ()
        )
        if visual_plan.selected_asset_ids and not visual_placements:
            raise RuntimeError(
                "Governed visual selections exist but no placement bindings could be "
                "planned from the governed plan; refusing a build that would silently "
                f"drop selected visuals. selected_asset_ids={','.join(visual_plan.selected_asset_ids)}"
            )
        placement_transport = (
            build_placement_transport(script_id=args.placement_script_id, credentials=credentials)
            if visual_placements
            else None
        )
        # #3252: the idempotency key covers every consequential input. The
        # same payload doubles as the input fingerprint bound to created
        # copies (anti-collision on recovery).
        idempotency_key = build_idempotency_key_v2(
            requirement_id=requirement_identity.get("requirement_id"),
            contract_version=requirement_identity.get("contract_version"),
            record_revision=requirement_identity.get("record_revision"),
            source_fingerprint=requirement_identity.get("source_fingerprint"),
            content_fingerprint=_lesson_content_fingerprint(content),
            slides_template_id=args.slides_template,
            slides_template_revision=_template_revision(drive_service, args.slides_template),
            doc_template_id=args.doc_template,
            doc_template_revision=_template_revision(drive_service, args.doc_template),
            selected_visuals=_selected_visuals_for_key(visual_plan),
            candidate_set_fingerprint=canonical_candidate_set_fingerprint(visual_candidates),
            visual_source_revision=args.visual_source_revision or "",
            target_folder=args.target_folder,
            content_title=content.title,
        )
        # #3258: derive terminal-QA expectations from the governed planned
        # inputs (planned replaceAllText requests + visual bindings) before
        # the build. Terminal QA evaluates the PERSISTED artifacts against
        # these expectations; metadata-only success is "persisted", never
        # "final".
        slides_requests = tuple(build_slides_replace_requests(content))
        qa_expectations = TerminalQAExpectations.build_from_requests(
            idempotency_key=idempotency_key,
            docs_requests=docs_requests,
            slides_requests=slides_requests,
            visual_placements=tuple(visual_placements),
        )
        build_input = LiveBuildInput(
                slides_template_id=args.slides_template, doc_template_id=args.doc_template,
                target_folder_id=args.target_folder, slides_name=f"{content.title} - Slides",
                doc_name=f"{content.title} - Worksheet",
                idempotency_key=idempotency_key,
                input_fingerprint=idempotency_key,
                slides_requests=slides_requests,
                docs_requests=docs_requests,
                visual_placements=tuple(visual_placements),
                qa_expectations=qa_expectations,
            )
        template_revisions = {"slides": _template_revision(drive_service, args.slides_template), "worksheet": _template_revision(drive_service, args.doc_template)}
        receipt = build_live_materials(
            build_input,
            drive_service=drive_service,
            slides_service=build_slides_service(credentials),
            docs_service=build_docs_service(credentials),
            resume_dir=args.resume_dir,
            placement_transport=placement_transport,
            placement_receipts_dir=args.placement_receipts_dir,
            qa_evidence_dir=args.qa_evidence_dir,
        )
        if args.receipt_out:
            write_build_receipt_atomic(args.receipt_out, build_receipt_record(build_input, receipt, requirement_identity=requirement_identity, template_revisions=template_revisions))
        if not receipt.succeeded:
            qa_summary = _terminal_qa_summary(receipt)
            raise RuntimeError(
                f"Live build incomplete: slides={receipt.slides.state} "
                f"(terminal_qa={receipt.slides.terminal_qa_state}); "
                f"worksheet={receipt.worksheet.state} "
                f"(terminal_qa={receipt.worksheet.terminal_qa_state}); "
                f"manual_reconciliation_required={receipt.manual_reconciliation_required}"
                + (f"; {qa_summary}" if qa_summary else "")
            )
        print(f"Slides final (native Google Slides, canonical editable): {receipt.slides.web_view_link}")
        print(f"Worksheet final (native Google Docs, canonical editable): {receipt.worksheet.web_view_link}")
        return 0
    except Exception as exc:
        if args.receipt_out:
            try:
                write_build_receipt_atomic(args.receipt_out, build_receipt_record(build_input, receipt, requirement_identity=requirement_identity, template_revisions=template_revisions, error_code=type(exc).__name__))
            except OSError as receipt_error:
                print(f"Receipt persistence failed: {receipt_error}", file=sys.stderr)
        lesson_path = record_lesson(lesson_from_exception(exc, context), args.lessons_dir)
        print(f"Build failed: {exc}", file=sys.stderr)
        print(f"Lesson recorded: {lesson_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
