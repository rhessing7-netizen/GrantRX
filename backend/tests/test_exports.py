"""Unit tests for the Calendar & Asana Multi-Export Engine.

Tests verify:
- Google Calendar URL encoding (special chars, date format, action=TEMPLATE)
- Asana CSV: RFC 4180 headers, comma/quote escaping, date formatting
- ICS feed: RFC 5545 structure, VEVENT properties, VALARM 7-day reminder
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app.services.export_service import (
    generate_asana_csv,
    generate_gcal_url,
    generate_ics_feed,
)


# ---------------------------------------------------------------------------
# Tests: Google Calendar URL
# ---------------------------------------------------------------------------


class TestGcalUrl:
    def test_basic_url_structure(self):
        url = generate_gcal_url(
            scholarship_title="Tylenol Scholarship",
            deadline=date(2026, 3, 15),
            portal_url="https://example.com/apply",
            provider="Tylenol",
        )
        assert url.startswith("https://calendar.google.com/render?action=TEMPLATE")
        assert "text=" in url
        assert "dates=" in url
        assert "details=" in url
        assert "add=" in url

    def test_date_format_all_day(self):
        url = generate_gcal_url(
            scholarship_title="Test",
            deadline=date(2026, 3, 15),
            portal_url="https://example.com",
            provider="Provider",
        )
        # All-day events use YYYYMMDD/YYYYMMDD (next day)
        assert "dates=20260315/20260316" in url

    def test_special_characters_encoded(self):
        url = generate_gcal_url(
            scholarship_title="A & B Scholarship, Inc.",
            deadline=date(2026, 1, 1),
            portal_url="https://example.com/apply?x=1&y=2",
            provider="A&B Corp",
        )
        # Commas, ampersands, and spaces must be URL-encoded
        assert "A & B" not in url
        assert "%26" in url  # & encoded
        assert "%2C" in url  # , encoded

    def test_action_template_present(self):
        url = generate_gcal_url(
            scholarship_title="Test",
            deadline=date(2026, 6, 1),
            portal_url="https://example.com",
            provider="Test",
        )
        assert "action=TEMPLATE" in url

    def test_title_in_url(self):
        url = generate_gcal_url(
            scholarship_title="Nursing Excellence Award",
            deadline=date(2026, 6, 1),
            portal_url="https://example.com",
            provider="ANA",
        )
        # Title should appear encoded
        assert "Nursing" in url or "Nursing%20" in url


# ---------------------------------------------------------------------------
# Tests: Asana CSV
# ---------------------------------------------------------------------------


class TestAsanaCsv:
    def test_csv_headers_correct(self):
        csv_str = generate_asana_csv([])
        reader = csv.reader(io.StringIO(csv_str))
        headers = next(reader)
        assert headers == [
            "Task Name",
            "Due Date",
            "Description",
            "Notes",
            "Section/Column",
            "Tags",
        ]

    def test_single_row_content(self):
        items = [
            {
                "title": "Pharmacy Scholarship",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com/apply",
                "provider": "APhA",
                "award_amount": 5000,
                "status": "planned",
            }
        ]
        csv_str = generate_asana_csv(items)
        reader = csv.reader(io.StringIO(csv_str))
        next(reader)  # skip header
        row = next(reader)
        assert row[0] == "Pharmacy Scholarship"
        assert row[1] == "03/15/2026"
        assert "example.com" in row[2]
        assert "APhA" in row[3]
        assert "$5,000" in row[3]
        assert row[4] == "Planned"
        assert "GrantRx" in row[5]

    def test_comma_escaping(self):
        items = [
            {
                "title": "Award, Excellence & Merit",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "Provider, Inc.",
                "award_amount": 1000,
                "status": "saved",
            }
        ]
        csv_str = generate_asana_csv(items)
        # Parse with csv reader to verify proper quoting
        reader = csv.reader(io.StringIO(csv_str))
        next(reader)
        row = next(reader)
        assert row[0] == "Award, Excellence & Merit"
        assert "Provider, Inc." in row[3]

    def test_multiple_rows(self):
        items = [
            {
                "title": f"Scholarship {i}",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "Provider",
                "award_amount": 1000 * i,
                "status": "planned",
            }
            for i in range(3)
        ]
        csv_str = generate_asana_csv(items)
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 4  # header + 3 data rows
        assert rows[1][0] == "Scholarship 0"
        assert rows[3][0] == "Scholarship 2"

    def test_empty_items_only_headers(self):
        csv_str = generate_asana_csv([])
        reader = csv.reader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 1  # only header

    def test_rfc4180_line_endings(self):
        csv_str = generate_asana_csv([])
        assert "\r\n" in csv_str


# ---------------------------------------------------------------------------
# Tests: ICS Feed
# ---------------------------------------------------------------------------


class TestIcsFeed:
    def test_ics_structure(self):
        ics = generate_ics_feed([
            {
                "title": "Test Scholarship",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "Provider",
                "award_amount": 5000,
            }
        ])
        assert "BEGIN:VCALENDAR" in ics
        assert "END:VCALENDAR" in ics
        assert "VERSION:2.0" in ics
        assert "PRODID" in ics

    def test_vevent_present(self):
        ics = generate_ics_feed([
            {
                "title": "Test Scholarship",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "Provider",
                "award_amount": 5000,
            }
        ])
        assert "BEGIN:VEVENT" in ics
        assert "END:VEVENT" in ics
        assert "SUMMARY:Test Scholarship" in ics

    def test_valarm_7_day_reminder(self):
        ics = generate_ics_feed([
            {
                "title": "Test Scholarship",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "Provider",
                "award_amount": 5000,
            }
        ])
        assert "BEGIN:VALARM" in ics
        assert "END:VALARM" in ics
        assert "TRIGGER:-P7D" in ics
        assert "ACTION:DISPLAY" in ics

    def test_dtstart_all_day(self):
        ics = generate_ics_feed([
            {
                "title": "Test",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            }
        ])
        assert "DTSTART;VALUE=DATE:20260315" in ics
        assert "DTEND;VALUE=DATE:20260316" in ics

    def test_url_property(self):
        ics = generate_ics_feed([
            {
                "title": "Test",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com/apply",
                "provider": "P",
                "award_amount": 1000,
            }
        ])
        assert "URL:https://example.com/apply" in ics

    def test_multiple_events(self):
        items = [
            {
                "title": f"Scholarship {i}",
                "deadline": f"2026-0{i+1}-15",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            }
            for i in range(3)
        ]
        ics = generate_ics_feed(items)
        assert ics.count("BEGIN:VEVENT") == 3
        assert ics.count("END:VEVENT") == 3
        assert ics.count("BEGIN:VALARM") == 3

    def test_skips_items_without_deadline(self):
        ics = generate_ics_feed([
            {
                "title": "No Deadline",
                "deadline": "",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            },
            {
                "title": "Has Deadline",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            },
        ])
        assert ics.count("BEGIN:VEVENT") == 1
        assert "Has Deadline" in ics
        assert "No Deadline" not in ics

    def test_empty_items_only_calendar_wrapper(self):
        ics = generate_ics_feed([])
        assert "BEGIN:VCALENDAR" in ics
        assert "END:VCALENDAR" in ics
        assert "BEGIN:VEVENT" not in ics

    def test_comma_escaping_in_summary(self):
        ics = generate_ics_feed([
            {
                "title": "Award, Excellence & Merit",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            }
        ])
        # Commas in SUMMARY must be escaped per RFC 5545
        assert "SUMMARY:Award\\, Excellence & Merit" in ics

    def test_rfc5545_line_endings(self):
        ics = generate_ics_feed([
            {
                "title": "Test",
                "deadline": "2026-03-15",
                "portal_url": "https://example.com",
                "provider": "P",
                "award_amount": 1000,
            }
        ])
        assert "\r\n" in ics
