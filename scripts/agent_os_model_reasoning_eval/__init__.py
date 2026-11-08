"""Fixture-first model x reasoning evaluation harness for #3337 (AN-MR2).

Compares identical frozen canonical Agent OS task packets (T1-T7) across
candidate model x reasoning-setting identities using ONLY fixture/mock
providers. This package is structurally incapable of live network calls:

- no adapter, provider, or runner code constructs an HTTP client;
- no network library is imported anywhere in the package
  (httpx, requests, urllib.request, aiohttp are all absent);
- any provider that is not a fixture/mock provider fails closed with
  ``LiveCallRefusedError`` before any execution attempt;
- results record measured offline cost (always $0.00) and never project
  live costs.

Task/reasoning semantics are reused from the AN-MR1 provider-neutral
contract (#3336, merged #3375): packets classify what reasoning a task
requires; candidate identities name requestable model x setting
configurations; the two are never conflated.

Results are component evidence only: this package never emits a universal
"best model" score and never authorizes execution, readiness, merge, or
closure.
"""

from .metrics import aggregate, score_run
from .providers import (
    CandidateIdentity,
    LiveCallRefusedError,
    MockModelProvider,
    ProviderObservation,
    load_candidates,
)
from .runner import EvaluationReport, EvaluationRunner
from .task_packets import TaskFamily, TaskPacket, load_packets

__all__ = [
    "CandidateIdentity",
    "EvaluationReport",
    "EvaluationRunner",
    "LiveCallRefusedError",
    "MockModelProvider",
    "ProviderObservation",
    "TaskFamily",
    "TaskPacket",
    "aggregate",
    "load_candidates",
    "load_packets",
    "score_run",
]
