"""#2826 fresh-reproduction regression: checkpoint composition boundary.

Mirrors the 2026-10-06T00:20Z reproduction: an explicitly authorized parallel
implementation mission (#3249/#3250/#3297 shape) completed its CKR6 issue-start
preflights, then the native host returned an intermediate "preflight is
underway" report instead of dispatching the next admitted step. #3250 carried
an item-local material-decision blocker; #3249 and #3297 remained independent
admissible candidates; no shared blocker was proven.

What these tests prove (repository side only):
- checkpoint complete + executable next action remains + no shared blocker
  composes to NON-terminal with a concrete ``next_action`` and the batch cursor
  preserved;
- genuine terminal dispositions (shared blocker proven, population exhausted,
  requested count delivered) still resolve terminal with an empty action.

What these tests do NOT prove: native ChatGPT next-dispatch. The repository
owns the decision -> payload composition; the native chat turn has no
repository-registered continuation ingestion (see the native-host integration
boundary recorded in ``continuation_driver``). Reconstructed/driver coverage
is never native-host evidence.
"""

from __future__ import annotations

import scripts.agent_os_execution_interface.continuation_driver as continuation_driver
from scripts.agent_os_execution_interface.continuation_driver import (
    completion_continuation_payload,
)
from scripts.agent_os_execution_interface.finite_batch_admission import (
    evaluate_finite_batch_admission,
)
from scripts.agent_os_execution_interface.investigation_completion_admission import (
    evaluate_investigation_completion_admission,
)

REPOSITORY = "Blummer92/agent-os"


def _compose_finite_batch_payload(**kwargs):
    """Compose the reproduction's checkpoint through the existing owners only.

    Finite-batch admission decides; ``completion_continuation_payload`` projects
    the already-decided facts into the canonical host payload. No new decision
    vocabulary is introduced here.
    """
    admission = evaluate_finite_batch_admission(**kwargs)
    payload = completion_continuation_payload(
        terminal=admission.completion_admissible,
        blocked=admission.shared_blocker,
        next_action=admission.next_action,
        reason_codes=admission.reason_codes,
    )
    return admission, payload


def test_checkpoint_complete_with_executable_next_action_is_nonterminal():
    # Reproduction shape: 3 lanes (#3249/#3250/#3297), preflight/checkpoint
    # complete, executable next action remains, no shared blocker proven.
    admission, payload = _compose_finite_batch_payload(
        requested_count=3,
        delivered_count=0,
        reconciled_candidate_count=3,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert admission.completion_admissible is False
    assert admission.next_action == "continue-candidate-cursor"
    # The composed host payload is non-terminal with the concrete next action
    # and the cursor preserved in the reason codes.
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["action"] == "continue-candidate-cursor"
    assert "requested-count-not-satisfied" in payload["reason_codes"]
    assert "population-not-exhausted" in payload["reason_codes"]
    assert payload["execution_authorized"] is False
    assert payload["github_writes_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_item_local_blocker_keeps_batch_nonterminal():
    # Reproduction shape: #3250 carries an item-local material-decision
    # blocker while #3249/#3297 remain independent admissible candidates.
    # Item-local blocking is delivered-short-of-requested with no shared
    # blocker; it must not terminalize the batch.
    admission, payload = _compose_finite_batch_payload(
        requested_count=3,
        delivered_count=1,
        reconciled_candidate_count=3,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert admission.completion_admissible is False
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["action"] == "continue-candidate-cursor"


def test_shared_blocker_proven_resolves_terminal():
    admission, payload = _compose_finite_batch_payload(
        requested_count=3,
        delivered_count=1,
        reconciled_candidate_count=3,
        population_exhausted=False,
        shared_blocker=True,
    )
    assert admission.completion_admissible is True
    assert admission.next_action == "report-shared-terminal-blocker-and-shortfall"
    assert payload["terminal"] is True
    assert payload["blocked"] is True
    # A terminal completion payload carries no executable action.
    assert payload["action"] == ""
    assert "shared-terminal-blocker" in payload["reason_codes"]


def test_population_exhausted_resolves_terminal():
    admission, payload = _compose_finite_batch_payload(
        requested_count=3,
        delivered_count=1,
        reconciled_candidate_count=3,
        population_exhausted=True,
        shared_blocker=False,
    )
    assert admission.completion_admissible is True
    assert admission.next_action == "report-proven-population-exhaustion-and-shortfall"
    assert payload["terminal"] is True
    assert payload["action"] == ""


def test_requested_count_delivered_resolves_terminal():
    admission, payload = _compose_finite_batch_payload(
        requested_count=3,
        delivered_count=3,
        reconciled_candidate_count=3,
        population_exhausted=False,
        shared_blocker=False,
    )
    assert admission.completion_admissible is True
    assert admission.next_action == "report-requested-count-delivered"
    assert payload["terminal"] is True
    assert payload["action"] == ""


def test_investigation_checkpoint_with_next_action_is_nonterminal():
    # The other half of the reproduction: a checkpoint is written while a
    # material branch remains intermediate and an executable next action
    # remains. The composed payload must stay non-terminal.
    decision = evaluate_investigation_completion_admission(
        repository=REPOSITORY,
        issue_number=2826,
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=True,
        subordinate_write_performed=True,
    )
    assert decision.completion_admissible is False
    assert decision.next_action == "continue-same-lineage-investigation"
    payload = completion_continuation_payload(
        terminal=decision.completion_admissible,
        blocked=False,
        next_action=decision.next_action,
        reason_codes=decision.reason_codes,
    )
    assert payload["terminal"] is False
    assert payload["action"] == "continue-same-lineage-investigation"
    assert "authorized-executable-next-action-remains" in payload["reason_codes"]


def test_native_host_boundary_is_recorded():
    # The external integration boundary is executable documentation: the
    # canonical payload owner must keep stating that the native ChatGPT turn
    # has no repository-registered continuation ingestion, so the record
    # cannot be silently dropped.
    docstring = continuation_driver.__doc__ or ""
    assert "native ChatGPT" in docstring
    assert "no repository-registered continuation ingestion" in docstring
    assert "cannot enforce next-dispatch" in docstring
