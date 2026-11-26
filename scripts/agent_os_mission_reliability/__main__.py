"""Entrypoint for `python -m scripts.agent_os_mission_reliability`; no logic or setup."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
