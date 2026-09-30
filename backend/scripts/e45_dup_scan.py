"""E4.5 read-only duplicate-candidate scan over the whole catalog.

Never mutates. Emits candidate pairs with the signals that fired and a
confidence tier. Title similarity alone never yields HIGH.
"""
import json
import os
import re
import sys
from collections import defaultdict
from itertools import combinations
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
assert "5433" in os.environ.get("DATABASE_URL", ""), "pin DATABASE_URL to :5433"

from app.database import SessionLocal  # noqa: E402
from app.models.models import Scholarship  # noqa: E402
from scrapers.utils.identity import canonical_identity_url, normalize_identity_text  # noqa: E402

STOP = {"of", "and", "the", "for", "in", "on", "at", "to", "a", "an", "&"}


def provider_core(p):
    p = re.sub(r"\([^)]*\)", " ", p or "")
    return normalize_identity_text(p)


def domain(u):
    h = (urlparse(u or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def tokens(t):
    return {w for w in normalize_identity_text(t).split() if w not in STOP}


def jacc(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def main():
    db = SessionLocal()
    rows = db.query(Scholarship).all()
    recs = []
    for r in rows:
        if r.lifecycle_status == "archived" and r.archive_reason == "duplicate":
            continue
        recs.append(dict(
            id=str(r.id), title=r.title, provider=r.provider,
            nt=normalize_identity_text(r.title), pc=provider_core(r.provider),
            tok=tokens(r.title), pdom=domain(r.portal_url), sdom=domain(r.source_url),
            canon=canonical_identity_url(r.portal_url or ""),
            ft=r.funding_type, states=sorted(r.state_restrictions or []),
            amt=r.award_amount, life=r.lifecycle_status, reason=r.archive_reason,
            ver=r.verification_status, portal=r.portal_url, source=r.source_url,
            ik=r.identity_key, fk=r.identity_fallback_key,
            created=str(r.created_at),
        ))
    db.close()

    # Block on shared title tokens to avoid O(n^2) noise.
    blocks = defaultdict(set)
    for i, r in enumerate(recs):
        for w in r["tok"]:
            blocks[w].add(i)
    pairs = set()
    for idx in blocks.values():
        if len(idx) > 60:  # generic word ("scholarship"); skip as a block key
            continue
        for a, b in combinations(sorted(idx), 2):
            pairs.add((a, b))
    for a, b in combinations(range(len(recs)), 2):
        if recs[a]["canon"] and recs[a]["canon"] == recs[b]["canon"]:
            pairs.add((a, b))

    out = []
    for a, b in pairs:
        x, y = recs[a], recs[b]
        sig = []
        same_title = x["nt"] == y["nt"]
        j = jacc(x["tok"], y["tok"])
        same_pc = bool(x["pc"]) and x["pc"] == y["pc"]
        same_dom = bool(x["pdom"]) and (x["pdom"] == y["pdom"] or x["sdom"] == y["sdom"])
        same_canon = bool(x["canon"]) and x["canon"] == y["canon"]
        same_states = x["states"] == y["states"]
        if same_title:
            sig.append("title=")
        elif j >= 0.75:
            sig.append(f"title~{j:.2f}")
        else:
            if not same_canon:
                continue
        if same_pc:
            sig.append("provider_core=")
        if same_canon:
            sig.append("portal_canon=")
        if same_dom:
            sig.append("domain=")
        if same_states and x["states"]:
            sig.append("states=")
        if x["amt"] and x["amt"] == y["amt"]:
            sig.append("amount=")
        if x["ft"] and x["ft"] == y["ft"]:
            sig.append("funding=")

        if same_title and same_pc:
            tier = "HIGH"
        elif same_title and (same_dom or same_canon):
            tier = "MEDIUM"
        elif same_canon and j >= 0.5:
            tier = "MEDIUM"
        elif (not same_title) and j >= 0.75 and same_pc and (same_dom or same_states):
            tier = "MEDIUM"
        else:
            tier = "LOW"
        out.append(dict(tier=tier, signals=sig, a=x, b=y))

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out.sort(key=lambda p: (order[p["tier"]], p["a"]["nt"]))
    for p in out:
        for k in ("a", "b"):
            p[k] = {kk: vv for kk, vv in p[k].items() if kk not in ("tok",)}
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "e45_dup_candidates.json"), "w"), indent=1, default=str)
    from collections import Counter
    print("records scanned:", len(recs))
    print("candidate pairs by tier:", dict(Counter(p["tier"] for p in out)))
    for p in out:
        if p["tier"] == "LOW":
            continue
        a, b = p["a"], p["b"]
        print(f"[{p['tier']}] {','.join(p['signals'])}")
        print(f"   A {a['life'][:4]}/{a['ver'][:5]} {a['title'][:55]!r} | {a['provider'][:45]!r} | {a['portal']}")
        print(f"   B {b['life'][:4]}/{b['ver'][:5]} {b['title'][:55]!r} | {b['provider'][:45]!r} | {b['portal']}")


if __name__ == "__main__":
    main()
