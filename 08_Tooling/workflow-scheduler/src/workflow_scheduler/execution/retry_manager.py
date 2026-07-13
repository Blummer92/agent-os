"""Retry backoff and eligibility computation for transient task failures."""

from datetime import datetime
from typing import Optional

from workflow_scheduler.models import Task


class RetryManager:
    """Computes exponential backoff delays and retry eligibility."""

    DEFAULT_BASE_DELAY_SECONDS = 5.0
    DEFAULT_MULTIPLIER = 2.0
    DEFAULT_MAX_DELAY_SECONDS = 300.0

    @staticmethod
    def compute_delay(
        retry_count: int,
        base_delay_seconds: float = 5.0,
        multiplier: float = 2.0,
        max_delay_seconds: float = 300.0,
    ) -> float:
        """Compute the exponential backoff delay for the given retry attempt.

        Args:
            retry_count: Number of retries already attempted (0-indexed)
            base_delay_seconds: Delay before the first retry
            multiplier: Growth factor applied per retry
            max_delay_seconds: Upper bound on the computed delay

        Returns:
            Delay in seconds before the next retry attempt
        """
        delay = base_delay_seconds * (multiplier ** retry_count)
        return min(delay, max_delay_seconds)

    @staticmethod
    def should_retry(task: Task) -> bool:
        """Check whether a task still has retry budget remaining.

        Args:
            task: Task to check

        Returns:
            True if task.retry_count is below task.max_retries
        """
        return task.retry_count < task.max_retries

    @staticmethod
    def is_due(task: Task, now: Optional[datetime] = None) -> bool:
        """Check whether a retry-scheduled task's backoff window has elapsed.

        Args:
            task: Task to check
            now: Reference time (defaults to current UTC time)

        Returns:
            True if the task has no scheduled retry time, or that time has passed
        """
        if task.next_retry_at is None:
            return True
        now = now or datetime.utcnow()
        return task.next_retry_at <= now
