"""Duplicate-candidate DETECTION for catalog audits (E4.5).

Read-only companion to ``identity.py``. Identity stays exact and
conservative (false merges are data corruption); this module only
*reports* pairs that exact identity cannot see, for human review:

  HIGH    same normalized title AND same provider core (provider with
          parenthetical qualifiers removed, e.g. "Board (HEAB)" == "Board").
          Proven E4 miss: the same WI program ingested from a statute page
          and a program page under "... Aids Board" / "... Aids Board (HEAB)".
  MEDIUM  same normalized title AND the same non-empty state set, but a
          different provider (administrator vs listing site — e.g. Next NC
          via CFNC and via the UNC System); or same title on the same domain.
  LOW     everything else that shares a title. Never actionable alone.

Nothing here mutates data or feeds ``compute_identity_keys``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from .identity import normalize_identity_text

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"


def provider_core(provider: Optional[str]) -> str:
    """Provider text with parenthetical qualifiers removed, then normalized."""
    return normalize_identity_text(re.sub(r"\([^)]*\)", " ", provider or ""))


def _domain(url: Optional[str]) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


@dataclass(frozen=True)
class DupCandidate:
    tier: str
    a_id: str
    b_id: str
    signals: tuple


def classify_pair(a, b) -> Optional[DupCandidate]:
    """Classify two opportunity-like objects; None when titles differ."""
    ta, tb = normalize_identity_text(a.title), normalize_identity_text(b.title)
    if not ta or ta != tb:
        return None
    signals = ["title="]
    same_core = bool(provider_core(a.provider)) and provider_core(a.provider) == provider_core(b.provider)
    if same_core:
        signals.append("provider_core=")
    sa, sb = sorted(a.state_restrictions or []), sorted(b.state_restrictions or [])
    same_states = bool(sa) and sa == sb
    if same_states:
        signals.append("states=")
    same_domain = bool(_domain(a.portal_url)) and _domain(a.portal_url) == _domain(b.portal_url)
    if same_domain:
        signals.append("domain=")
    if same_core:
        tier = HIGH
    elif same_states or same_domain:
        tier = MEDIUM
    else:
        tier = LOW
    return DupCandidate(tier, str(a.id), str(b.id), tuple(signals))


def find_candidates(rows: Iterable, *, skip_archived_duplicates: bool = True) -> List[DupCandidate]:
    """All same-title candidate pairs, grouped by normalized title (O(n))."""
    groups: dict = {}
    for r in rows:
        if skip_archived_duplicates and getattr(r, "archive_reason", None) == "duplicate":
            continue
        key = normalize_identity_text(r.title)
        if key:
            groups.setdefault(key, []).append(r)
    out: List[DupCandidate] = []
    for members in groups.values():
        members = sorted(members, key=lambda r: str(r.id))
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                c = classify_pair(members[i], members[j])
                if c:
                    out.append(c)
    order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    out.sort(key=lambda c: (order[c.tier], c.a_id, c.b_id))
    return out


def summarize(cands: Sequence[DupCandidate]) -> dict:
    return {t: sum(1 for c in cands if c.tier == t) for t in (HIGH, MEDIUM, LOW)}
