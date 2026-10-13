"""Focused coverage for scripts/agent_os_issue_acceptance/pr_lineage_reader.py (#3441).

Fixture-first and network free: the reader is exercised through in-memory
read ports. Covers population enumeration and its self-proven completeness,
classification of pull requests against an issue with the existing ``parse_pr``
authority, per-issue acquisition through the unchanged #3433 evaluator, and
every fail-closed path (bound exhaustion, rate limit, malformed or conflicting
records, drift between observations). Fixture success is not live evidence.
"""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts.agent_os_candidate_packet_live_input import (
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_issue_acceptance import pr_lineage_reader as reader_module
from scripts.agent_os_issue_acceptance.github_issue_source import GitHubIssuePageResponse
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    MAX_PRIMARY_CLAIMS,
    LifecycleStage,
)
from scripts.agent_os_issue_acceptance.lifecycle_stage_acquisition import (
    LifecycleAcquisitionOutcome,
)
from scripts.agent_os_issue_acceptance.pr_lineage_reader import (
    REASON_CLAIMS_EXCEED_BOUND,
    REASON_CONFLICTING_DUPLICATE,
    REASON_CROSS_REPOSITORY_RECORD,
    REASON_DEFAULT_BRANCH_MOVED,
    REASON_DEFAULT_BRANCH_UNREADABLE,
    REASON_DETAIL_READ_FAILED,
    REASON_ISSUE_READ_FAILED,
    REASON_ISSUE_STATE_UNSUPPORTED,
    REASON_LIST_DETAIL_DISAGREEMENT,
    REASON_MALFORMED_PR_RECORD,
    REASON_PAGE_BOUND_EXHAUSTED,
    REASON_PAGE_READ_FAILED,
    REASON_PAGINATION_UNPROVEN,
    REASON_POPULATION_COMPLETE,
    REASON_POPULATION_SHIFTED,
    REASON_REPOSITORY_MISMATCH,
    PrLineageAcquirer,
    PrPopulation,
    PullRequestDetailOutcome,
    PullRequestDetailResult,
    enumerate_pull_request_population,
)

REPO = "Blummer92/agent-os"
OBSERVED_AT = "2026-10-13T20:00:00Z"
MAIN_SHA = "a" * 40
OTHER_MAIN_SHA = "b" * 40
ISSUE = 3441


def head(n: int) -> str:
    return f"{n:040x}"


def pr_item(
    number: int,
    *,
    state: str = "open",
    draft: bool = False,
    merged: bool = False,
    sha: str | None = None,
    ref: str | None = None,
    title: str | None = None,
    body: str | None = "",
    repo: str = REPO,
) -> dict[str, object]:
    return {
        "number": number,
        "state": state,
        "draft": draft,
        "merged_at": "2026-10-12T10:00:00Z" if merged else None,
        "title": title if title is not None else f"PR {number}",
        "body": body,
        "head": {"sha": sha or head(number), "ref": ref or f"agent/{number}-work"},
        "base": {"repo": {"full_name": repo}},
    }


def closes(issue: int = ISSUE) -> str:
    return f"## Linked issue\n\nCloses #{issue}\n"


class FakePageReader:
    """Serves a fixed PR table in pages; records every page request."""

    def __init__(self, items, *, per_page: int = 100, fail_on_page: int | None = None,
                 fail_with: BaseException | None = None, error_kind: str | None = None,
                 terminal_proven: bool = True, skip_next: bool = False) -> None:
        self.items = list(items)
        self.per_page = per_page
        self.calls: list[int] = []
        self._fail_on_page = fail_on_page
        self._fail_with = fail_with
        self._error_kind = error_kind
        self._terminal_proven = terminal_proven
        self._skip_next = skip_next

    def read_pull_request_page(self, repository, *, page, per_page, state):
        self.calls.append(page)
        assert state == "all", "the population must be the all-state listing"
        assert per_page == self.per_page or self.per_page == 100
        if self._fail_on_page == page:
            if self._fail_with is not None:
                raise self._fail_with
            return GitHubIssuePageResponse(
                items=(), next_page=None, complete=False,
                error_kind=self._error_kind or "rate-limited", page=page,
            )
        size = self.per_page
        chunk = self.items[(page - 1) * size : page * size]
        has_next = page * size < len(self.items)
        next_page = (page + 1) if has_next else None
        if self._skip_next and has_next:
            next_page = page + 2
        return GitHubIssuePageResponse(
            items=tuple(copy.deepcopy(chunk)),
            next_page=next_page,
            complete=True,
            terminal_page_proven=(not has_next) and self._terminal_proven,
            page=page,
            source_query_string=f"state={state}&per_page={per_page}&page={page}",
            rate_limit_remaining="4990",
        )


class FakeDetailReader:
    def __init__(self, items, *, overrides=None) -> None:
        self._items = {item["number"]: item for item in items}
        self._overrides = overrides or {}
        self.calls: list[int] = []

    def read_pull_request(self, repository, number):
        self.calls.append(number)
        if number in self._overrides:
            return self._overrides[number]
        return PullRequestDetailResult(
            PullRequestDetailOutcome.OK, copy.deepcopy(self._items[number])
        )


def issue_item(number: int = ISSUE, *, state: str = "open", body: str = "body") -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "body": body,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": "2026-10-08T16:13:39Z",
        "updated_at": "2026-10-11T15:56:33Z",
        "closed_at": None if state == "open" else "2026-10-12T00:00:00Z",
        "state_reason": None if state == "open" else "completed",
        "labels": [{"name": "agent-os"}],
    }


@dataclass
class FakeIssueTransport:
    item: dict | None = field(default_factory=issue_item)
    outcome: SingleIssueTransportOutcome = SingleIssueTransportOutcome.OK
    calls: int = 0

    def get_issue(self, repository, issue_number):
        self.calls += 1
        if self.outcome is not SingleIssueTransportOutcome.OK:
            return SingleIssueTransportResult(outcome=self.outcome)
        item = copy.deepcopy(self.item)
        item["number"] = issue_number  # the transport answers the issue asked for
        return SingleIssueTransportResult(outcome=SingleIssueTransportOutcome.OK, item=item)


class MainSha:
    """Default-branch reader whose answer can change between reads."""

    def __init__(self, *shas: str) -> None:
        self._shas = list(shas)
        self.calls = 0

    def __call__(self) -> str:
        value = self._shas[min(self.calls, len(self._shas) - 1)]
        self.calls += 1
        if isinstance(value, BaseException):
            raise value
        return value


def make_acquirer(items, *, issue=None, main=None, per_page=100, max_pages=40,
                  pages=None, details=None) -> tuple[PrLineageAcquirer, FakePageReader,
                                                      FakeDetailReader, FakeIssueTransport]:
    page_reader = pages or FakePageReader(items, per_page=per_page)
    detail_reader = details or FakeDetailReader(items)
    transport = issue or FakeIssueTransport()
    acquirer = PrLineageAcquirer(
        repository=REPO,
        issue_transport=transport,
        page_reader=page_reader,
        detail_reader=detail_reader,
        source_revision_reader=main or MainSha(MAIN_SHA),
        observed_at=OBSERVED_AT,
        per_page=per_page,
        max_pages=max_pages,
    )
    return acquirer, page_reader, detail_reader, transport


def enumerate_items(items, **kwargs) -> tuple[PrPopulation, FakePageReader]:
    reader = kwargs.pop("reader", None) or FakePageReader(items, per_page=kwargs.get("per_page", 100))
    population = enumerate_pull_request_population(
        REPO, reader, observed_at=OBSERVED_AT, source_revision=MAIN_SHA,
        per_page=kwargs.get("per_page", 100), max_pages=kwargs.get("max_pages", 40),
    )
    return population, reader


# ---------------------------------------------------------------------------
# Population enumeration: completeness is proven by the enumerator itself
# ---------------------------------------------------------------------------


def test_zero_pull_requests_single_terminal_page_is_complete() -> None:
    population, reader = enumerate_items([])
    assert population.complete is True
    assert population.reason_codes == (REASON_POPULATION_COMPLETE,)
    assert population.facts == ()
    assert reader.calls == [1]


def test_multi_page_population_is_complete_sorted_and_carries_provenance() -> None:
    items = [pr_item(n) for n in (5, 4, 3, 2, 1)]  # newest first, as GitHub lists
    population, reader = enumerate_items(items, per_page=2)
    assert population.complete is True
    assert reader.calls == [1, 2, 3]
    assert [fact.number for fact in population.facts] == [1, 2, 3, 4, 5]
    pages = population.page_observations
    assert [obs.page for obs in pages] == [1, 2, 3]
    assert [obs.item_count for obs in pages] == [2, 2, 1]
    assert pages[-1].terminal_page_proven is True and pages[-1].next_page is None
    assert pages[0].source_query_string == "state=all&per_page=2&page=1"
    assert pages[0].rate_limit_remaining == "4990"
    summary = population.summary()
    assert summary["page_count"] == 3 and summary["pull_request_count"] == 5
    assert summary["source_revision"] == MAIN_SHA
    json.dumps(summary)  # JSON-ready


def test_exactly_full_terminal_page_is_complete() -> None:
    population, _ = enumerate_items([pr_item(1), pr_item(2)], per_page=2)
    assert population.complete is True
    assert len(population.facts) == 2


def test_missing_terminal_proof_is_incomplete_not_negative_evidence() -> None:
    reader = FakePageReader([pr_item(1)], terminal_proven=False)
    population, _ = enumerate_items([], reader=reader)
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGINATION_UNPROVEN,)
    assert population.facts == () and population.references == ()


def test_non_contiguous_next_page_is_incomplete() -> None:
    reader = FakePageReader([pr_item(n) for n in range(1, 6)], per_page=2, skip_next=True)
    population, _ = enumerate_items([], reader=reader, per_page=2)
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGINATION_UNPROVEN,)
    assert "contiguous" in population.note


def test_page_bound_exhaustion_is_incomplete_and_exact_bound_is_complete() -> None:
    items = [pr_item(n) for n in range(1, 6)]
    exhausted, reader = enumerate_items(items, per_page=2, max_pages=2)
    assert exhausted.complete is False
    assert exhausted.reason_codes == (REASON_PAGE_BOUND_EXHAUSTED,)
    assert reader.calls == [1, 2]  # never reads past the explicit bound
    assert exhausted.facts == ()
    exact, _ = enumerate_items(items[:4], per_page=2, max_pages=2)
    assert exact.complete is True and len(exact.facts) == 4


def test_rate_limited_page_is_incomplete() -> None:
    reader = FakePageReader([pr_item(1)], fail_on_page=1, error_kind="rate-limited")
    population, _ = enumerate_items([], reader=reader)
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGE_READ_FAILED,)
    assert "rate-limited" in population.note


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (PermissionError("denied"), "permission-denied"),
        (LookupError("gone"), "source-inaccessible"),
        (RuntimeError("boom"), "api-error"),
        (ValueError("bad json"), "malformed-response"),
        (TypeError("bad type"), "malformed-response"),
    ],
)
def test_reader_exceptions_become_incomplete_populations(error, label) -> None:
    reader = FakePageReader([pr_item(1)], fail_on_page=1, fail_with=error)
    population, _ = enumerate_items([], reader=reader)
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGE_READ_FAILED,)
    assert label in population.note


def test_failure_on_a_later_page_discards_earlier_pages() -> None:
    reader = FakePageReader([pr_item(n) for n in range(1, 6)], per_page=2,
                            fail_on_page=2, fail_with=RuntimeError("boom"))
    population, _ = enumerate_items([], reader=reader, per_page=2)
    assert population.complete is False
    assert population.facts == ()  # a partial listing is never exposed as evidence
    assert len(population.page_observations) == 1


def test_incomplete_flag_on_page_is_pagination_unproven() -> None:
    class Reader:
        def read_pull_request_page(self, repository, *, page, per_page, state):
            return GitHubIssuePageResponse(items=(), next_page=None, complete=False)

    population = enumerate_pull_request_population(
        REPO, Reader(), observed_at=OBSERVED_AT, source_revision=MAIN_SHA
    )
    assert population.reason_codes == (REASON_PAGINATION_UNPROVEN,)


def test_non_response_return_value_is_incomplete() -> None:
    class Reader:
        def read_pull_request_page(self, repository, *, page, per_page, state):
            return {"items": []}

    population = enumerate_pull_request_population(
        REPO, Reader(), observed_at=OBSERVED_AT, source_revision=MAIN_SHA
    )
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGE_READ_FAILED,)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.pop("number"),
        lambda item: item.update(number=True),
        lambda item: item.update(number=0),
        lambda item: item.update(state="merged"),
        lambda item: item.update(draft="no"),
        lambda item: item.update(merged_at=5),
        lambda item: item.update(state="open", merged_at="2026-10-12T10:00:00Z"),
        lambda item: item["head"].update(sha="ABC"),
        lambda item: item["head"].update(ref=""),
        lambda item: item.update(head="not-a-mapping"),
        lambda item: item["base"].update(repo={}),
        lambda item: item["base"]["repo"].update(full_name="no-slash"),
        lambda item: item.update(title=None),
        lambda item: item.update(body=12),
    ],
    ids=[
        "no-number", "bool-number", "zero-number", "bad-state", "draft-not-bool",
        "merged-at-not-text", "open-but-merged", "bad-head-sha", "empty-head-ref",
        "head-not-mapping", "base-repo-empty", "base-repo-malformed", "title-null",
        "body-not-text",
    ],
)
def test_malformed_pull_request_record_makes_population_incomplete(mutate) -> None:
    item = pr_item(7)
    mutate(item)
    population, _ = enumerate_items([item])
    assert population.complete is False
    assert population.reason_codes == (REASON_MALFORMED_PR_RECORD,)
    assert population.facts == ()


def test_non_mapping_record_is_rejected_at_the_page_container() -> None:
    # The shared page container refuses non-mapping items, so the page read
    # itself fails closed before any record is trusted.
    reader = FakePageReader([])
    reader.items = ["not-a-mapping"]
    population, _ = enumerate_items([], reader=reader)
    assert population.complete is False
    assert population.reason_codes == (REASON_PAGE_READ_FAILED,)
    assert "malformed-response" in population.note


def test_cross_repository_record_makes_population_incomplete() -> None:
    population, _ = enumerate_items([pr_item(1), pr_item(2, repo="other/repo")])
    assert population.complete is False
    assert population.reason_codes == (REASON_CROSS_REPOSITORY_RECORD,)
    assert "other/repo" in population.note


def test_repository_comparison_is_case_insensitive() -> None:
    population, _ = enumerate_items([pr_item(1, repo="blummer92/AGENT-OS")])
    assert population.complete is True


def test_identical_duplicate_observation_proves_an_unobserved_pull_request() -> None:
    first, second = pr_item(2), pr_item(1)
    reader = FakePageReader([first, second, pr_item(2)], per_page=2)
    # page 1: [2, 1]; page 2: [2]. Newest-first listing: a PR opened mid-listing
    # pushed #2 onto page 2, and that new PR was never observed.
    population, _ = enumerate_items([], reader=reader, per_page=2)
    assert population.complete is False
    assert population.reason_codes == (REASON_POPULATION_SHIFTED,)
    assert population.duplicate_observations == 1
    assert "#2 listed twice" in population.note
    assert population.facts == () and population.references == ()


@pytest.mark.parametrize(
    "changed",
    [
        {"state": "closed"},
        {"sha": head(999)},
        {"draft": True},
        {"body": "edited"},
        {"merged": True, "state": "closed"},
    ],
)
def test_conflicting_duplicate_observation_makes_population_incomplete(changed) -> None:
    reader = FakePageReader([pr_item(2), pr_item(1), pr_item(2, **changed)], per_page=2)
    population, _ = enumerate_items([], reader=reader, per_page=2)
    assert population.complete is False
    assert population.reason_codes == (REASON_CONFLICTING_DUPLICATE,)
    assert population.duplicate_observations == 1


def test_closed_draft_pull_request_is_not_a_draft() -> None:
    population, _ = enumerate_items([pr_item(1, state="closed", draft=True)])
    (fact,) = population.facts
    assert fact.is_open is False and fact.is_draft is False and fact.is_merged is False


def test_incomplete_population_cannot_carry_facts() -> None:
    with pytest.raises(ValueError, match="exposes no facts"):
        PrPopulation(
            repository=REPO, observed_at=OBSERVED_AT, source_revision=MAIN_SHA,
            source_query="q", complete=False, reason_codes=("x",), note="n",
            facts=enumerate_items([pr_item(1)])[0].facts,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "no-slash"},
        {"observed_at": "yesterday"},
        {"source_revision": "short"},
        {"per_page": 0},
        {"per_page": 101},
        {"max_pages": 0},
    ],
)
def test_enumeration_arguments_are_validated(kwargs) -> None:
    arguments = dict(repository=REPO, observed_at=OBSERVED_AT, source_revision=MAIN_SHA)
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        enumerate_pull_request_population(
            arguments.pop("repository"), FakePageReader([]), **arguments
        )


# ---------------------------------------------------------------------------
# Classification against one issue: the existing parse_pr authority decides
# ---------------------------------------------------------------------------


def roles_for(items, issue: int = ISSUE) -> list[tuple[int, str]]:
    population, _ = enumerate_items(items)
    assert population.complete
    return [
        (ref.pull_request_number, ref.role)
        for ref in population.references
        if ref.issue_number == issue
    ]


def test_standalone_closing_directive_is_a_claim() -> None:
    assert roles_for([pr_item(10, body=closes())]) == [(10, "claim")]


def test_duplicate_identical_closing_references_are_one_claim() -> None:
    body = f"Closes #{ISSUE}\n\nCloses #{ISSUE}\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "claim")]


@pytest.mark.parametrize(
    "body",
    [
        f"Part of #{ISSUE}\n",
        f"Refs #{ISSUE}\n",
        f"This is related to #{ISSUE} but does not close it.\n",
    ],
)
def test_non_authoritative_reference_is_an_ambiguous_claim_not_dropped(body) -> None:
    assert roles_for([pr_item(10, body=body)]) == [(10, "ambiguous")]


def test_title_only_reference_is_ambiguous() -> None:
    assert roles_for([pr_item(10, title=f"Work for #{ISSUE}", body="")]) == [(10, "ambiguous")]


def test_pull_request_resolved_to_another_issue_keeps_this_mention_ambiguous() -> None:
    body = f"Closes #4000\n\nBackground: see #{ISSUE}.\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "ambiguous")]
    assert roles_for([pr_item(10, body=body)], issue=4000) == [(10, "claim")]


def test_pull_request_resolved_to_another_issue_keeps_a_title_mention_ambiguous() -> None:
    items = [pr_item(10, title=f"Follow-up to #{ISSUE}", body="Closes #4000\n")]
    assert roles_for(items) == [(10, "ambiguous")]
    assert roles_for(items, issue=4000) == [(10, "claim")]


@pytest.mark.parametrize(
    "masked",
    [
        f"`Fixes #{ISSUE}`",
        f"```\nresolves #{ISSUE}\n```",
        f"<!-- closes #{ISSUE} -->",
    ],
)
def test_a_target_github_would_close_is_ambiguous_even_where_parse_pr_masks_it(masked) -> None:
    items = [pr_item(10, body=f"Closes #4000\n\n{masked}\n")]
    assert roles_for(items) == [(10, "ambiguous")]
    assert roles_for(items, issue=4000) == [(10, "claim")]


def test_a_canonical_qualified_closing_target_survives_the_detector_defect() -> None:
    # detect_github_effective_closing_references raises on "Closes <canonical>#N";
    # the reader folds the qualifier the way normalize_issue_target does and asks again.
    items = [pr_item(10, body=f"Closes #4000\n\n`closes BLUMMER92/agent-os#{ISSUE}`\n")]
    assert roles_for(items) == [(10, "ambiguous")]
    assert roles_for(items, issue=4000) == [(10, "claim")]


def test_unreadable_closing_references_make_the_population_incomplete(monkeypatch) -> None:
    import scripts.agent_os_issue_acceptance.pr_lineage_reader as reader_module

    def broken(body, title=""):
        raise ValueError("detector failure")

    monkeypatch.setattr(reader_module, "detect_github_effective_closing_references", broken)
    population, _ = enumerate_items([pr_item(1), pr_item(10, body=closes())])
    assert population.complete is False
    assert population.reason_codes == (REASON_MALFORMED_PR_RECORD,)
    assert "references unreadable" in population.note


def test_the_claim_outranks_other_mentions_of_the_same_issue() -> None:
    body = f"Closes #{ISSUE}\n\nSee #{ISSUE} and `fixes #{ISSUE}`.\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "claim")]


def test_a_closing_target_in_another_repository_stays_unrelated() -> None:
    body = f"Closes #4000\n\n`Fixes other/repo#{ISSUE}`\n"
    assert roles_for([pr_item(10, body=body)]) == []


def test_declared_non_closing_reference_is_recorded_but_not_a_claim() -> None:
    body = f"Part of #{ISSUE}\n\nNon-closing: #{ISSUE}\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "declared-non-closing")]


def test_multiple_closing_targets_are_ambiguous_for_each_named_issue() -> None:
    body = f"Closes #{ISSUE}\nCloses #4000\n"
    items = [pr_item(10, body=body)]
    assert roles_for(items) == [(10, "ambiguous")]
    assert roles_for(items, issue=4000) == [(10, "ambiguous")]


def test_reference_to_another_repository_is_unrelated() -> None:
    body = f"Closes other/repo#{ISSUE}\n"
    assert roles_for([pr_item(10, body=body)]) == []


def test_repository_qualified_reference_to_this_repository_is_ambiguous() -> None:
    body = f"Closes {REPO}#{ISSUE}\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "ambiguous")]


def test_pull_request_without_references_is_unrelated() -> None:
    assert roles_for([pr_item(10, body="no links here")]) == []


def test_a_fenced_closing_keyword_is_not_a_claim_but_stays_visible() -> None:
    # parse_pr masks the fence; GitHub's own closing semantics do not, so the
    # reference is ambiguous (manual review), never a claim and never dropped.
    body = f"Example only:\n\n```\nCloses #{ISSUE}\n```\n"
    assert roles_for([pr_item(10, body=body)]) == [(10, "ambiguous")]


def test_a_fenced_plain_mention_is_not_a_reference() -> None:
    body = f"Example only:\n\n```\nsee #{ISSUE}\n```\n"
    assert roles_for([pr_item(10, body=body)]) == []


# ---------------------------------------------------------------------------
# Per-issue acquisition through the unchanged #3433 evaluator
# ---------------------------------------------------------------------------


def acquire(items, **kwargs):
    acquirer, pages, details, transport = make_acquirer(items, **kwargs)
    attempt = acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    return attempt, acquirer, pages, details, transport


def test_one_open_draft_claim_acquires_draft_pr_with_bound_revisions() -> None:
    items = [pr_item(20, draft=True, body=closes()), pr_item(21, body=closes(4000))]
    attempt, acquirer, _, details, _ = acquire(items)
    result = attempt.result
    assert result is not None
    assert result.outcome is LifecycleAcquisitionOutcome.ACQUIRED
    assert result.lifecycle_stage is LifecycleStage.DRAFT_PR
    assert result.verified_claims == (20,)
    assert result.source_revision == MAIN_SHA
    assert result.issue_source_revision.startswith("github-issue-v1:")
    assert details.calls == [20]  # only the pull request that references the issue is re-read
    (observation,) = acquirer.observations
    assert observation["lifecycle_stage"] == "draft-pr"
    assert observation["lineage"]["claims"] == [20]


def test_open_ready_claim_is_review() -> None:
    attempt, *_ = acquire([pr_item(20, body=closes())])
    assert attempt.result.lifecycle_stage is LifecycleStage.REVIEW


def test_merged_claim_with_issue_still_open_is_merged() -> None:
    attempt, *_ = acquire([pr_item(20, state="closed", merged=True, body=closes())])
    assert attempt.result.lifecycle_stage is LifecycleStage.MERGED


def test_sole_closed_unmerged_claim_is_manual_review() -> None:
    attempt, *_ = acquire([pr_item(20, state="closed", body=closes())])
    assert attempt.result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert attempt.result.reason_codes == ("lifecycle-acquisition.closed-unmerged-pr",)


def test_no_claim_is_unavailable_never_a_defaulted_stage() -> None:
    attempt, *_ = acquire([pr_item(20, body=closes(4000))])
    assert attempt.result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert attempt.result.reason_codes == ("lifecycle-acquisition.no-verified-pr-lineage",)
    assert attempt.result.lifecycle_stage is None


def test_two_claims_conflict() -> None:
    attempt, *_ = acquire([pr_item(20, body=closes()), pr_item(21, body=closes())])
    assert attempt.result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert attempt.result.reason_codes == ("lifecycle-acquisition.conflicting-pr-claims",)
    assert attempt.result.verified_claims == (20, 21)


def test_claim_plus_ambiguous_reference_is_manual_review_not_a_unique_primary() -> None:
    items = [pr_item(20, body=closes()), pr_item(21, body=f"Refs #{ISSUE}")]
    attempt, *_ = acquire(items)
    assert attempt.result.outcome is LifecycleAcquisitionOutcome.MANUAL_REVIEW
    assert attempt.result.reason_codes == ("lifecycle-acquisition.pr-linkage-unverifiable",)


def test_only_declared_non_closing_reference_is_unavailable_and_recorded() -> None:
    body = f"Part of #{ISSUE}\n\nNon-closing: #{ISSUE}\n"
    attempt, acquirer, *_ = acquire([pr_item(20, body=body)])
    assert attempt.result.reason_codes == ("lifecycle-acquisition.no-verified-pr-lineage",)
    (observation,) = acquirer.observations
    assert observation["lineage"]["declared_non_closing_references"] == [20]
    assert observation["lineage"]["claims"] == []


def test_closed_issue_is_closed_without_consulting_lineage() -> None:
    transport = FakeIssueTransport(item=issue_item(state="closed"))
    attempt, acquirer, pages, details, _ = acquire([pr_item(20, body=closes())], issue=transport)
    assert attempt.result.lifecycle_stage is LifecycleStage.CLOSED
    assert pages.calls == [] and details.calls == []
    assert acquirer.population_summary is None
    lineage = acquirer.observations[0]["lineage"]
    assert lineage["lineage_consulted"] is False
    assert lineage["enumeration_complete"] is False


def test_population_is_enumerated_once_for_the_whole_run() -> None:
    items = [pr_item(n, body=closes(n + 1000)) for n in range(1, 6)]
    acquirer, pages, _, _ = make_acquirer(items, per_page=2)
    for issue in (1001, 1002, 1003, 4000):
        acquirer.acquire_lifecycle_stage(REPO, issue)
    assert pages.calls == [1, 2, 3]  # one enumeration, not one per candidate
    assert len(acquirer.observations) == 4
    assert acquirer.population_summary["pull_request_count"] == 5


def test_incomplete_population_fails_closed_for_every_candidate() -> None:
    items = [pr_item(n, body=closes()) for n in range(1, 6)]
    attempt, acquirer, pages, _, _ = acquire(items, per_page=2, max_pages=2)
    assert attempt.result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert attempt.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)
    assert pages.calls == [1, 2]
    assert acquirer.population_summary["complete"] is False
    assert acquirer.population_summary["reason_codes"] == [REASON_PAGE_BOUND_EXHAUSTED]
    # The incomplete state is remembered; it is not silently retried per candidate.
    acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    assert pages.calls == [1, 2]


def test_default_branch_moved_since_population_read_fails_closed() -> None:
    items = [pr_item(20, body=closes())]
    main = MainSha(MAIN_SHA, MAIN_SHA, OTHER_MAIN_SHA)  # read, post-listing check, 2nd issue
    acquirer, *_ = make_acquirer(items, main=main)
    first = acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    assert first.result.lifecycle_stage is LifecycleStage.REVIEW
    second = acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    assert second.result.outcome is LifecycleAcquisitionOutcome.UNAVAILABLE
    assert second.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)
    assert second.result.source_revision == OTHER_MAIN_SHA
    assert acquirer.observations[1]["lineage"]["stale_reason"] == REASON_DEFAULT_BRANCH_MOVED


def test_default_branch_moving_while_the_population_is_read_makes_it_incomplete() -> None:
    main = MainSha(MAIN_SHA, OTHER_MAIN_SHA)
    attempt, acquirer, *_ = acquire([pr_item(20, body=closes())], main=main)
    assert attempt.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)
    assert acquirer.population_summary["reason_codes"] == [REASON_DEFAULT_BRANCH_MOVED]


@pytest.mark.parametrize(
    "outcome",
    [
        PullRequestDetailOutcome.NOT_FOUND,
        PullRequestDetailOutcome.PERMISSION_DENIED,
        PullRequestDetailOutcome.API_ERROR,
        PullRequestDetailOutcome.MALFORMED_RESPONSE,
    ],
)
def test_detail_read_failure_is_incomplete(outcome) -> None:
    items = [pr_item(20, body=closes())]
    details = FakeDetailReader(items, overrides={20: PullRequestDetailResult(outcome)})
    attempt, *_ = acquire(items, details=details)
    assert attempt.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)


def test_detail_failure_note_names_the_cause() -> None:
    items = [pr_item(20, body=closes())]
    details = FakeDetailReader(
        items, overrides={20: PullRequestDetailResult(PullRequestDetailOutcome.NOT_FOUND)}
    )
    acquirer, *_ = make_acquirer(items, details=details)
    acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    observation = acquirer.observations[0]
    assert observation["outcome"] == "unavailable"
    assert observation["lineage"]["enumeration_complete"] is False
    assert REASON_DETAIL_READ_FAILED in observation["lineage"]["enumeration_note"]
    assert "#20 not-found" in observation["lineage"]["enumeration_note"]


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (lambda d: d["head"].update(sha=head(777)), "head moved"),
        (lambda d: d.update(state="closed"), "state moved"),
        (lambda d: d.update(draft=True), "draft toggled"),
        (lambda d: d.update(merged_at="2026-10-13T00:00:00Z", state="closed"), "merged since listing"),
        (lambda d: d.update(body=closes() + "edited"), "body edited"),
        (lambda d: d.update(title="renamed"), "title edited"),
    ],
)
def test_list_detail_disagreement_is_incomplete(mutate, label) -> None:
    listed = pr_item(20, body=closes())
    detail = copy.deepcopy(listed)
    mutate(detail)
    details = FakeDetailReader([listed], overrides={
        20: PullRequestDetailResult(PullRequestDetailOutcome.OK, detail)
    })
    attempt, *_ = acquire([listed], details=details)
    assert attempt.result.reason_codes == (
        "lifecycle-acquisition.incomplete-enumeration",
    ), label


def test_disagreement_reason_is_named_in_the_enumeration_note() -> None:
    listed = pr_item(20, body=closes())
    detail = copy.deepcopy(listed)
    detail["head"]["sha"] = head(777)
    details = FakeDetailReader([listed], overrides={
        20: PullRequestDetailResult(PullRequestDetailOutcome.OK, detail)
    })
    _, acquirer, *_ = acquire([listed], details=details)
    note = acquirer.observations[0]["lineage"]["enumeration_note"]
    assert REASON_LIST_DETAIL_DISAGREEMENT in note and "#20" in note


def test_detail_record_that_is_malformed_is_incomplete() -> None:
    listed = pr_item(20, body=closes())
    broken = copy.deepcopy(listed)
    broken["head"] = {"sha": "nope", "ref": "x"}
    details = FakeDetailReader([listed], overrides={
        20: PullRequestDetailResult(PullRequestDetailOutcome.OK, broken)
    })
    attempt, *_ = acquire([listed], details=details)
    assert attempt.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)


def test_more_references_than_the_evaluator_accepts_fails_closed() -> None:
    items = [pr_item(n, body=f"Refs #{ISSUE}") for n in range(1, MAX_PRIMARY_CLAIMS + 2)]
    attempt, acquirer, _, details, _ = acquire(items)
    assert attempt.result.reason_codes == ("lifecycle-acquisition.incomplete-enumeration",)
    assert details.calls == []  # bounded: no detail reads past the evaluator's bound
    assert acquirer.observations[0]["lineage"]["ambiguous_references"] == list(
        range(1, MAX_PRIMARY_CLAIMS + 2)
    )
    assert REASON_CLAIMS_EXCEED_BOUND in acquirer.observations[0]["lineage"]["enumeration_note"]


def test_exactly_the_evaluator_bound_of_references_is_still_evaluated() -> None:
    items = [pr_item(n, body=f"Refs #{ISSUE}") for n in range(1, MAX_PRIMARY_CLAIMS + 1)]
    attempt, *_ = acquire(items)
    assert attempt.result.reason_codes == ("lifecycle-acquisition.pr-linkage-unverifiable",)


@pytest.mark.parametrize(
    "outcome",
    [
        SingleIssueTransportOutcome.NOT_FOUND,
        SingleIssueTransportOutcome.PERMISSION_DENIED,
        SingleIssueTransportOutcome.API_ERROR,
        SingleIssueTransportOutcome.MALFORMED_RESPONSE,
    ],
)
def test_issue_read_failure_yields_a_named_failure_not_a_result(outcome) -> None:
    attempt, acquirer, pages, *_ = acquire(
        [pr_item(20, body=closes())], issue=FakeIssueTransport(outcome=outcome)
    )
    assert attempt.result is None
    assert attempt.failure_reason == REASON_ISSUE_READ_FAILED
    assert outcome.value in attempt.failure_detail
    assert pages.calls == []
    assert acquirer.observations[0]["outcome"] == "not-acquired"


def test_unsupported_issue_state_is_a_named_failure() -> None:
    item = issue_item()
    item["state"] = "weird"
    attempt, *_ = acquire([], issue=FakeIssueTransport(item=item))
    assert attempt.failure_reason == REASON_ISSUE_STATE_UNSUPPORTED


def test_repository_mismatch_is_a_named_failure_without_any_read() -> None:
    acquirer, pages, _, transport = make_acquirer([])
    attempt = acquirer.acquire_lifecycle_stage("other/repo", ISSUE)
    assert attempt.failure_reason == REASON_REPOSITORY_MISMATCH
    assert transport.calls == 0 and pages.calls == []


def test_repository_comparison_for_the_acquirer_is_case_insensitive() -> None:
    acquirer, *_ = make_acquirer([])
    attempt = acquirer.acquire_lifecycle_stage(REPO.upper(), ISSUE)
    assert attempt.failure_reason != REASON_REPOSITORY_MISMATCH


def test_invalid_issue_number_is_a_programming_error() -> None:
    acquirer, *_ = make_acquirer([])
    with pytest.raises(TypeError):
        acquirer.acquire_lifecycle_stage(REPO, 0)


@pytest.mark.parametrize(
    "main",
    [MainSha(RuntimeError("down")), MainSha("not-a-sha")],
    ids=["unreadable", "malformed"],
)
def test_default_branch_read_failure_is_a_named_failure(main) -> None:
    attempt, _, pages, *_ = acquire([], main=main)
    assert attempt.failure_reason == REASON_DEFAULT_BRANCH_UNREADABLE
    assert pages.calls == []


def test_observations_are_ordered_json_ready_and_carry_no_authority() -> None:
    acquirer, *_ = make_acquirer([pr_item(20, body=closes())])
    acquirer.acquire_lifecycle_stage(REPO, ISSUE)
    acquirer.acquire_lifecycle_stage(REPO, 4000)
    records = acquirer.observations
    assert [record["issue_number"] for record in records] == [ISSUE, 4000]
    json.dumps(records)
    forbidden = {"execution_authorized", "merge_authorized", "github_writes_authorized"}
    assert forbidden.isdisjoint(records[0])


def test_acquirer_construction_is_validated() -> None:
    good = dict(
        repository=REPO, issue_transport=FakeIssueTransport(), page_reader=FakePageReader([]),
        detail_reader=FakeDetailReader([]), source_revision_reader=MainSha(MAIN_SHA),
        observed_at=OBSERVED_AT,
    )
    PrLineageAcquirer(**good)
    for bad in (
        {"repository": "nope"},
        {"observed_at": "today"},
        {"page_reader": None},
        {"source_revision_reader": "not-callable"},
        {"per_page": 0},
        {"max_pages": 0},
    ):
        with pytest.raises((TypeError, ValueError)):
            PrLineageAcquirer(**{**good, **bad})


# ---------------------------------------------------------------------------
# Negative controls: no parallel client, parser, selector, or write surface
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(reader_module.__file__)


def test_module_is_pure_over_injected_ports() -> None:
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"urllib", "requests", "http", "socket", "subprocess", "httpx", "github",
                 "os", "pathlib", "shutil"}
    assert imported.isdisjoint(forbidden), sorted(imported & forbidden)


def test_module_defines_no_parallel_parser_selector_or_write_surface() -> None:
    names = {
        node.name
        for node in ast.walk(ast.parse(_MODULE_PATH.read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    for forbidden in ("parse_linked_issue", "select_issue", "post", "put", "patch", "delete",
                      "create_comment", "merge", "close_issue"):
        assert forbidden not in names
    assert not [n for n in names if n.startswith(("write", "create", "update", "delete"))]
