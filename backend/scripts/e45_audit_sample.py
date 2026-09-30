"""E4.5 Part G: independent stratified sample of CURRENTLY DISCOVERABLE E4-added records.

Excludes every record in the E4 audit sample (independence). Stratifies by
source category (employer / government / association ...), funding type,
geography (state vs national), and discipline, then fills round-robin.
Writes the sample plus an evidence-probe file for scripts/e45_evidence.py.
"""
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
assert "5433" in os.environ.get("DATABASE_URL", ""), "pin DATABASE_URL to :5433"

from app.database import SessionLocal  # noqa: E402
from app.models.models import CatalogSource, Scholarship  # noqa: E402
from app.services import lifecycle  # noqa: E402

HERE = os.path.dirname(__file__)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 56
GOV = {"state_agency", "federal_program", "government_employee_benefit"}
EMP = {"employer_tuition_benefit", "corporate_healthcare", "corporate_unrestricted", "clinical_employee_pipeline"}


def group(cat):
    return "government" if cat in GOV else "employer" if cat in EMP else "association/foundation/institution"


def main():
    db = SessionLocal()
    keys = set(json.load(open(os.path.join(HERE, "e4_new_source_keys.json"))))
    src = {s.url: s.category for s in db.query(CatalogSource).filter(CatalogSource.source_key.in_(keys))}
    src["https://ccpe.nebraska.gov/financial-aid"] = "state_agency"
    prior = {r["id"] for r in json.load(open(os.path.join(HERE, "e4_audit_sample.json")))["records"]}
    pool = [r for r in db.query(Scholarship).filter(Scholarship.source_url.in_(list(src)))
            if lifecycle.is_discoverable(r) and str(r.id) not in prior]
    random.seed(4545)
    random.shuffle(pool)
    strata = defaultdict(list)
    for r in pool:
        strata[(group(src[r.source_url]), r.funding_type or "null", r.scope or "null")].append(r)
    picked, seen = [], set()
    while len(picked) < min(N, len(pool)):
        progressed = False
        for k in sorted(strata):
            if strata[k] and len(picked) < N:
                r = strata[k].pop()
                if r.id not in seen:
                    picked.append(r)
                    seen.add(r.id)
                    progressed = True
        if not progressed:
            break
    out, probes = [], []
    for r in picked:
        rec = dict(id=str(r.id), title=r.title, provider=r.provider, provider_type=r.provider_type,
                   group=group(src[r.source_url]), category=src[r.source_url], funding_type=r.funding_type,
                   scope=r.scope, states=r.state_restrictions, award_amount=r.award_amount,
                   deadline=str(r.deadline) if r.deadline else None, disciplines=r.eligible_disciplines,
                   credentials=r.eligible_credentials, levels=r.academic_levels, min_gpa=r.min_gpa,
                   employment_required=r.employment_required, service=r.has_service_commitment,
                   service_months=r.service_commitment_duration_months,
                   verification=r.verification_status, verified_fields=r.verified_fields,
                   portal_url=r.portal_url, source_url=r.source_url)
        out.append(rec)
        pats = [re.escape(r.title[:40])]
        if r.award_amount:
            pats.append(r"\$\s?" + f"{r.award_amount:,}".replace(",", ",?"))
        if r.deadline:
            pats.append(r.deadline.strftime("%B") + r"\s+" + str(r.deadline.day))
        pats.append(r"eligib|must (be|have)|resident|citizen|enrolled|employ|serve|service")
        url = r.portal_url if r.portal_url and "docs.google" not in r.portal_url else r.source_url
        probes.append(dict(label=f"{str(r.id)[:8]} {r.title[:50]}", url=url, patterns=pats, max_hits=2))
        if url != r.source_url:
            probes.append(dict(label=f"{str(r.id)[:8]} (source)", url=r.source_url,
                               patterns=[re.escape(r.title[:40])], max_hits=1))
    json.dump(out, open(os.path.join(HERE, "e45_audit_sample.json"), "w"), indent=1, default=str)
    json.dump(probes, open(os.path.join(HERE, "e45_audit_probes.json"), "w"), indent=1)
    print("pool (discoverable E4, excl. E4 sample):", len(pool), "sampled:", len(out))
    for dim in ("group", "funding_type", "scope", "provider_type"):
        print(dim, dict(Counter(str(o[dim]) for o in out)))
    print("disciplines", dict(Counter(d for o in out for d in (o["disciplines"] or ["<none>"]))))
    db.close()


if __name__ == "__main__":
    main()
