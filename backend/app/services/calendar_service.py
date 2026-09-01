"""Calendar event aggregation and .ICS feed generation.

Builds iCalendar feeds with VALARM triggers 7 days and 1 day before each
scholarship deadline. Compatible with Apple Calendar, Google Calendar, and
Outlook subscription URLs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List
from uuid import UUID

from icalendar import Alarm, Calendar, Event, vText
from sqlalchemy.orm import Session, joinedload

from ..models.models import Profile, UserScholarship

logger = logging.getLogger(__name__)

# Only include scholarships the user is actively tracking (not archived/awarded)
TRACKING_STATUSES = ("saved", "in_progress", "submitted")


def get_calendar_events(db: Session, user_id: UUID) -> List[dict]:
    """Return a list of calendar event dicts for the authenticated user."""
    rows = (
        db.query(UserScholarship)
        .options(joinedload(UserScholarship.scholarship))
        .filter(
            UserScholarship.user_id == user_id,
            UserScholarship.status.in_(TRACKING_STATUSES),
        )
        .all()
    )

    events: List[dict] = []
    for row in rows:
        s = row.scholarship
        if not s:
            continue
        events.append(
            {
                "tracking_id": str(row.id),
                "scholarship_id": str(s.id),
                "title": s.title,
                "provider": s.provider,
                "deadline": s.deadline.isoformat() if s.deadline else None,
                "status": row.status,
                "award_amount": s.award_amount,
                "custom_deadline_reminder": (
                    row.custom_deadline_reminder.isoformat()
                    if row.custom_deadline_reminder
                    else None
                ),
                "user_notes": row.user_notes,
            }
        )
    return events


def _deadline_to_datetime(deadline: date) -> datetime:
    """Convert a date to an all-day-style datetime at 23:59 UTC."""
    return datetime(deadline.year, deadline.month, deadline.day, 23, 59, 0, tzinfo=timezone.utc)


def generate_ics_feed(db: Session, feed_token: str) -> str:
    """Generate a full .ics feed string for a user identified by feed_token.

    Returns an empty calendar (with proper headers) if the token is invalid.
    """
    profile = db.query(Profile).filter(Profile.feed_token == feed_token).first()
    if not profile:
        # Return a minimal valid calendar so clients don't error
        cal = Calendar()
        cal.add("prodid", "-//GrantRx//Calendar//EN")
        cal.add("version", "2.0")
        return cal.to_ical().decode("utf-8")

    events_data = get_calendar_events(db, profile.id)

    cal = Calendar()
    cal.add("prodid", "-//GrantRx//Scholarship Deadlines//EN")
    cal.add("version", "2.0")
    cal.add("name", vText("GrantRx Scholarship Deadlines"))
    cal.add("x-wr-calname", "GrantRx Scholarships")
    cal.add("x-wr-timezone", "UTC")

    for ev_data in events_data:
        if not ev_data["deadline"]:
            continue

        try:
            deadline_date = date.fromisoformat(ev_data["deadline"])
        except (ValueError, TypeError):
            continue

        dtstart = _deadline_to_datetime(deadline_date)
        dtend = dtstart + timedelta(hours=1)

        event = Event()
        event.add("uid", f"grantrx-{ev_data['tracking_id']}@grantrx.app")
        event.add("summary", f"{ev_data['title']} — Deadline")
        description_parts = [
            f"Provider: {ev_data['provider']}",
            f"Award: ${ev_data['award_amount']:,}",
            f"Status: {ev_data['status']}",
        ]
        if ev_data["user_notes"]:
            description_parts.append(f"Notes: {ev_data['user_notes']}")
        event.add("description", "\n".join(description_parts))
        event.add("dtstart", dtstart)
        event.add("dtend", dtend)
        event.add("status", "CONFIRMED")

        # Alarm 1: 7 days before
        alarm_7d = Alarm()
        alarm_7d.add("action", "DISPLAY")
        alarm_7d.add("description", f"7 days left: {ev_data['title']} deadline")
        alarm_7d.add("trigger", timedelta(days=-7))
        event.add_component(alarm_7d)

        # Alarm 2: 1 day before
        alarm_1d = Alarm()
        alarm_1d.add("action", "DISPLAY")
        alarm_1d.add("description", f"1 day left: {ev_data['title']} deadline")
        alarm_1d.add("trigger", timedelta(days=-1))
        event.add_component(alarm_1d)

        # Custom reminder alarm if set
        if ev_data["custom_deadline_reminder"]:
            try:
                custom_dt = datetime.fromisoformat(ev_data["custom_deadline_reminder"])
                if custom_dt.tzinfo is None:
                    custom_dt = custom_dt.replace(tzinfo=timezone.utc)
                # Trigger relative to the custom datetime (fire at that exact time)
                alarm_custom = Alarm()
                alarm_custom.add("action", "DISPLAY")
                alarm_custom.add("description", f"Reminder: {ev_data['title']}")
                # Use absolute trigger
                alarm_custom.add("trigger", custom_dt)
                event.add_component(alarm_custom)
            except (ValueError, TypeError):
                pass

        cal.add_component(event)

    return cal.to_ical().decode("utf-8")
