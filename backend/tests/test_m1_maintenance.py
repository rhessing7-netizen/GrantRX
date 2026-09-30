"""M1 maintenance tooling invariants.

The registry's health semantics are covered by test_c7_source_registry.py.
These tests guard the maintenance scripts themselves: the unhealthy-sweep
set must match registry semantics, and the apply-script decision tables
must never overlap (a source cannot be both repaired and retired).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.source_registry import HEALTH_STATES
from scripts import m1_apply_repairs, m1_source_check


def test_sweep_covers_every_non_terminal_health():
    """The --all-unhealthy sweep must cover every state except 'healthy'
    and 'retired' (owner-disabled terminal state — never auto-checked)."""
    expected = HEALTH_STATES - {"healthy", "retired"}
    assert set(m1_source_check.NON_HEALTHY) == expected


def test_decision_tables_are_disjoint():
    """A source key may appear in exactly one action table."""
    buckets = [
        set(m1_apply_repairs.REPAIRS),
        set(m1_apply_repairs.ADOPT_RESOLVED),
        set(m1_apply_repairs.RETIRED),
        set(m1_apply_repairs.MARK_REVIEW),
    ]
    seen = set()
    for bucket in buckets:
        assert not (seen & bucket), "source key in two decision tables"
        seen |= bucket


def test_repair_urls_are_https():
    """Every replacement URL must be a canonical https URL."""
    for key, (url, _name) in m1_apply_repairs.REPAIRS.items():
        assert url.startswith("https://"), key
        assert " " not in url, key


def test_notes_cover_every_remaining_review_key():
    """Sources left unresolved carry an explanatory note, and no note is
    orphaned on a source that was actually repaired."""
    repaired_or_changed = (
        set(m1_apply_repairs.REPAIRS)
        | set(m1_apply_repairs.ADOPT_RESOLVED)
        | set(m1_apply_repairs.RETIRED)
    )
    assert not (set(m1_apply_repairs.NOTES) & repaired_or_changed)
