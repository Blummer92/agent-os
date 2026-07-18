from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .discovery import discover_capabilities
from .models import Confidence
from .reader import RegistryError, RegistryReader
from .serialization import render_text_results, serialize_discovery_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover reusable Agent OS capabilities offline.")
    parser.add_argument("--registry", type=Path, help="Explicit local registry YAML path.")
    parser.add_argument("--id", dest="capability_id", help="Exact capability ID.")
    parser.add_argument("--keyword", action="append", default=[], help="Keyword; repeat to require all.")
    parser.add_argument("--owner", help="Exact owner agent.")
    parser.add_argument("--status", help="Exact capability status.")
    parser.add_argument("--canonical-path", help="Exact registered canonical path.")
    parser.add_argument("--public-interface", help="Exact registered public interface.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not any(
        (
            args.capability_id,
            args.keyword,
            args.owner,
            args.status,
            args.canonical_path,
            args.public_interface,
        )
    ):
        parser.error("at least one lookup option is required")
    try:
        reader = RegistryReader(args.registry)
        results = discover_capabilities(
            reader,
            capability_id=args.capability_id,
            keywords=args.keyword,
            owner=args.owner,
            status=args.status,
            canonical_path=args.canonical_path,
            public_interface=args.public_interface,
        )
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(serialize_discovery_results(results), end="")
    else:
        print(render_text_results(results), end="")
    if not results:
        return 1
    if any(result.confidence is Confidence.MANUAL_REVIEW for result in results):
        return 2
    return 0
