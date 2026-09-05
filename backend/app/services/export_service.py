"""Calendar & Asana Multi-Export Engine.

Provides utilities to generate:
- Google Calendar web intent URLs for individual scholarships
- Asana-compatible CSV files for bulk task import
- RFC 5545 .ics calendar feeds with VALARM reminders
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import List
from urllib.parse import quote


def generate_gcal_url(
    scholarship_title: str,
    deadline: date,
    portal_url: str,
    provider: str,
) -> str:
    """Generate a Google Calendar 'Add Event' web intent URL.

    Uses the https://calendar.google.com/render?action=TEMPLATE endpoint
    with URL-encoded parameters for title, dates, details, and provider.
    """
    # Google Calendar expects all-day events as YYYYMMDD/YYYYMMDD (next day)
    date_str = deadline.strftime("%Y%m%d")
    end_date = deadline + timedelta(days=1)
    end_str = end_date.strftime("%Y%m%d")

    params = (
        f"?action=TEMPLATE"
        f"&text={quote(scholarship_title)}"
        f"&dates={date_str}/{end_str}"
        f"&details={quote(portal_url)}"
        f"&add={quote(provider)}"
    )
    return f"https://calendar.google.com/render{params}"


def generate_asana_csv(planned_items: List[dict]) -> str:
    """Format planned scholarships into Asana-compatible CSV (RFC 4180).

    Expected dict keys per item: title, deadline, portal_url, provider,
    award_amount, status.

    Returns CSV string with headers:
    Task Name,Due Date,Description,Notes,Section/Column,Tags
    """
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    # Header row
    writer.writerow([
        "Task Name",
        "Due Date",
        "Description",
        "Notes",
        "Section/Column",
        "Tags",
    ])

    for item in planned_items:
        title = item.get("title", "")
        deadline = item.get("deadline", "")
        portal_url = item.get("portal_url", "")
        provider = item.get("provider", "")
        award_amount = item.get("award_amount", 0)
        status = item.get("status", "planned")

        # Format deadline as MM/DD/YYYY for Asana
        due_date = ""
        if deadline:
            try:
                if isinstance(deadline, str):
                    parsed = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
                else:
                    parsed = deadline
                due_date = parsed.strftime("%m/%d/%Y")
            except (ValueError, TypeError):
                due_date = str(deadline)

        notes = f"Provider: {provider}. Award: ${award_amount:,}. Apply at {portal_url}"

        writer.writerow([
            title,
            due_date,
            f"Apply at {portal_url}",
            notes,
            status.capitalize(),
            "GrantRx,Scholarship",
        ])

    return output.getvalue()


def generate_ics_feed(user_scholarships: List[dict]) -> str:
    """Generate an RFC 5545 .ics calendar feed with VALARM reminders.

    Expected dict keys per item: title, deadline, portal_url, provider,
    award_amount.

    Each VEVENT includes:
    - SUMMARY with scholarship title
    - DTSTART/DTEND as all-day events
    - URL property with application link
    - VALARM trigger 7 days before deadline
    """
    lines: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GrantRx//Scholarship Deadline Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for item in user_scholarships:
        title = item.get("title", "Scholarship Deadline")
        deadline = item.get("deadline")
        portal_url = item.get("portal_url", "")
        provider = item.get("provider", "")
        award_amount = item.get("award_amount", 0)

        if not deadline:
            continue

        # Parse deadline
        try:
            if isinstance(deadline, str):
                dl = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
            else:
                dl = deadline
        except (ValueError, TypeError):
            continue

        date_str = dl.strftime("%Y%m%d")
        end_str = (dl + timedelta(days=1)).strftime("%Y%m%d")

        # Escape commas and semicolons in text fields
        def esc(text: str) -> str:
            return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:grantrx-{date_str}-{hash(title) & 0xFFFFFFFF:08x}@grantrx.app",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{date_str}",
            f"DTEND;VALUE=DATE:{end_str}",
            f"SUMMARY:{esc(title)}",
            f"DESCRIPTION:{esc(f'Provider: {provider}. Award: ${award_amount:,}. Apply at {portal_url}')}",
            f"URL:{portal_url}",
            # VALARM: 7-day reminder
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Scholarship deadline in 7 days",
            "TRIGGER:-P7D",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
