"""D07 fail-first frontend receipt integrity probes.

A successful exit code is not a proof that the expected command ran or that
Vitest/Playwright executed tests. No production or workflow files are changed.
"""
from __future__ import annotations

import pytest

from scripts import agent_os_frontend_checks as fe


def _project(name):
    return next(p for p in fe.PROJECTS if p.name == name)


@pytest.mark.parametrize("project_name", ["picture-perfect-coach", "teacher-os-web"])
def test_d07_rejects_same_length_wrong_command_identity(project_name):
    project = _project(project_name)
    record = [(" ".join(argv), 0) for argv in project.commands]
    record[-1] = ("npm run unrelated-but-green", 0)
    assert fe.evaluate([project], {project.name: record}), "wrong command must not pass"


@pytest.mark.parametrize("project_name", ["picture-perfect-coach", "teacher-os-web"])
def test_d07_missing_required_obligation_cannot_be_erased_from_registry(project_name):
    project = _project(project_name)
    # An untrusted or accidentally edited runtime registry drops the final
    # command. The evaluator must have an independent expected obligation.
    mutant = project._replace(commands=project.commands[:-1])
    record = [(" ".join(argv), 0) for argv in mutant.commands]
    assert fe.evaluate([mutant], {mutant.name: record}), "deleted obligation must not pass"


def test_d07_zero_case_playwright_success_is_not_execution_evidence():
    project = _project("teacher-os-web")
    record = [(" ".join(argv), 0) for argv in project.commands]
    # The current receipt schema has only command text and exit code, so this
    # exact same record can represent a real test run or a zero-case stub.
    # The desired contract must reject this receipt without independent proof.
    assert fe.evaluate([project], {project.name: record}), "no case evidence must not pass"


def test_d07_nonzero_browser_exit_remains_blocking():
    project = _project("teacher-os-web")
    record = [(" ".join(argv), 0) for argv in project.commands]
    record[-1] = (record[-1][0], 1)
    assert fe.evaluate([project], {project.name: record})
