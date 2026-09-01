-- Migration 004: Add multi-select disciplines and target_credentials arrays
-- Converts single-choice primary_discipline and target_credential to
-- multi-select array columns (disciplines, target_credentials).
-- Old columns are retained for backward compatibility but made nullable.

-- Add new array columns
alter table profiles
    add column if not exists disciplines text[] default '{}',
    add column if not exists target_credentials text[] default '{}';

-- Make old columns nullable so users can skip onboarding fields
alter table profiles
    alter column primary_discipline drop not null,
    alter column gpa drop not null,
    alter column state_residence drop not null;

-- Migrate existing data: copy primary_discipline into disciplines array
update profiles
    set disciplines = array[primary_discipline::text]
    where primary_discipline is not null and (disciplines = '{}' or disciplines is null);

-- Migrate existing data: copy target_credential into target_credentials array
update profiles
    set target_credentials = array[target_credential]
    where target_credential is not null and (target_credentials = '{}' or target_credentials is null);

-- Also make scholarship eligible_disciplines nullable (already supports empty array = "any")
alter table scholarships
    alter column eligible_disciplines drop not null;
