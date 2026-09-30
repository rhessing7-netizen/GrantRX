"""Tests for scripts.sync_waitlist_leads — the provider retry sweep.

Leads are committed to the EdFintia database before any provider sync, so a
provider outage leaves provider_sync_status in pending | failed | skipped.
The sweep re-attempts only those leads and never touches 'synced' leads, so
it cannot restart or re-enroll a contact in the provider's automation.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.models import WaitlistLead
from app.services.email_marketing import ProviderSyncResult
from scripts import sync_waitlist_leads


class _RetryableQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *criteria):
        rows = []
        for row in self._rows:
            ok = True
            for criterion in criteria:
                left = getattr(criterion.left, "key", None) or getattr(
                    criterion.left, "name", None
                )
                # Only the .in_() status filter is used by the sweep.
                if hasattr(criterion, "right") and hasattr(
                    criterion.right, "value"
                ) and isinstance(criterion.right.value, (list, tuple)):
                    ok = ok and getattr(row, left) in criterion.right.value
                else:
                    ok = ok and getattr(row, left) in criterion.right.value
            if ok:
                rows.append(row)
        self._rows = rows
        return self

    def order_by(self, *_):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def all(self):
        return list(self._rows)


class FakeSyncSession:
    def __init__(self, leads):
        self._leads = list(leads)
        self.commits = 0

    def query(self, model):
        assert model is WaitlistLead
        return _RetryableQuery(self._leads)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _lead(status, email="lead@example.com"):
    lead = WaitlistLead()
    lead.id = uuid4()
    lead.email = email
    lead.first_name = "Lead"
    lead.audience_type = "student"
    lead.education_type = None
    lead.status = "waitlist"
    lead.consent_timestamp = datetime.now(timezone.utc)
    lead.consent_source = "early_access_form"
    lead.provider_sync_status = status
    lead.provider_synced_at = (
        datetime.now(timezone.utc) if status == "synced" else None
    )
    lead.provider_last_error = "boom" if status == "failed" else None
    lead.created_at = datetime.now(timezone.utc)
    lead.updated_at = datetime.now(timezone.utc)
    return lead


def _patch_session(db):
    return patch.object(sync_waitlist_leads, "SessionLocal", return_value=db)


@pytest.fixture(autouse=True)
def _provider_env():
    with patch.dict(
        os.environ,
        {"EMAILOCTOPUS_API_KEY": "k", "EMAILOCTOPUS_LIST_ID": "list-1"},
    ):
        yield


class TestRetrySweep:
    def test_pending_failed_skipped_are_retried(self):
        leads = [_lead("pending"), _lead("failed", "f@x.com"), _lead("skipped", "s@x.com")]
        db = FakeSyncSession(leads)
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(status="synced")

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=provider
        ):
            out = sync_waitlist_leads.sync_retryable()

        assert out["candidates"] == 3
        assert out["synced"] == 3
        assert all(lead.provider_sync_status == "synced" for lead in leads)
        assert all(lead.provider_synced_at is not None for lead in leads)
        assert db.commits == 1

    def test_synced_leads_are_never_retried(self):
        synced = _lead("synced")
        db = FakeSyncSession([synced])
        provider = MagicMock()

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=provider
        ):
            out = sync_waitlist_leads.sync_retryable()

        # A synced lead is not a candidate — no provider call can re-enroll it.
        assert out["candidates"] == 0
        provider.subscribe_or_update.assert_not_called()
        assert synced.provider_sync_status == "synced"

    def test_provider_failure_marks_failed_and_keeps_lead(self):
        lead = _lead("pending")
        db = FakeSyncSession([lead])
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(
            status="failed", error="HTTP 500: upstream down"
        )

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=provider
        ):
            out = sync_waitlist_leads.sync_retryable()

        assert out["failed"] == 1
        assert lead.provider_sync_status == "failed"
        assert lead.provider_last_error == "HTTP 500: upstream down"
        # Lead remains in the retryable set for the next sweep.

    def test_unconfigured_provider_changes_nothing(self):
        leads = [_lead("pending"), _lead("failed", "f@x.com")]
        db = FakeSyncSession(leads)

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=None
        ):
            out = sync_waitlist_leads.sync_retryable()

        assert out["provider_configured"] is False
        assert out["unchanged"] == 2
        assert leads[0].provider_sync_status == "pending"
        assert db.commits == 0

    def test_dry_run_changes_nothing(self):
        leads = [_lead("pending")]
        db = FakeSyncSession(leads)
        provider = MagicMock()

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=provider
        ):
            out = sync_waitlist_leads.sync_retryable(dry_run=True)

        assert out["dry_run"] is True
        assert out["candidates"] == 1
        provider.subscribe_or_update.assert_not_called()
        assert leads[0].provider_sync_status == "pending"
        assert db.commits == 0

    def test_limit_bounds_the_sweep(self):
        leads = [_lead("pending", f"l{i}@x.com") for i in range(5)]
        db = FakeSyncSession(leads)
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(status="synced")

        with _patch_session(db), patch.object(
            sync_waitlist_leads, "get_email_marketing_provider", return_value=provider
        ):
            out = sync_waitlist_leads.sync_retryable(limit=2)

        assert out["candidates"] == 2
        assert out["synced"] == 2
