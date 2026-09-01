-- Migration 009: Add Document Vault fields to user_scholarships
--
-- application_notes: free-form notes for the application
-- documents: JSONB array of { name, url, uploaded_at, type }
-- checklist: JSONB array of { id, text, completed }

ALTER TABLE user_scholarships
    ADD COLUMN IF NOT EXISTS application_notes TEXT,
    ADD COLUMN IF NOT EXISTS documents JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS checklist JSONB DEFAULT '[]'::jsonb;
