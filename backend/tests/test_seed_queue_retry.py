"""Regression tests for crawler seed retry/backoff policy."""
from datetime import timedelta

from scrapers.seed_queue import (
    MAX_FAILURES_BEFORE_QUARANTINE,
    RETRY_BACKOFF,
    _retry_delay,
)


def test_retry_backoff_grows_and_is_bounded():
    assert _retry_delay(1) == timedelta(hours=1)
    assert _retry_delay(2) == timedelta(hours=6)
    assert _retry_delay(3) == timedelta(hours=24)
    assert _retry_delay(4) == timedelta(hours=72)
    assert _retry_delay(99) == timedelta(hours=72)


def test_quarantine_threshold_allows_multiple_transient_retries():
    assert MAX_FAILURES_BEFORE_QUARANTINE == 5
    assert len(RETRY_BACKOFF) == MAX_FAILURES_BEFORE_QUARANTINE - 1
