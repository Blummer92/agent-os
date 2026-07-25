from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .draft import IssueDraftInput, build_issue_draft
from .issue_create import (
    ConfirmationProvider,
    GitHubRepositoryTarget,
    IssueCreateCommandPlan,
    IssueCreateConfirmation,
    IssueCreateExitCode,
    IssueCreateRequest,
    SubprocessGhRunner,
    execute_issue_creation,
    issue_create_result_to_dict,
    render_issue_create_result,
)
from .validation import DraftExitCode, validate_issue_draft


class _UsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


class _NoConfirmation:
    def confirm(self, plan: IssueCreateCommandPlan) -> None:
        return None


class _PromptConfirmation:
    def confirm(self, plan: IssueCreateCommandPlan) -> IssueCreateConfirmation | None:
        print(f"Target: {plan.target.canonical}", file=sys.stderr)
        print(f"Operation identity: {plan.operation_identity}", file=sys.stderr)
        print(f"Title: sha256={_digest_from_plan(plan, '--title=')}", file=sys.stderr)
        print(f"Body: sha256={plan.body_digest} bytes={plan.body_bytes}", file=sys.stderr)
        print(
            f"Labels: count={sum(value.startswith('--label=') for value in plan.argv)}",
            file=sys.stderr,
        )
        print(f"Warnings: {', '.join(plan.warning_reason_codes) or 'none'}", file=sys.stderr)
        print(f"Confirmation fingerprint: {plan.operation_fingerprint}", file=sys.stderr)
        expected = f"create {plan.operation_fingerprint}"
        try:
            entered = input(f"Type exactly '{expected}' to authorize this one invocation: ")
        except (EOFError, KeyboardInterrupt):
            return IssueCreateConfirmation(
                invocation_id="",
                operation_fingerprint=plan.operation_fingerprint,
                target=plan.target.canonical,
                confirmed=False,
            )
        return IssueCreateConfirmation(
            invocation_id="__FROM_CLI__",
            operation_fingerprint=plan.operation_fingerprint,
            target=plan.target.canonical,
            confirmed=entered == expected,
            accepted_warning_reason_codes=(
                plan.warning_reason_codes if entered == expected else ()
            ),
        )


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description="Plan or explicitly confirm one fail-closed GitHub issue creation."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Structured JSON draft path, or - for stdin.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="OWNER/REPO or HOST/OWNER/REPO.",
    )
    parser.add_argument(
        "--issue-form",
        default=".github/ISSUE_TEMPLATE/agent-os-task.yml",
    )
    parser.add_argument(
        "--label-map",
        default=".github/labeler/agent-os-issue-label-map.yml",
    )
    parser.add_argument("--available-label", action="append", default=None)
    parser.add_argument("--candidate-summary", action="append", default=[])
    parser.add_argument(
        "--prior-fingerprint",
        action="append",
        default=[],
        help="Previously attempted stable operation identity; repeat as needed.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Prompt for one fresh exact confirmation.",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        payload = json.loads(_read(args.input))
        if not isinstance(payload, dict):
            raise ValueError("structured draft input must be a JSON object")
        target = GitHubRepositoryTarget.parse(args.target)
    except (_UsageError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"issue-create input error: {exc}", file=sys.stderr)
        return int(DraftExitCode.INVALID_INPUT_OR_USAGE)

    try:
        source = IssueDraftInput.from_mapping(payload)
        draft = build_issue_draft(source, args.issue_form, args.label_map)
        validation = validate_issue_draft(
            draft,
            source,
            args.issue_form,
            available_labels=args.available_label,
            local_issue_summaries=tuple(args.candidate_summary),
        )
        invocation_id = uuid.uuid4().hex
        request = IssueCreateRequest(
            validation=validation,
            target=target,
            invocation_id=invocation_id,
            prior_fingerprints=tuple(args.prior_fingerprint),
        )
        provider: ConfirmationProvider
        if args.execute:
            prompt = _PromptConfirmation()

            class _BoundPrompt:
                def confirm(
                    self,
                    plan: IssueCreateCommandPlan,
                ) -> IssueCreateConfirmation | None:
                    value = prompt.confirm(plan)
                    if value is None:
                        return None
                    return IssueCreateConfirmation(
                        invocation_id=invocation_id,
                        operation_fingerprint=value.operation_fingerprint,
                        target=value.target,
                        confirmed=value.confirmed,
                        accepted_warning_reason_codes=(
                            value.accepted_warning_reason_codes
                        ),
                    )

            provider = _BoundPrompt()
        else:
            provider = _NoConfirmation()
        result = execute_issue_creation(request, SubprocessGhRunner(), provider)
    except (OSError, ValueError) as exc:
        print(f"issue-create planning error: {exc}", file=sys.stderr)
        return int(IssueCreateExitCode.AUTHORIZATION)

    if args.format == "json":
        print(
            json.dumps(
                issue_create_result_to_dict(result),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        print(render_issue_create_result(result), end="")
    return result.exit_code


def _digest_from_plan(plan: IssueCreateCommandPlan, prefix: str) -> str:
    import hashlib

    value = next(item[len(prefix) :] for item in plan.argv if item.startswith(prefix))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
