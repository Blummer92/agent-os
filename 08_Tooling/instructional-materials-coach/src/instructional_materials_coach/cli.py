"""CLI: build a slide deck and worksheet for one lesson from an approved template pair.

Refuses to run unless ALLOW_WRITE=true, on top of the write-authorization
rules this tool inherits from the Instructional Materials Coach overlay.

On a failed build, writes a local lesson-candidate record instead of
failing silently (see lesson_record.py) -- this tool never writes to
Notion itself; a human applies the record to the real Lessons Learned
database.
"""
from __future__ import annotations

import argparse
import os
import sys

from .content_spec import load_lesson_content
from .docs_requests import build_docs_replace_requests
from .drive_client import build_drive_service, duplicate_template, get_credentials, get_file_link
from .lesson_record import LEARNING_TYPES, SEVERITIES, LessonRecord, lesson_from_exception, record_lesson
from .slides_requests import build_slides_replace_requests
from .workspace_clients import apply_docs_requests, apply_slides_requests, build_docs_service, build_slides_service

DEFAULT_LESSONS_DIR = "reports/lessons"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build instructional materials from an approved template, or log a lesson learned."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="Build a slide deck and worksheet from an approved template and lesson content."
    )
    build.add_argument("--content", required=True, help="Path to the lesson content YAML file.")
    build.add_argument("--slides-template", required=True, help="File ID of the approved Slides template.")
    build.add_argument("--doc-template", required=True, help="File ID of the approved Doc template.")
    build.add_argument("--target-folder", required=True, help="Drive folder ID the new files are created in.")
    build.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", ""))
    build.add_argument("--token-path", default=os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", ""))
    build.add_argument(
        "--lessons-dir",
        default=DEFAULT_LESSONS_DIR,
        help="Where lesson-candidate records are written if the build fails.",
    )

    log_lesson = subparsers.add_parser(
        "log-lesson", help="Manually record a lesson (e.g. QA feedback) without building anything."
    )
    log_lesson.add_argument("--title", required=True, help="Short summary -- becomes the Lesson Learned title.")
    log_lesson.add_argument("--what-happened", required=True)
    log_lesson.add_argument("--what-to-do-next-time", default="")
    log_lesson.add_argument("--guardrail", default="")
    log_lesson.add_argument("--severity", default="Low", choices=SEVERITIES)
    log_lesson.add_argument("--learning-type", default="QA feedback", choices=LEARNING_TYPES)
    log_lesson.add_argument("--source-link", default="")
    log_lesson.add_argument("--lessons-dir", default=DEFAULT_LESSONS_DIR)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "log-lesson":
        record = LessonRecord(
            lesson_learned=args.title,
            what_happened=args.what_happened,
            what_to_do_next_time=args.what_to_do_next_time,
            guardrail=args.guardrail,
            severity=args.severity,
            learning_type=args.learning_type,
            source_link=args.source_link,
        )
        path = record_lesson(record, args.lessons_dir)
        print(f"Lesson recorded: {path}")
        return 0

    if os.environ.get("ALLOW_WRITE", "false").lower() != "true":
        print("Refusing to run: set ALLOW_WRITE=true to confirm this should write to Drive.", file=sys.stderr)
        return 1

    context = {
        "slides_template": args.slides_template,
        "doc_template": args.doc_template,
        "target_folder": args.target_folder,
        "content_path": args.content,
    }
    try:
        content = load_lesson_content(args.content)
        context["content_title"] = content.title

        credentials = get_credentials(args.client_secret, args.token_path)
        drive_service = build_drive_service(credentials)

        slides_id = duplicate_template(
            drive_service, args.slides_template, args.target_folder, f"{content.title} - Slides"
        )
        doc_id = duplicate_template(
            drive_service, args.doc_template, args.target_folder, f"{content.title} - Worksheet"
        )

        slides_service = build_slides_service(credentials)
        docs_service = build_docs_service(credentials)
        apply_slides_requests(slides_service, slides_id, build_slides_replace_requests(content))
        apply_docs_requests(docs_service, doc_id, build_docs_replace_requests(content))

        print(f"Slides: {get_file_link(drive_service, slides_id)}")
        print(f"Worksheet: {get_file_link(drive_service, doc_id)}")
        return 0
    except Exception as exc:
        lesson = lesson_from_exception(exc, context)
        lesson_path = record_lesson(lesson, args.lessons_dir)
        print(f"Build failed: {exc}", file=sys.stderr)
        print(f"Lesson recorded: {lesson_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
