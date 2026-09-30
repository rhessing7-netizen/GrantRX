-- Migration 027: Early-access / waitlist leads (R3).
--
-- Durable source-of-truth table for pre-launch acquisition. The EdFintia
-- database captures the lead BEFORE any email-marketing provider sync is
-- attempted, so an EmailOctopus outage can never lose a signup.
--
-- Design notes:
--   * email is stored normalized (trimmed + lowercased) and unique — repeat
--     submissions update profile/consent fields instead of creating
--     additional rows.
--   * Attribution fields hold FIRST-TOUCH values: referral_source,
--     referral_code, referred_by, utm_* and landing_page are distinct
--     concepts and are only filled while still empty.
--   * status doubles as the segment column ('waitlist' today; later values
--     such as student/parent/college/counselor/creator/campus_ambassador/
--     media/nonprofit/founding_user need no schema change).
--   * provider_sync_* tracks the EmailOctopus sync state for retry
--     (pending | synced | failed | skipped).
--
-- Additive and non-destructive; idempotent (safe to apply more than once).

CREATE TABLE IF NOT EXISTS waitlist_leads (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email                 TEXT NOT NULL,
    first_name            TEXT NOT NULL,
    audience_type         TEXT NOT NULL,  -- student | parent | college_staff | counselor | scholarship_organization | other
    education_type        TEXT,           -- undergraduate | graduate | professional | trade | other
    status                TEXT NOT NULL DEFAULT 'waitlist',
    referral_source       TEXT,
    referral_code         TEXT,
    referred_by           TEXT,
    utm_source            TEXT,
    utm_medium            TEXT,
    utm_campaign          TEXT,
    utm_content           TEXT,
    utm_term              TEXT,
    landing_page          TEXT,
    consent_timestamp     TIMESTAMPTZ NOT NULL,
    consent_source        TEXT NOT NULL,
    provider_sync_status  TEXT NOT NULL DEFAULT 'pending',  -- pending | synced | failed | skipped
    provider_synced_at    TIMESTAMPTZ,
    provider_last_error   TEXT,
    converted_to_user     BOOLEAN NOT NULL DEFAULT FALSE,
    converted_at          TIMESTAMPTZ,
    converted_user_id     UUID REFERENCES profiles(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One lead per normalized email address.
CREATE UNIQUE INDEX IF NOT EXISTS waitlist_leads_email_key
    ON waitlist_leads (email);

-- Reporting indexes: leads over time, audience/referral breakdowns,
-- provider-sync retry sweeps.
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_status
    ON waitlist_leads (status);
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_created_at
    ON waitlist_leads (created_at);
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_referral_source
    ON waitlist_leads (referral_source);
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_audience_type
    ON waitlist_leads (audience_type);
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_provider_sync_status
    ON waitlist_leads (provider_sync_status);
CREATE INDEX IF NOT EXISTS idx_waitlist_leads_utm_campaign
    ON waitlist_leads (utm_campaign);

-- Waitlist contact data is personal data and is only ever read/written by
-- the backend service role — no client-side access is permitted.
ALTER TABLE waitlist_leads ENABLE ROW LEVEL SECURITY;
