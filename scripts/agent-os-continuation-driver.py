#!/usr/bin/env python3
"""Inspectable runtime entrypoint for the bounded Agent OS continuation driver.

This command does not grant authority or perform repository mutations by itself.
Host composition supplies the canonical observer, classifier, and dispatcher.
"""

from scripts.agent_os_execution_interface.continuation_driver import MAX_DRIVER_TRANSITIONS


def main() -> int:
    print(f"agent-os continuation driver available; max_transitions={MAX_DRIVER_TRANSITIONS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
