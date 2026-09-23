"""Operational consumer that imports and uses the registered interface."""

from src.cleanpkg.core import run


def use_it(number: int) -> int:
    return run(number)
