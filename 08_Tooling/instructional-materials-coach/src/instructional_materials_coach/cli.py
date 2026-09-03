"""CLI: build a slide deck and worksheet for one lesson from an approved template pair."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from .content_spec import load_lesson_content
from .docs_requests import build_docs_replace_requests
from .drive_client import build_drive_service, get_credentials
from .generation_context import compose_generation_context
from .lesson_record import LEARNING_TYPES, SEVERITIES, LessonRecord, lesson_from_exception, record_lesson
from .live_build import LiveBuildInput, build_live_materials
from .slides_requests import build_slides_replace_requests
from .visual_reuse import plan_governed_visual_reuse
from .workspace_clients import build_docs_service, build_slides_service

DEFAULT_LESSONS_DIR = "reports/lessons"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build instructional materials from an approved template, or log a lesson learned.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build a slide deck and worksheet from an approved template and lesson content.")
    build.add_argument("--content", required=True)
    build.add_argument("--slides-template", required=True)
    build.add_argument("--doc-template", required=True)
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


def _build_idempotency_key(
    args: argparse.Namespace,
    content_title: str,
    material_requirement: object,
) -> str:
    identity = material_requirement.get("identity", {}) if isinstance(material_requirement, dict) else {}
    payload = {
        "requirement_id": identity.get("requirement_id"),
        "contract_version": identity.get("contract_version"),
        "record_revision": identity.get("record_revision"),
        "source_fingerprint": identity.get("source_fingerprint"),
        "slides_template": args.slides_template,
        "doc_template": args.doc_template,
        "target_folder": args.target_folder,
        "content_title": content_title,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


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
    try:
        content = load_lesson_content(args.content)
        context["content_title"] = content.title
        if not args.material_requirement:
            raise RuntimeError("Governed MaterialRequirement JSON is required before a connected build.")
        if not args.current_curriculum_evidence:
            raise RuntimeError("Governed current-curriculum evidence is required before a connected build.")
        material_requirement = _load_json(args.material_requirement, default=None)
        visual_plan = plan_governed_visual_reuse(
            material_requirement,
            artifact_manifests=_load_json(args.artifact_manifests, default=[]),
            visual_candidates=_load_json(args.visual_candidates, default=[]),
            source_revision=args.visual_source_revision,
            changed_dependency_keys=_load_json(args.changed_dependency_keys, default=[]),
            impact_map=_load_json(args.impact_map, default={}),
        )
        context["visual_reuse_outcome"] = visual_plan.outcome
        context["selected_asset_ids"] = list(visual_plan.selected_asset_ids)
        if visual_plan.final_production_blocked:
            raise RuntimeError(f"Governed visual reuse gate blocked final production: {visual_plan.outcome}; image_gap_briefs={len(visual_plan.image_gap_briefs)}")

        content = compose_generation_context(
            content,
            material_requirement=material_requirement,
            current_curriculum_evidence=_load_json(args.current_curriculum_evidence, default=None),
            selected_asset_ids=tuple(visual_plan.selected_asset_ids),
            governed_visual_plan=visual_plan.cohesive_visual_plan_result,
        )
        context["generation_context_tokens"] = sorted(content.context_tokens)

        credentials = get_credentials(args.client_secret, args.token_path)
        receipt = build_live_materials(
            LiveBuildInput(
                slides_template_id=args.slides_template,
                doc_template_id=args.doc_template,
                target_folder_id=args.target_folder,
                slides_name=f"{content.title} - Slides",
                doc_name=f"{content.title} - Worksheet",
                idempotency_key=_build_idempotency_key(args, content.title, material_requirement),
                slides_requests=tuple(build_slides_replace_requests(content)),
                docs_requests=tuple(build_docs_replace_requests(content)),
            ),
            drive_service=build_drive_service(credentials),
            slides_service=build_slides_service(credentials),
            docs_service=build_docs_service(credentials),
        )
        if not receipt.succeeded:
            raise RuntimeError(f"Live build incomplete: slides={receipt.slides.state}; worksheet={receipt.worksheet.state}; manual_reconciliation_required={receipt.manual_reconciliation_required}")
        if visual_plan.selected_asset_ids:
            print(f"Approved visual assets: {', '.join(visual_plan.selected_asset_ids)}")
        print(f"Slides: {receipt.slides.web_view_link}")
        print(f"Worksheet: {receipt.worksheet.web_view_link}")
        return 0
    except Exception as exc:
        lesson_path = record_lesson(lesson_from_exception(exc, context), args.lessons_dir)
        print(f"Build failed: {exc}", file=sys.stderr)
        print(f"Lesson recorded: {lesson_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
