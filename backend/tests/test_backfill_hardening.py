"""Backfill-hardening coverage — pilot findings and controlled-batch controls.

Proves:
- low-information gate rejects generic filler / title restatement but keeps
  legitimate concise and number-free narratives
- large aggregate pages are reduced to bounded, target-scoped evidence and
  ambiguous targets fail closed
- the canonical backfill tool enforces dry-run default, caps, apply gating,
  staging/prod identity, no-overwrite, deterministic selection,
  already-described skip, failure classification, auth abort, bounded
  retries, and verbatim artifact application
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from scrapers.extraction import isolate_target_evidence
from scrapers.llm_parser import (
    LLM_ERR_AUTH,
    LLM_ERR_CONTEXT,
    LLM_ERR_OTHER,
    LLM_ERR_RATE_LIMIT,
    LLMScholarship,
    classify_llm_error,
    llm_item_to_extract,
)
from scrapers.verification import description_low_information

BACKEND = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "backfill_public_description",
    BACKEND / "scripts" / "backfill_public_description.py",
)
bpd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bpd)


# --------------------------------------------------------------------------
# Low-information gate
# --------------------------------------------------------------------------

FSAG_TITLE = "Florida Student Assistance Grant"
FSAG_PROVIDER = "Florida Student Scholarship & Grant Programs"
FSAG_EVIDENCE = (
    "State Grants & Scholarships. Florida Student Assistance Grant. "
    "Florida Work Experience Program. Scholarship search resources. "
    "Contact the Office of Student Financial Assistance. Programs A-Z index."
)


class TestLowInformationGate:
    def test_fsag_style_generic_filler_rejected(self):
        """The pilot reject: name restatement + 'ensuring they have the
        support needed' filler, grounded only by a directory index."""
        desc = (
            "The Florida Student Assistance Grant provides financial aid to "
            "eligible students in Florida, ensuring they have the support "
            "needed to pursue their education."
        )
        assert description_low_information(
            desc, title=FSAG_TITLE, provider=FSAG_PROVIDER,
            evidence_text=FSAG_EVIDENCE,
        ) == "restatement"

    _RICH_EVIDENCE = (
        "Programme listings for the region: the Alpha Merit Scholarship, "
        "Bravo Nursing Grant, and Rural Health Scholarship are administered "
        "annually with contact details and forms for each named award."
    )

    def test_title_only_restatement_rejected(self):
        assert description_low_information(
            "The Rural Health Scholarship is a scholarship offered by the "
            "Health Foundation for students.",
            title="Rural Health Scholarship",
            provider="Health Foundation",
            evidence_text=self._RICH_EVIDENCE,
        ) == "restatement"

    def test_provider_title_repetition_rejected(self):
        assert description_low_information(
            "An award from the Health Foundation, the Rural Health "
            "Scholarship provides scholarships to eligible students.",
            title="Rural Health Scholarship",
            provider="Health Foundation",
            evidence_text=self._RICH_EVIDENCE,
        ) == "restatement"

    def test_legitimate_concise_narrative_accepted(self):
        desc = (
            "The Rural Health Scholarship supports nursing students "
            "training in Ohio clinics."
        )
        evidence = (
            "Rural Health Scholarship. Open to nursing students undertaking "
            "clinical training at clinics across Ohio. Applications reviewed "
            "each cycle by the foundation board."
        )
        assert description_low_information(
            desc, title="Rural Health Scholarship",
            provider="Health Foundation", evidence_text=evidence,
        ) is None

    def test_meaningful_no_number_narrative_accepted(self):
        """No numeric facts required — substantive supported terms suffice."""
        desc = (
            "A fellowship supporting early-career science journalists "
            "covering international affairs."
        )
        evidence = (
            "The fellowship is intended for early-career journalists "
            "specialising in science coverage and international affairs. "
            "Recipients join the society's mentoring programme."
        )
        assert description_low_information(
            desc, title="International Fellowship",
            provider="Journalism Society", evidence_text=evidence,
        ) is None

    def test_unsupported_substantive_terms_rejected(self):
        """Novel claims the evidence cannot locate — prose-layer
        hallucination that numeric grounding cannot see."""
        desc = (
            "The Rural Health Scholarship supports veterinary radiology "
            "residents in Alberta."
        )
        evidence = (
            "Rural Health Scholarship. Open to nursing students undertaking "
            "clinical training at clinics across Ohio."
        )
        assert description_low_information(
            desc, title="Rural Health Scholarship",
            provider="Health Foundation", evidence_text=evidence,
        ) == "unsupported"

    def test_sparse_source_rejected(self):
        assert description_low_information(
            "The Rural Health Scholarship supports nursing students.",
            title="Rural Health Scholarship", provider="Health Foundation",
            evidence_text="Scholarship. Apply.",
        ) == "sparse_source"


# --------------------------------------------------------------------------
# Large-source target isolation
# --------------------------------------------------------------------------

def _listing_page(target_pos="middle"):
    """A synthetic aggregate page with three scholarships; the target's
    facts differ sharply from its siblings' so contamination is visible."""
    alpha = (
        "Alpha Merit Scholarship\n"
        "The Alpha Merit Scholarship awards $1,000 to violin students "
        "studying at the conservatory. Deadline March 1.\n\n"
    )
    bravo = (
        "Bravo Nursing Grant\n"
        "The Bravo Nursing Grant awards $9,500 to registered nurses "
        "pursuing oncology certification. Deadline July 15.\n\n"
    )
    target = (
        "Spicer Family Scholarship\n"
        "The Spicer Family Scholarship provides $2,000 to graduates of "
        "Cody High School attending any Wyoming college. Deadline "
        "October 1. Renewable for four years.\n\n"
    )
    preamble = (
        "Wyoming Community Foundation — scholarships are open to "
        "residents of Wyoming and administered through the "
        "foundation's annual cycle.\n\n"
    )
    parts = {
        "beginning": [target, alpha, bravo],
        "middle": [alpha, target, bravo],
        "end": [alpha, bravo, target],
    }[target_pos]
    return preamble + "".join(parts)


LABELS = [
    "Alpha Merit Scholarship",
    "Bravo Nursing Grant",
    "Spicer Family Scholarship",
]


class TestTargetIsolation:
    @pytest.mark.parametrize("pos", ["beginning", "middle", "end"])
    def test_target_isolated_at_any_position(self, pos):
        page = _listing_page(pos)
        out = isolate_target_evidence(page, "Spicer Family Scholarship", LABELS)
        assert out is not None
        assert "Spicer Family Scholarship" in out
        assert "Cody High School" in out          # target's own facts kept
        assert "Wyoming Community Foundation" in out  # page-level context kept
        assert "$9,500" not in out                # sibling detail excluded
        assert "oncology certification" not in out
        assert "violin students" not in out

    def test_bounded_context(self):
        page = _listing_page() + "padding " * 5000
        out = isolate_target_evidence(
            page, "Spicer Family Scholarship", LABELS, total_cap=3000
        )
        assert out is not None and len(out) <= 3000

    def test_title_absent_fails_closed(self):
        assert isolate_target_evidence(
            _listing_page(), "Nonexistent Award", LABELS
        ) is None

    def test_similar_names_fail_closed(self):
        """'Alpha Scholarship' could mean I or II — never guess."""
        labels = ["Alpha Scholarship I", "Alpha Scholarship II"]
        page = (
            "Awards page.\n\nAlpha Scholarship I\nFor violin students.\n\n"
            "Alpha Scholarship II\nFor viola students.\n\n"
        )
        assert isolate_target_evidence(page, "Alpha Scholarship", labels) is None

    def test_repeated_target_occurrences_union_segments(self):
        page = (
            "Index: Spicer Family Scholarship — see below.\n\n"
            + _listing_page()
        )
        out = isolate_target_evidence(page, "Spicer Family Scholarship", LABELS)
        assert out is not None and "Cody High School" in out

    def test_no_cross_contamination_on_shared_program(self):
        """Target facts must come from its own segment, not a sibling's."""
        out = isolate_target_evidence(_listing_page(), "Bravo Nursing Grant", LABELS)
        assert "$9,500" in out and "Cody High School" not in out


# --------------------------------------------------------------------------
# LLM error taxonomy
# --------------------------------------------------------------------------

class TestClassifyLlmError:
    def test_auth_status(self):
        class E(Exception):
            status_code = 401
        assert classify_llm_error(E("nope")) == LLM_ERR_AUTH

    def test_invalid_api_key_message(self):
        assert classify_llm_error(
            Exception("invalid api key provided")
        ) == LLM_ERR_AUTH

    def test_rate_limit(self):
        class RateLimitError(Exception):
            pass
        assert classify_llm_error(RateLimitError("slow down")) == LLM_ERR_RATE_LIMIT

    def test_context_limit(self):
        assert classify_llm_error(
            Exception("output truncated: max_tokens reached")
        ) == LLM_ERR_CONTEXT

    def test_other(self):
        assert classify_llm_error(Exception("boom")) == LLM_ERR_OTHER


class TestSanitizerDropFlag:
    def test_url_bearing_description_flagged(self):
        item = LLMScholarship(
            title="T", provider="P",
            public_description="Apply at https://x.example for this award",
        )
        ex = llm_item_to_extract(item, "https://src.example")
        assert ex.public_description is None
        assert ex.public_description_dropped is True

    def test_clean_description_not_flagged(self):
        item = LLMScholarship(
            title="T", provider="P",
            public_description="A faithful grounded summary of the award.",
        )
        ex = llm_item_to_extract(item, "https://src.example")
        assert ex.public_description is not None
        assert ex.public_description_dropped is False


# --------------------------------------------------------------------------
# Backfill tool controls
# --------------------------------------------------------------------------

STAGING_URL = "postgresql://postgres.cacpuytmmwlilidadklu:pw@aws-0-us-east-2.pooler.supabase.com:6543/postgres"


class TestIdentityGuards:
    def test_staging_identity_required(self, monkeypatch):
        monkeypatch.setenv("TARGET_DATABASE_URL", "postgresql://x:y@db.supabase.com/postgres")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            bpd.staging_db_url()

    def test_production_refused(self, monkeypatch):
        monkeypatch.setenv(
            "TARGET_DATABASE_URL",
            "postgresql://postgres.bcsniblbexmugkypbrff:pw@aws-0-us-east-2.pooler.supabase.com:6543/postgres",
        )
        with pytest.raises(SystemExit):
            bpd.staging_db_url()

    def test_local_catalog_refused(self, monkeypatch):
        monkeypatch.setenv("TARGET_DATABASE_URL", "postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx")
        with pytest.raises(SystemExit):
            bpd.staging_db_url()

    def test_staging_accepted(self, monkeypatch):
        monkeypatch.setenv("TARGET_DATABASE_URL", STAGING_URL)
        assert bpd.staging_db_url() == STAGING_URL


class TestBatchControls:
    def _run_main(self, monkeypatch, argv):
        monkeypatch.setattr("sys.argv", ["backfill", *argv])
        return bpd.main()

    def test_dry_run_is_default(self, monkeypatch, tmp_path):
        called = {"dry": False, "apply": False}

        async def fake_dry(args):
            called["dry"] = True

        monkeypatch.setattr(bpd, "cmd_dry_run", fake_dry)
        monkeypatch.setattr(bpd, "cmd_apply", lambda a: called.__setitem__("apply", True))
        self._run_main(monkeypatch, ["--out", str(tmp_path / "r.json")])
        assert called["dry"] and not called["apply"]

    def test_hard_cap_25(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._run_main(monkeypatch, ["--limit", "26"])

    def test_limit_25_allowed(self, monkeypatch, tmp_path):
        async def fake_dry(args):
            pass

        monkeypatch.setattr(bpd, "cmd_dry_run", fake_dry)
        self._run_main(monkeypatch, ["--limit", "25", "--out", str(tmp_path / "r.json")])

    def test_ids_over_cap_blocked(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._run_main(monkeypatch, ["--ids", *[f"id{i}" for i in range(26)]])

    def test_apply_requires_results(self, monkeypatch):
        with pytest.raises(SystemExit):
            self._run_main(monkeypatch, ["--apply"])

    def test_selection_is_deterministic_and_null_only(self):
        sql = bpd._candidate_sql([])
        assert "ORDER BY title" in sql
        assert "LIMIT" in sql and sql.index("ORDER BY") < sql.index("LIMIT")
        assert "public_description IS NULL" in bpd.CANDIDATE_SQL
        assert "lifecycle_status = 'published'" in bpd.CANDIDATE_SQL
        assert "IS DISTINCT FROM 'needs_review'" in bpd.CANDIDATE_SQL


# --------------------------------------------------------------------------
# Resumability — artifact-aware exclusion (Batch-2 gap fix)
# --------------------------------------------------------------------------

def _artifact(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(json.dumps(rows), encoding="utf-8")
    return str(p)


_R1 = "11111111-0000-0000-0000-000000000001"
_R2 = "22222222-0000-0000-0000-000000000002"
_R3 = "33333333-0000-0000-0000-000000000003"


class TestResumability:
    def test_success_and_failure_ids_all_excluded(self, tmp_path):
        """Every adjudicated record consumes its slot — not just failures."""
        art = _artifact(tmp_path, "b1.json", [
            {"id": _R1, "classification": bpd.OUTCOME_SUCCESS,
             "public_description": "x"},
            {"id": _R2, "classification": bpd.OUTCOME_LOW_INFORMATION},
            {"id": _R3, "classification": bpd.OUTCOME_NOT_ISOLATED},
        ])
        assert bpd.load_exclusion_ids([art]) == {_R1, _R2, _R3}

    def test_multiple_artifacts_combine_and_dedupe(self, tmp_path):
        a = _artifact(tmp_path, "a.json", [{"id": _R1}, {"id": _R2}])
        b = _artifact(tmp_path, "b.json", [{"id": _R2}, {"id": _R3}])
        assert bpd.load_exclusion_ids([a, b]) == {_R1, _R2, _R3}

    def test_exclusion_applies_before_limit(self):
        """WHERE … id <> ALL(%) ORDER BY title LIMIT — not select-then-drop."""
        sql = bpd._candidate_sql({_R1})
        assert "id <> ALL" in sql
        assert sql.index("id <> ALL") < sql.index("ORDER BY") < sql.index("LIMIT")
        assert "id <> ALL" not in bpd._candidate_sql(set())

    def test_exclusion_params_order(self):
        cur = _FakeCursor()
        bpd.select_candidates(cur, 25, {_R1, _R2})
        _, params = cur.executed[0]
        assert params[0] == sorted([_R1, _R2]) or set(params[0]) == {_R1, _R2}
        assert params[1] == 25

    def test_malformed_json_fails_closed(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            bpd.load_exclusion_ids([str(bad)])

    def test_missing_results_array_fails_closed(self, tmp_path):
        bad = _artifact_dict(tmp_path, "bad.json", {"results": []})
        with pytest.raises(SystemExit):
            bpd.load_exclusion_ids([bad])

    def test_missing_or_invalid_id_fails_closed(self, tmp_path):
        no_id = _artifact(tmp_path, "a.json", [{"classification": "SUCCESS"}])
        bad_id = _artifact(tmp_path, "b.json", [{"id": "not-a-uuid"}])
        for path in (no_id, bad_id):
            with pytest.raises(SystemExit):
                bpd.load_exclusion_ids([path])

    def test_exclusion_loads_make_no_llm_calls(self, tmp_path, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("no LLM during exclusion loading")

        monkeypatch.setattr(bpd, "extract_opportunities_with_llm", boom)
        art = _artifact(tmp_path, "a.json", [{"id": _R1}])
        assert bpd.load_exclusion_ids([art]) == {_R1}

    def test_apply_path_ignores_exclusion(self, monkeypatch, tmp_path):
        """--exclude-results must not weaken or interfere with --apply."""
        called = {"apply": False}
        monkeypatch.setattr(bpd, "cmd_apply", lambda a: called.__setitem__("apply", True))
        art = _artifact(tmp_path, "res.json", [{"id": _R1}])
        monkeypatch.setattr(
            "sys.argv",
            ["backfill", "--apply", "--results", art, "--exclude-results", art],
        )
        bpd.main()
        assert called["apply"]

    def test_exclusion_excludes_prior_batch_ids_from_query(self, tmp_path):
        """SQL-level proof: excluded IDs are filtered before ordering/limit."""
        art = _artifact(tmp_path, "b1.json", [{"id": _R1}, {"id": _R2}])
        excluded = bpd.load_exclusion_ids([art])
        cur = _FakeCursor()
        bpd.select_candidates(cur, 25, excluded)
        sql, params = cur.executed[0]
        assert "id <> ALL(%s::uuid[])" in sql
        assert params[0] == [_R1, _R2] or sorted(params[0]) == sorted([_R1, _R2])


def _artifact_dict(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


class _FakeCursor:
    description = []

    def __init__(self, rowcount=1):
        self.executed = []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.rowcount = 1

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _apply_args(tmp_path, results, ids=None):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results))
    return bpd.argparse.Namespace(
        results=str(path), ids=ids, apply=True, limit=10,
        allow_over_limit=False, out="x",
    )


class TestApplyPath:
    REVIEWED = (
        "The Workforce Development Sequence Scholarship provides financial "
        "assistance to students enrolling in an approved non-credit "
        "certificate program."
    )

    def _results(self, desc=None):
        return [{
            "id": "31618136-0000-0000-0000-000000000000",
            "title": "Workforce Development Sequence Scholarship",
            "provider": "Maryland HEC",
            "classification": bpd.OUTCOME_SUCCESS,
            "public_description": desc if desc is not None else self.REVIEWED,
        }]

    def test_apply_writes_artifact_verbatim_with_null_guard(
        self, monkeypatch, tmp_path
    ):
        cur = _FakeCursor()
        monkeypatch.setattr(
            bpd.psycopg, "connect", lambda url: _FakeConn(cur)
        )
        monkeypatch.setenv("TARGET_DATABASE_URL", STAGING_URL)
        bpd.cmd_apply(_apply_args(tmp_path, self._results()))
        assert len(cur.executed) == 1
        sql, params = cur.executed[0]
        assert "public_description IS NULL" in sql          # no-overwrite guard
        assert sql.count("SET") == 1 and "UPDATE scholarships" in sql
        assert params[0] == self.REVIEWED                    # verbatim text
        assert params[1] == "31618136-0000-0000-0000-000000000000"

    def test_non_success_records_never_written(self, monkeypatch, tmp_path):
        cur = _FakeCursor()
        monkeypatch.setattr(bpd.psycopg, "connect", lambda url: _FakeConn(cur))
        monkeypatch.setenv("TARGET_DATABASE_URL", STAGING_URL)
        results = self._results() + [
            {"id": "x1", "classification": bpd.OUTCOME_LOW_INFORMATION,
             "public_description": None},
            {"id": "x2", "classification": bpd.OUTCOME_INSUFFICIENT,
             "public_description": None},
        ]
        bpd.cmd_apply(_apply_args(tmp_path, results))
        assert len(cur.executed) == 1  # only the SUCCESS row


class TestAlreadyDescribedAndRetry:
    def test_auth_failure_aborts_run(self, monkeypatch):
        async def fake_attempt(row):
            return {"id": row["id"]}, bpd.OUTCOME_LLM_AUTH, None

        monkeypatch.setattr(bpd, "_attempt_for", fake_attempt)
        with pytest.raises(bpd._AuthAbort):
            asyncio.run(bpd.generate_for({"id": "x", "title": "t",
                                          "provider": "p", "source_url": "u"}))

    def test_bounded_retry_on_rate_limit(self, monkeypatch):
        calls = {"n": 0}

        async def fake_attempt(row):
            calls["n"] += 1
            return {"id": row["id"]}, bpd.OUTCOME_LLM_RATE_LIMIT, None

        monkeypatch.setattr(bpd, "_attempt_for", fake_attempt)
        monkeypatch.setattr(bpd.time, "sleep", lambda s: None)
        out = asyncio.run(
            bpd.generate_for({"id": "x", "title": "t",
                              "provider": "p", "source_url": "u"})
        )
        assert calls["n"] == 1 + bpd._MAX_RETRIES          # bounded, not infinite
        assert out["classification"] == bpd.OUTCOME_LLM_RATE_LIMIT
        assert len(out["attempts"]) == calls["n"]

    def test_no_retry_on_grounding_rejection(self, monkeypatch):
        calls = {"n": 0}

        async def fake_attempt(row):
            calls["n"] += 1
            return {"id": row["id"]}, bpd.OUTCOME_GROUNDING, None

        monkeypatch.setattr(bpd, "_attempt_for", fake_attempt)
        monkeypatch.setattr(bpd.time, "sleep", lambda s: None)
        asyncio.run(bpd.generate_for({"id": "x", "title": "t",
                                      "provider": "p", "source_url": "u"}))
        assert calls["n"] == 1

    def test_no_retry_when_target_not_isolated(self, monkeypatch):
        calls = {"n": 0}

        async def fake_attempt(row):
            calls["n"] += 1
            return {"id": row["id"]}, bpd.OUTCOME_NOT_ISOLATED, None

        monkeypatch.setattr(bpd, "_attempt_for", fake_attempt)
        asyncio.run(bpd.generate_for({"id": "x", "title": "t",
                                      "provider": "p", "source_url": "u"}))
        assert calls["n"] == 1

    def test_already_described_skipped_in_dry_run(self, monkeypatch, tmp_path):
        """Populated rows (the six pilot records) are classified and never
        sent to the fetch/LLM path."""
        row = {
            "id": "fcc05c0a-0000-0000-0000-000000000000",
            "title": "Minudri", "provider": "ALA",
            "source_url": "https://x.example", "_has_description": True,
        }

        async def boom(r):
            raise AssertionError("generate_for must not run for populated rows")

        monkeypatch.setattr(bpd, "generate_for", boom)
        cur = _FakeCursor()
        cur.description = []  # unused for --ids path

        class Cur(_FakeCursor):
            def execute(self, sql, params=None):
                pass

            def fetchall(self):
                return [tuple(row.get(c, None) for c in (
                    "id", "title", "provider", "source_url", "portal_url",
                    "award_amount", "deadline", "verification_status",
                    "lifecycle_status", "_has_description"))]

            @property
            def description(self):
                class D:
                    def __init__(self, name):
                        self.name = name
                return [D(c) for c in (
                    "id", "title", "provider", "source_url", "portal_url",
                    "award_amount", "deadline", "verification_status",
                    "lifecycle_status", "_has_description")]

        conn = _FakeConn(Cur())
        monkeypatch.setattr(bpd.psycopg, "connect", lambda url: conn)
        monkeypatch.setenv("TARGET_DATABASE_URL", STAGING_URL)
        args = bpd.argparse.Namespace(
            ids=["fcc05c0a-0000-0000-0000-000000000000"], limit=10,
            out=str(tmp_path / "r.json"),
        )
        asyncio.run(bpd.cmd_dry_run(args))
        results = json.loads((tmp_path / "r.json").read_text())
        assert results[0]["classification"] == bpd.OUTCOME_ALREADY
        assert results[0]["public_description"] is None
