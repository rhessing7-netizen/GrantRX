"""Retry EmailOctopus sync for waitlist leads that never reached the provider.

    python -m scripts.sync_waitlist_leads [--dry-run] [--limit=N]

The EdFintia database is the source of truth: leads are committed before any
provider sync is attempted, so a provider outage can never lose a signup —
it only leaves provider_sync_status in pending | failed | skipped. This sweep
re-attempts the sync for exactly those leads.

Safe to re-run: the EmailOctopus adapter upserts by MD5-keyed contact PUT, so
repeating the sync never creates duplicate contacts or re-enrolls a contact
that is already subscribed — it converges provider state to the durable lead.

Leaves 'synced' leads untouched: a synced lead is never re-PUT by this sweep,
so it cannot restart or re-enroll a contact in the provider's automation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models.models import WaitlistLead
from app.services.email_marketing import (
    get_email_marketing_provider,
    waitlist_tags_for_audience,
)

RETRYABLE_STATUSES = ("pending", "failed", "skipped")


def sync_retryable(dry_run: bool = False, limit: int = 500) -> dict:
    provider = get_email_marketing_provider()
    db = SessionLocal()
    try:
        leads = (
            db.query(WaitlistLead)
            .filter(WaitlistLead.provider_sync_status.in_(RETRYABLE_STATUSES))
            .order_by(WaitlistLead.created_at)
            .limit(limit)
            .all()
        )
        summary = {
            "dry_run": dry_run,
            "provider_configured": provider is not None,
            "candidates": len(leads),
            "synced": 0,
            "failed": 0,
            "unchanged": 0,
        }
        if dry_run or provider is None:
            summary["unchanged"] = len(leads)
            return summary

        for lead in leads:
            result = provider.subscribe_or_update(
                email=lead.email,
                first_name=lead.first_name,
                tags=waitlist_tags_for_audience(lead.audience_type),
            )
            if result.status == "synced":
                lead.provider_sync_status = "synced"
                lead.provider_synced_at = datetime.now(timezone.utc)
                lead.provider_last_error = None
                summary["synced"] += 1
            elif result.status == "failed":
                lead.provider_sync_status = "failed"
                lead.provider_last_error = result.error
                summary["failed"] += 1
            else:
                summary["unchanged"] += 1
        db.commit()
        return summary
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)
    print(json.dumps(sync_retryable(dry_run=args.dry_run, limit=args.limit), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
