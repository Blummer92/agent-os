"""CLI: build a slide deck and worksheet for one lesson from an approved template pair.

Refuses to run unless ALLOW_WRITE=true, on top of the write-authorization
rules this tool inherits from the Instructional Materials Coach overlay.
"""
from __future__ import annotations

import argparse
import os
import sys

from .content_spec import load_lesson_content
from .docs_requests import build_docs_replace_requests
from .drive_client import build_drive_service, duplicate_template, get_credentials, get_file_link
from .slides_requests import build_slides_replace_requests
from .workspace_clients import apply_docs_requests, apply_slides_requests, build_docs_service, build_slides_service


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a slide deck and worksheet from an approved template and lesson content."
    )
    parser.add_argument("--content", required=True, help="Path to the lesson content YAML file.")
    parser.add_argument("--slides-template", required=True, help="File ID of the approved Slides template.")
    parser.add_argument("--doc-template", required=True, help="File ID of the approved Doc template.")
    parser.add_argument("--target-folder", required=True, help="Drive folder ID the new files are created in.")
    parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", ""))
    parser.add_argument("--token-path", default=os.environ.get("GOOGLE_OAUTH_TOKEN_PATH", ""))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("ALLOW_WRITE", "false").lower() != "true":
        print("Refusing to run: set ALLOW_WRITE=true to confirm this should write to Drive.", file=sys.stderr)
        return 1

    args = parse_args(argv)
    content = load_lesson_content(args.content)

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


if __name__ == "__main__":
    raise SystemExit(main())
