-- Migration 003: Add user identity and consent fields to profiles
-- Adds full_name, email, terms/privacy acceptance timestamps, and marketing opt-in.

alter table profiles
    add column if not exists full_name text,
    add column if not exists email text,
    add column if not exists terms_accepted_at timestamptz,
    add column if not exists privacy_accepted_at timestamptz,
    add column if not exists marketing_opt_in boolean default false,
    add column if not exists marketing_opt_in_at timestamptz;
