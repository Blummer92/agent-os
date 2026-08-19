#!/usr/bin/env python3
"""Claude Code hook entrypoint for the #1237 governed-route preflight.

Wired from ``.claude/settings.json`` so it runs before the model selects
generic GitHub publish tooling or checks local ``git``/``gh`` prerequisites:

```bash
scripts/agent-os-execution-interface-preflight.py --hook user-prompt-submit
scripts/agent-os-execution-interface-preflight.py --hook pre-tool-use
scripts/agent-os-execution-interface-preflight.py --repository <owner/name> --issue <n>
```

The hook modes read their JSON payload from stdin. The direct mode prints
canonical preflight JSON and is the inspectable form of the same decision.

The entrypoint always exits ``0``: it is an advisory routing seam, not a gate.
Fail-closed behavior belongs to the emitted decision (``not-found`` /
``needs-decision``), never to killing the host turn.
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
    run_user_prompt_submit_hook,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve the governed Agent OS route before generic publish tooling.",
    )
    parser.add_argument("--hook", choices=("user-prompt-submit", "pre-tool-use"))
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
        handler = (
            run_user_prompt_submit_hook
            if args.hook == "user-prompt-submit"
            else run_pre_tool_use_hook
        )
        try:
            output = handler(raw)
        except Exception:  # never let an advisory seam break the host turn
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
