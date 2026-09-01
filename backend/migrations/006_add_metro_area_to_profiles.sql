-- Migration 006: Add metro_area to profiles
-- Stores the student's metropolitan area (MSA name or metro slug) for
-- metro-level scholarship eligibility matching.

alter table profiles
    add column if not exists metro_area text;
