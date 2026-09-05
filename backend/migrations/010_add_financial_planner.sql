-- Migration 010: Add StudentCollegeBudget table + planner fields to user_scholarships

-- Add is_planned and target_submission_date to user_scholarships
ALTER TABLE user_scholarships
    ADD COLUMN IF NOT EXISTS is_planned BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS target_submission_date DATE;

-- Create student_college_budgets table
CREATE TABLE IF NOT EXISTS student_college_budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    -- Direct educational costs
    tuition_fees INTEGER DEFAULT 0,
    books_supplies INTEGER DEFAULT 0,
    clinical_lab_fees INTEGER DEFAULT 0,
    -- Living & personal costs
    housing_rent INTEGER DEFAULT 0,
    food_groceries INTEGER DEFAULT 0,
    utilities_wifi INTEGER DEFAULT 0,
    transportation INTEGER DEFAULT 0,
    health_insurance INTEGER DEFAULT 0,
    personal_misc INTEGER DEFAULT 0,
    -- Income / resources
    family_contribution INTEGER DEFAULT 0,
    work_study_wages INTEGER DEFAULT 0,
    other_grants INTEGER DEFAULT 0,
    -- Loan configuration
    program_years INTEGER DEFAULT 4,
    interest_rate FLOAT DEFAULT 7.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id)
);
