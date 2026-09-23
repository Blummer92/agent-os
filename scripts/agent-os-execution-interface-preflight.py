#!/usr/bin/env python3
"""Claude Code hook entrypoint for governed Agent OS route re-entry.

Wired from ``.claude/settings.json`` for prompt submission, mutation-capable
PreToolUse events, and turn Stop evaluation. Hook modes read JSON from stdin.
Direct mode remains the inspectable governed-route preflight.

Every mode exits ``0``. PreToolUse remains advisory. Stop may return the host's
bounded ``decision=block`` response only when an already-structured continuation
decision names an authorized executable next action; evaluator errors fail open.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.agent_os_execution_interface.governed_route_preflight import (  # noqa: E402
    resolve_governed_route_preflight,
    serialize_preflight_result,
)
from scripts.agent_os_execution_interface.hook_adapter import (  # noqa: E402
    render_preflight_notice,
    resolve_store_root,
    run_pre_tool_use_hook,
    run_stop_hook,
    run_user_prompt_submit_hook,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve governed Agent OS routing and bounded continuation hooks.",
    )
    parser.add_argument("--hook", choices=("user-prompt-submit", "pre-tool-use", "stop"))
    parser.add_argument("--repository")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--checkout-root", default=".")
    parser.add_argument("--store-root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else list(argv))

    if args.hook is not None:
        try:
            raw = sys.stdin.read()
        except (OSError, ValueError):
            return 0
        handlers = {
            "user-prompt-submit": run_user_prompt_submit_hook,
            "pre-tool-use": run_pre_tool_use_hook,
            "stop": run_stop_hook,
        }
        try:
            output = handlers[args.hook](raw)
        except Exception:  # never let a governance seam trap the host turn
            return 0
        if output:
            print(output)
        return 0

    result = resolve_governed_route_preflight(
        checkout_root=args.checkout_root,
        repository=args.repository,
        issue_numbers=(args.issue,) if args.issue is not None else (),
        store_root=args.store_root if args.store_root else resolve_store_root(),
    )
    print(serialize_preflight_result(result))
    notice = render_preflight_notice(result)
    if notice:
        print(notice, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
