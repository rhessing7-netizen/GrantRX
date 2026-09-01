"""Import seed scholarship URLs from CSV into the database.

The CSV (scrapers/data/seed_urls.csv) contains placeholder entries that the
scraper pipeline will later enrich with real data (award amounts, deadlines, etc.).
This script inserts them with sensible defaults so they appear in the feed
immediately and can be updated by future scrape runs.

CSV columns:
    title, category, target_level, state, seed_url, typical_cycle

Mapping to Scholarship model:
    title             -> title
    seed_url          -> portal_url
    target_level      -> eligible_credentials (e.g. ["PharmD"])
    state             -> state_restrictions (["OH"] or [] for "ALL")
    category          -> matching_tags
    typical_cycle     -> matching_tags
    (derived)         -> provider (extracted from title)
    (default)         -> award_amount=0, deadline=2027-12-31, eligible_disciplines=["pharmacy"]
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

# Add the backend directory to Python path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.models import Scholarship

CSV_PATH = Path(__file__).resolve().parents[1] / "scrapers" / "data" / "seed_urls.csv"

# Default placeholder values for seed entries
DEFAULT_DEADLINE = date(2027, 12, 31)
DEFAULT_AWARD = 0

# Map target_level CSV values to clinical_discipline enum values
_DISCIPLINE_MAP = {
    "PharmD": "pharmacy",
    "MD": "medicine",
    "DO": "medicine",
    "BSN": "nursing",
    "DPT": "therapeutics_rehab",
}


def _extract_provider(title: str) -> str:
    """Extract a reasonable provider name from the scholarship title."""
    # Split on common scholarship-related keywords
    for keyword in [
        " Student Scholarships",
        " Student Leadership Awards",
        " Scholarships",
        " Scholarship Program",
        " Scholarship",
        " Awards",
        " Memorial Scholarship Foundation",
        " National Scholarships Program",
    ]:
        if keyword in title:
            provider = title.split(keyword)[0].strip()
            if provider:
                return provider
    return title


def import_seeds():
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} does not exist.")
        return

    db = SessionLocal()
    created = 0
    skipped = 0

    try:
        with open(CSV_PATH, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                portal_url = row["seed_url"].strip()
                title = row["title"].strip()

                # Dedup by portal_url — skip if already exists
                existing = db.query(Scholarship).filter_by(portal_url=portal_url).first()
                if existing:
                    skipped += 1
                    continue

                # Map CSV fields to model columns
                target_level = row.get("target_level", "").strip()
                discipline = _DISCIPLINE_MAP.get(target_level, "pharmacy")
                state_raw = row.get("state", "ALL").strip()
                state_restrictions = [] if state_raw.upper() == "ALL" else [state_raw]

                tags = []
                category = row.get("category", "").strip()
                if category:
                    tags.append(category)
                cycle = row.get("typical_cycle", "").strip()
                if cycle:
                    tags.append(cycle)

                new_entry = Scholarship(
                    title=title,
                    provider=_extract_provider(title),
                    portal_url=portal_url,
                    award_amount=DEFAULT_AWARD,
                    deadline=DEFAULT_DEADLINE,
                    eligible_disciplines=[discipline],
                    eligible_credentials=[target_level] if target_level else [],
                    min_gpa=0.0,
                    state_restrictions=state_restrictions,
                    matching_tags=tags,
                    is_archived=False,
                )
                db.add(new_entry)
                created += 1

        db.commit()
        print(f"Successfully imported {created} new seed scholarship(s).")
        if skipped:
            print(f"Skipped {skipped} existing record(s) (URL already in database).")
    except Exception as e:
        db.rollback()
        print(f"Failed to import seeds: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    import_seeds()
