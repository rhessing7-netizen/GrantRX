"""M1 maintenance: apply evidence-backed source repairs.

Phase 3/4 executor for the M1 source-health workstream. Applies only
decisions backed by live compliant fetches + authoritative evidence:

  - ``REPAIRS``:   verified 200 authoritative replacement URLs
                   (sources.json url updated so sync_sources does not
                   revert the row to the dead configured URL).
  - ``RETIRED``:   programs authoritatively ended (row marked retired +
                   disabled; entry removed from sources.json).
  - ``MARK_REVIEW``: sources demoted to needs_url_review by hand where a
                   fetch cannot produce that state (e.g. redirect landing
                   on an auth wall).
  - ``NOTES``:     last_error annotations for sources left in an honest
                   unresolved state, so the review queue explains itself.
  - Redirect adoption: for ``redirected_or_moved`` rows whose recorded
                   ``last_resolved_url`` was verified to land on a real
                   program page, adopt the resolved URL as canonical.

Every changed row is fetched through the compliant FetchSession and
persisted via ``source_registry.record_check`` so health/hashes/
scheduling stay internally consistent. Scholarship records are never
touched. A mutation log is written to ``scripts/m1_mutation_log.json``.

Usage:
    python -m scripts.m1_apply_repairs --dry-run   # plan only
    python -m scripts.m1_apply_repairs --write     # apply + log
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SOURCES_JSON = Path(__file__).resolve().parent.parent / "scrapers" / "sources.json"
LOG_PATH = Path(__file__).resolve().parent / "m1_mutation_log.json"

# ---------------------------------------------------------------------------
# Decision table — every entry verified live via the compliant fetch path
# (HTTP 200 + on-topic page title/content) or by authoritative evidence.
# URL = observed final canonical URL (post-redirect), so the stored URL does
# not immediately re-classify as redirected_or_moved.
# ---------------------------------------------------------------------------

# source_key -> (new_url, new_name_or_None)
REPAIRS = {
    # --- permanent_not_found (16) ---
    "community-foundation-for-mississippi": (
        "https://formississippi.org/scholarship-awards/", None),
    "community-foundation-for-northeast-florida": (
        "https://www.jaxcf.org/apply-for-grants-or-scholarships/", None),
    "community-foundation-of-greater-birmingham": (
        "https://www.cfbham.org/grants/scholarships/", None),
    "idaho-community-foundation": (
        "https://www.idahocf.org/grants-scholarships", None),
    "nebraska-rural-health-student-loan-program": (
        "https://dhhs.ne.gov/Pages/Loan-Repayment-FAQ.aspx", None),
    "nevada-primary-care-workforce-assistance": (
        "https://www.dpbh.nv.gov/programs/health-planning-primary-care/primary-care-office/",
        None),
    "new-jersey-hesaa-primary-care-practitioner-redemption": (
        "https://www.hesaa.org/Pages/HCPLRP.aspx", None),
    "north-dakota-health-care-professional-student-repayment": (
        "https://www.hhs.nd.gov/health/primary-care-office/"
        "north-dakota-health-service-corps/healthcare-professional-loan-repayment",
        None),
    "south-carolina-ahec-rural-health-grants": (
        "https://www.scahec.net/recruitment.html", None),
    "south-dakota-recruitment-assistance-program": (
        "https://doh.sd.gov/healthcare-professionals/rural-health/"
        "careers-and-recruiting/recruitment-assistance/", None),
    "the-greater-kanawha-valley-foundation": (
        "https://tgkvf.org/scholarship-information/", None),
    "university-of-pittsburgh-outside-scholarships": (
        "https://financialaid.pitt.edu/types-of-aid/scholarships/pitt-funds-me/",
        None),
    "virginia-state-loan-repayment-program-vdh": (
        "https://www.vdh.virginia.gov/health-equity/virginia-loan-repayment-programs-2/",
        None),
    "walmart-health-equity-scholarship-program": (
        "https://www.aacp.org/resource/"
        "2026-walmart-community-pharmacy-scholarship-pharmacy-students",
        "Walmart Community Pharmacy Scholarship"),
    "west-virginia-health-sciences-service-program": (
        "https://www.cfwv.com/financial-aid/health-sciences-service-program/",
        None),
    "wyoming-healthcare-professional-loan-program": (
        "https://health.wyo.gov/publichealth/rural/officeofruralhealth/primary-care-office/",
        None),
    # --- needs_url_review (6) ---
    "cleveland-clinic-tuition-assistance-program": (
        "https://jobs.clevelandclinic.org/benefits/", None),
    "cvs-health-foundation-pharmacy-scholarship": (
        "https://www.aacp.org/resource/"
        "2026-cvs-health-foundation-aacp-community-pharmacy-award",
        "CVS Health Foundation / AACP Community Pharmacy Award"),
    "georgia-board-of-health-care-workforce-grants": (
        "https://healthcareworkforce.georgia.gov/loan-repayment-programs/"
        "loan-repayment-programs", None),
    "indiana-primary-care-scholarship-che": (
        "https://www.marian.edu/osteopathic-medical-school/financial-aid/scholarships",
        None),
    "ohio-state-university-outside-scholarships": (
        "https://sfa.osu.edu/current-student/types-of-aid/scholarships", None),
    "the-minneapolis-foundation": (
        "https://www.minneapolisfoundation.org/funding-opportunities/", None),
    # --- unknown (1) ---
    "mikeroweworks-work-ethic-scholarship": (
        "https://mikeroweworks.org/scholarship/", None),
    # --- redirected_or_moved (1): real relocation, not canonicalization ---
    "kentucky-kheaa-osteopathic-medicine-scholarship": (
        "https://www.kheaa.com/web/scholarships-grants.faces", None),
}

# Redirected sources whose recorded last_resolved_url was verified to land on
# a real program/scholarship page — adopt the resolved URL as canonical.
ADOPT_RESOLVED = (
    "aacn-student-scholarship-directory",
    "adea-crest-oral-b-scholarships",
    "aotf-scholarship-program",
    "baltimore-community-foundation",
    "central-carolina-community-foundation",
    "community-foundation-for-southeast-michigan",
    "community-foundation-of-greater-memphis",
    "community-foundation-of-new-jersey",
    "delaware-community-foundation",
    "delaware-health-care-commission-slrp",
    "dell-scholars-program",
    "greater-new-orleans-foundation",
    "hartford-foundation-for-public-giving",
    "national-association-of-hispanic-nurses-nahn-grants",
    "national-black-nurses-association-nbna-scholarships",
    "ncpa-foundation-scholarships",
    "society-of-women-engineers-scholarships",
    "st-louis-community-foundation",
    "taco-bell-live-mas-scholarship",
)

# Programs authoritatively ended — retire the source (never rescheduled).
RETIRED = {
    "mississippi-health-care-professions-scholarship": (
        "M1: retired — MS Office of Student Financial Aid lists HCP under "
        "'Inactive Programs: no longer funded, no new awards'"),
    "iowa-health-care-professional-recruitment": (
        "M1: retired — program consolidated into Health Care Professional "
        "Incentive Program (HF 972, 2025); not among current Iowa aid programs"),
}

# Redirect lands on an auth wall — fetch can't produce needs_url_review.
MARK_REVIEW = {
    "aacp-express-scripts-pharmacy-scholarship": (
        "M1: canonical URL redirects to my.aacp.org sign-in; public program "
        "page no longer fetchable — needs owner decision"),
}

# Honest unresolved annotations (state unchanged).
NOTES = {
    "encompass-health-inpatient-therapy-scholarships":
        "M1: student-center page 404; no current public scholarship/program "
        "page found on encompasshealth.com or careers.encompasshealth.com",
    "genesis-healthcare-therapy-nursing-scholarships":
        "M1: /careers/scholarships 404; careers moved to genesiscareers.jobs "
        "but no public scholarships listing exists",
    "intermountain-health-healthcare-foundation-grants":
        "M1: foundation scholarships page 404; Intermountain scholarships "
        "now dispersed via partner colleges — no central public listing",
    "omaha-community-foundation":
        "M1: /scholarships/ 404; no student-facing scholarship listing found",
    "tennessee-rural-health-loan-forgiveness-tsac":
        "M1: tn.gov unreachable to compliant crawler (robots unavailable); "
        "old TSAC page 404 — needs manual verification",
    "community-foundation-of-utah":
        "M1: /receive/scholarships confirmed 404; no public student-facing "
        "scholarship listing on utahcf.org",
    "nevada-community-foundation":
        "M1: /scholarships/ returns 404; NCF has no public student-facing "
        "scholarship listing (fund-administered awards only)",
}


async def run(write: bool) -> dict:
    from dotenv import load_dotenv

    load_dotenv()

    from app.database import SessionLocal
    from app.models.models import CatalogSource
    from scrapers.fetch_policy import (
        FetchResult, OUTCOME_NETWORK_ERROR, default_session)
    from scrapers.fetcher import fetch_result
    from scrapers.source_registry import record_check
    from scrapers.sources import load_sources

    db = SessionLocal()
    session = default_session()
    log = {"at": datetime.utcnow().isoformat() + "Z", "changes": []}
    try:
        rows = {s.source_key: s for s in db.query(CatalogSource).all()}
        processed = set()

        async def check(src, prime: bool = True):
            if prime:
                session.prime_validators(src.url, src.etag, src.last_modified)
            else:
                # URL changed — old validators belong to the old resource.
                src.etag = None
                src.last_modified = None
            try:
                return await fetch_result(
                    src.url, scraper_type=src.scraper_type or "deterministic",
                    session=session)
            except Exception as exc:  # noqa: BLE001
                return FetchResult(url=src.url, outcome=OUTCOME_NETWORK_ERROR,
                                   error=type(exc).__name__)

        # -- URL repairs -------------------------------------------------
        for key, (new_url, new_name) in REPAIRS.items():
            src = rows[key]
            processed.add(key)
            before = {"url": src.url, "name": src.name, "health": src.health}
            src.url = new_url
            if new_name:
                src.name = new_name
            res = await check(src, prime=False)
            if write:
                health = record_check(db, src, res)
            else:
                from scrapers.source_registry import classify_health
                health = classify_health(src.health, res)
            log["changes"].append({
                "type": "repair_url", "source_key": key,
                "before": before,
                "after": {"url": src.url, "name": src.name,
                          "health": health, "outcome": res.outcome,
                          "http_status": res.http_status,
                          "final_url": res.final_url}})
            print(f"repair {key:55} {before['health']:>20} -> {health} "
                  f"({res.outcome} {res.http_status})")

        # -- redirect canonical adoption ---------------------------------
        for key in ADOPT_RESOLVED:
            src = rows[key]
            processed.add(key)
            resolved = src.last_resolved_url
            before = {"url": src.url, "health": src.health}
            src.url = resolved
            res = await check(src, prime=False)
            if write:
                health = record_check(db, src, res)
            else:
                from scrapers.source_registry import classify_health
                health = classify_health(src.health, res)
            log["changes"].append({
                "type": "adopt_resolved", "source_key": key,
                "before": before,
                "after": {"url": src.url, "health": health,
                          "outcome": res.outcome,
                          "http_status": res.http_status,
                          "final_url": res.final_url}})
            print(f"adopt  {key:55} -> {health} ({res.outcome} "
                  f"{res.http_status})")

        # -- retire confirmed-ended programs ------------------------------
        for key, note in RETIRED.items():
            src = rows[key]
            before = {"url": src.url, "health": src.health,
                      "enabled": src.enabled}
            if write:
                src.health = "retired"
                src.enabled = False
                src.next_check_at = None
                src.last_error = note
                src.updated_at = datetime.utcnow()
                db.commit()
            log["changes"].append({
                "type": "retired", "source_key": key, "before": before,
                "after": {"health": "retired", "enabled": False,
                          "note": note}})
            print(f"retire {key:55} {before['health']:>20} -> retired")

        # -- manual needs_url_review (fetch can't express it) -------------
        for key, note in MARK_REVIEW.items():
            src = rows[key]
            before = {"url": src.url, "health": src.health}
            if write:
                src.health = "needs_url_review"
                src.next_check_at = None
                src.last_error = note
                src.updated_at = datetime.utcnow()
                db.commit()
            log["changes"].append({
                "type": "needs_url_review", "source_key": key,
                "before": before, "after": {"health": "needs_url_review",
                                            "note": note}})
            print(f"review {key:55} {before['health']:>20} -> "
                  f"needs_url_review")

        # -- recheck confirmed-dead (utahcf: PNF->NUR; nevadacf: first 404)
        for key in ("community-foundation-of-utah", "nevada-community-foundation"):
            src = rows[key]
            processed.add(key)
            before = {"url": src.url, "health": src.health}
            res = await check(src)
            if write:
                health = record_check(db, src, res)
            else:
                from scrapers.source_registry import classify_health
                health = classify_health(src.health, res)
            log["changes"].append({
                "type": "recheck", "source_key": key, "before": before,
                "after": {"health": health, "outcome": res.outcome,
                          "http_status": res.http_status}})
            print(f"recheck {key:54} {before['health']:>20} -> {health} "
                  f"({res.outcome} {res.http_status})")

        # -- first live check for remaining unknown sources ---------------
        for key, src in rows.items():
            if src.health == "unknown" and key not in processed:
                before = {"url": src.url, "health": src.health}
                res = await check(src)
                if write:
                    health = record_check(db, src, res)
                else:
                    from scrapers.source_registry import classify_health
                    health = classify_health(src.health, res)
                log["changes"].append({
                    "type": "first_check", "source_key": key,
                    "before": before,
                    "after": {"health": health, "outcome": res.outcome,
                              "http_status": res.http_status,
                              "final_url": res.final_url}})
                print(f"first  {key:55} unknown -> {health} "
                      f"({res.outcome} {res.http_status})")

        # -- annotations on unresolved rows -------------------------------
        if write:
            for key, note in NOTES.items():
                src = rows[key]
                src.last_error = note
                src.updated_at = datetime.utcnow()
            db.commit()

        # -- sources.json sync --------------------------------------------
        # sync_sources matches config -> row by URL and would otherwise
        # overwrite the maintained row.url with the stale configured URL.
        if write:
            configs = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
            old_to_new = {}
            renamed = {}
            for c in log["changes"]:
                if c["type"] in ("repair_url", "adopt_resolved"):
                    old_to_new[c["before"]["url"]] = c["after"]["url"]
            # program renames discovered during maintenance
            renamed["Walmart Health Equity Scholarship Program"] = (
                "Walmart Community Pharmacy Scholarship")
            renamed["CVS Health Foundation Pharmacy Scholarship"] = (
                "CVS Health Foundation / AACP Community Pharmacy Award")
            out = []
            for cfg in configs:
                if cfg.get("url") in old_to_new:
                    cfg["url"] = old_to_new[cfg["url"]]
                if cfg.get("name") in renamed:
                    cfg["name"] = renamed[cfg["name"]]
                out.append(cfg)
            # retire entries removed via name match on retired source keys
            retire_names = {
                "Mississippi Health Care Professions Scholarship",
                "Iowa Health Care Professional Recruitment",
            }
            out = [c for c in out if c.get("name") not in retire_names]
            SOURCES_JSON.write_text(json.dumps(out, indent=2) + "\n",
                                    encoding="utf-8")
            removed = len(configs) - len(out)
            print(f"sources.json: {removed} retired entries removed, "
                  f"{len(out)} remain")
    finally:
        db.close()
        await session.aclose()
    return log


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.m1_apply_repairs")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    log = asyncio.run(run(write=args.write and not args.dry_run))
    if args.write and not args.dry_run:
        LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")
        print(f"mutation log -> {LOG_PATH}")
    print(f"{len(log['changes'])} source change(s) applied"
          if args.write else f"{len(log['changes'])} change(s) planned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
