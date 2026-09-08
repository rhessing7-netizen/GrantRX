-- Migration 018: Add has_completed_tour column to profiles.
--
-- Tracks whether the user has completed the interactive product walkthrough.
-- Used in combination with the localStorage flag on the frontend to decide
-- whether to auto-start the driver.js onboarding tour.

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS has_completed_tour BOOLEAN DEFAULT FALSE;
