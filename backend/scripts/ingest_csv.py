"""Import curated CSV URLs into the autonomous crawler seed queue.

Seed URLs are discovery inputs, not verified scholarships.  This script must
never manufacture award amounts, deadlines, GPA requirements, disciplines, or
other user-facing scholarship facts merely to make a seed appear in the feed.
The crawler/extraction/verification pipeline is responsible for creating or
updating ``scholarships`` records after source evidence has been collected.

CSV columns:
    title, category, target_level, state, seed_url, typical_cycle

Only source metadata that the crawler queue can represent is persisted here:
``seed_url`` -> ``crawler_seeds.url``, ``title`` -> ``source_name``, and
``category`` -> ``category``.  The remaining CSV columns stay in the curated
CSV for crawler/source curation and are not converted into scholarship facts.
"""

import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.models import CrawlerSeed

CSV_PATH = Path(__file__).resolve().parents[1] / "scrapers" / "data" / "seed_urls.csv"


def import_seeds() -> None:
    if not CSV_PATH.exists():
        print(f"Error: {CSV_PATH} does not exist.")
        return

    db = SessionLocal()
    created = 0
    updated = 0
    skipped = 0

    try:
        with CSV_PATH.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("seed_url") or "").strip()
                if not url:
                    skipped += 1
                    continue

                source_name = (row.get("title") or "").strip() or None
                category = (row.get("category") or "").strip() or "curated_seed"

                existing = db.query(CrawlerSeed).filter_by(url=url).first()
                if existing:
                    changed = False
                    if source_name and existing.source_name != source_name:
                        existing.source_name = source_name
                        changed = True
                    if category and existing.category != category:
                        existing.category = category
                        changed = True
                    if existing.status in {"failed", "quarantined"}:
                        # Do not silently override operational review states.
                        pass
                    if changed:
                        updated += 1
                    else:
                        skipped += 1
                    continue

                db.add(CrawlerSeed(
                    url=url,
                    source_name=source_name,
                    category=category,
                    priority=2,
                    status="queued",
                ))
                created += 1

        db.commit()
        print(f"Queued {created} new crawler seed(s); updated {updated}; skipped {skipped}.")
        print("No user-facing scholarship facts were fabricated by seed import.")
    except Exception as exc:
        db.rollback()
        print(f"Failed to import seeds: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_seeds()
