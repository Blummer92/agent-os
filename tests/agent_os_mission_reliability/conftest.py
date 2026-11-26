"""Keep slice tests, including defect toggles, offline without touching import paths."""

import socket

import pytest


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch):
    """Fail a test before any live DNS lookup or socket connection."""
    def unexpected(*args, **kwargs):
        pytest.fail("Mission Reliability tests must use an offline transport fixture.")
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected)
    monkeypatch.setattr(socket.socket, "connect", unexpected)
