-- Migration 005: Add metro_restrictions array to scholarships
-- Stores Top-20 MSA names or CBSA codes for metro-level residency targeting.

alter table scholarships
    add column if not exists metro_restrictions text[] default '{}';
