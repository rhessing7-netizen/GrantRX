"""Q1 audit: independently re-verify every cleared record's FINAL claims
against freshly fetched authoritative evidence.

For each record the dry-run cleared, rebuild the final claim set (persisted
fields minus the degraded optional claims), fetch the authoritative
source/portal pages through the C6 policy, rebuild the evidence window the
same way the engine does, and run the real verification engine on the final
claims. Any cleared record whose remaining assertions are unsupported is a
stop-and-fix finding.
"""
import asyncio
import json
import sys
from datetime import date

from app.database import SessionLocal
from app.models.models import Scholarship
from scrapers.extraction import _deadline_year_supported, evidence_windows
from scrapers.fetch_policy import default_session
from scrapers.schema import ScholarshipExtract
from scrapers.utils.page_links import normalize_link
from scrapers.verification import html_to_text, verify_extract_against_text


async def main():
    rep = json.load(open("q1_dryrun_full.json"))
    outcomes = rep["outcomes"]
    cleared_ids = [rid for rid, o in outcomes.items() if o["action"] == "verified"]

    db = SessionLocal()
    session = default_session()
    cache = {}

    async def fetch(url):
        if url not in cache:
            cache[url] = await session.get(url, timeout=30)
        return cache[url]

    # All persisted titles per source for windowing (same as engine).
    source_titles = {}
    for src, title in db.query(Scholarship.source_url, Scholarship.title).all():
        source_titles.setdefault(src or "", []).append(title or "")

    findings = []
    audit_rows = []
    for rid in cleared_ids:
        row = db.query(Scholarship).filter(Scholarship.id == rid).first()
        o = outcomes[rid]
        degraded = set(o["degraded"])

        # Final claim set = persisted claims minus degraded optionals.
        deadline_claim = None if "unsupported_deadline" in degraded else (
            row.deadline.isoformat() if row.deadline else None)
        extract = ScholarshipExtract(
            title=row.title, provider=row.provider or "",
            portal_url=row.portal_url or "",
            award_amount=None if "unsupported_award_amount" in degraded else row.award_amount,
            deadline=deadline_claim,
            min_gpa=None if "unsupported_min_gpa" in degraded else
            (row.min_gpa if row.min_gpa not in (None, 0.0) else None),
            eligible_disciplines=[] if "unsupported_unrestricted_claim" in degraded
            else list(row.eligible_disciplines or []),
            is_general_major=False if "unsupported_unrestricted_claim" in degraded
            else bool(row.is_general_major),
        )

        # Rebuild evidence exactly as the engine did.
        evidence_parts = []
        title_ok = False
        if row.source_url:
            res = await fetch(row.source_url)
            if res.ok and res.text:
                text = html_to_text(res.text)
                sibs = [t for t in source_titles.get(row.source_url or "", [])
                        if t and t != row.title]
                win = evidence_windows(text, [row.title, *sibs])[0] if sibs else text
                evidence_parts.append(win)
                title_ok = row.title.lower() in text.lower()
        if row.portal_url and normalize_link(row.portal_url) != normalize_link(row.source_url or ""):
            res = await fetch(row.portal_url)
            if res.ok and res.text:
                evidence_parts.append(html_to_text(res.text))
        evidence = " ".join(p for p in evidence_parts if p).strip()

        # Replicate the engine's pre-verification normalization: a deadline
        # whose year is unsupported by the evidence window degrades to
        # unknown — the final persisted claim is None, not the old value.
        extract.deadline = _deadline_year_supported(extract.deadline, evidence)

        verdict = verify_extract_against_text(extract, evidence)
        fields = verdict.get("fields", {})
        bad = {f: v for f, v in fields.items() if v == "unverified"}
        status = verdict.get("status")

        audit_rows.append({
            "id": rid, "title": row.title, "provider": row.provider,
            "degraded": sorted(degraded), "final_fields": fields,
            "audit_status": status, "title_on_source": title_ok,
            "award_amount": extract.award_amount,
            "deadline": extract.deadline,
        })
        if status != "verified" or bad:
            findings.append({
                "id": rid, "title": row.title, "status": status,
                "unverified": bad, "degraded": sorted(degraded),
                "claims": {"award": extract.award_amount,
                           "deadline": extract.deadline,
                           "gpa": extract.min_gpa,
                           "disciplines": extract.eligible_disciplines},
            })

    json.dump({"audited": len(audit_rows), "findings": findings,
               "rows": audit_rows}, open("q1_audit_results.json", "w"),
              indent=2, default=str)
    print(f"audited={len(audit_rows)} pages={len(cache)} findings={len(findings)}")
    for f in findings[:30]:
        print(" FINDING:", f["title"][:55], f["unverified"], "claims:", f["claims"])
    db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
