"""Unit tests for the Financial Planner calculation engine.

Tests verify:
- Budget total computation (direct educational, living/personal, COA)
- Net unfunded annual calculation
- 10-year amortization formula (monthly payment, lifetime interest)
- Planning goals (3x cushion, 5x safety buffer, progress percentage)
- Edge cases (zero expenses, zero interest, fully funded)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.main import _compute_financial_planner
from app.models.models import StudentCollegeBudget
from app.schemas.schemas import FinancialPlannerOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_budget(**kwargs) -> StudentCollegeBudget:
    """Create a StudentCollegeBudget-like object with defaults."""
    defaults = {
        "tuition_fees": 0,
        "books_supplies": 0,
        "clinical_lab_fees": 0,
        "housing_rent": 0,
        "food_groceries": 0,
        "utilities_wifi": 0,
        "transportation": 0,
        "health_insurance": 0,
        "personal_misc": 0,
        "family_contribution": 0,
        "work_study_wages": 0,
        "other_grants": 0,
        "program_years": 4,
        "interest_rate": 7.5,
    }
    defaults.update(kwargs)
    obj = MagicMock(spec=StudentCollegeBudget)
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# Tests: budget totals
# ---------------------------------------------------------------------------


class TestBudgetTotals:
    def test_direct_educational_sum(self):
        budget = _make_budget(tuition_fees=20000, books_supplies=1500, clinical_lab_fees=500)
        result = _compute_financial_planner(budget, 0)
        assert result.total_direct_educational == 22000

    def test_living_personal_sum(self):
        budget = _make_budget(
            housing_rent=12000, food_groceries=6000, utilities_wifi=1200,
            transportation=2000, health_insurance=3000, personal_misc=1000,
        )
        result = _compute_financial_planner(budget, 0)
        assert result.total_living_personal == 25200

    def test_total_annual_expenses_coa(self):
        budget = _make_budget(
            tuition_fees=20000, books_supplies=1500,
            housing_rent=12000, food_groceries=6000,
        )
        result = _compute_financial_planner(budget, 0)
        assert result.total_annual_expenses == 39500

    def test_zero_expenses(self):
        budget = _make_budget()
        result = _compute_financial_planner(budget, 0)
        assert result.total_annual_expenses == 0
        assert result.net_unfunded_annual == 0
        assert result.estimated_total_debt == 0


# ---------------------------------------------------------------------------
# Tests: net unfunded & income
# ---------------------------------------------------------------------------


class TestNetUnfunded:
    def test_net_unfunded_with_income(self):
        budget = _make_budget(
            tuition_fees=30000, housing_rent=10000,
            family_contribution=5000, work_study_wages=3000,
        )
        result = _compute_financial_planner(budget, 0)
        # COA = 40000, income = 8000, unfunded = 32000
        assert result.total_non_loan_income == 8000
        assert result.net_unfunded_annual == 32000

    def test_net_unfunded_with_scholarships(self):
        budget = _make_budget(tuition_fees=30000, housing_rent=10000)
        result = _compute_financial_planner(budget, 15000)
        # COA = 40000, scholarships = 15000, unfunded = 25000
        assert result.total_planned_scholarships == 15000
        assert result.net_unfunded_annual == 25000

    def test_fully_funded_no_deficit(self):
        budget = _make_budget(
            tuition_fees=20000,
            family_contribution=15000, other_grants=5000,
        )
        result = _compute_financial_planner(budget, 0)
        # COA = 20000, income = 20000, unfunded = 0
        assert result.net_unfunded_annual == 0
        assert result.estimated_total_debt == 0
        assert result.monthly_loan_payment == 0

    def test_surplus_clamped_to_zero(self):
        budget = _make_budget(
            tuition_fees=10000,
            family_contribution=20000,
        )
        result = _compute_financial_planner(budget, 0)
        # COA = 10000, income = 20000 — surplus, but unfunded clamped to 0
        assert result.net_unfunded_annual == 0


# ---------------------------------------------------------------------------
# Tests: loan amortization
# ---------------------------------------------------------------------------


class TestLoanAmortization:
    def test_monthly_payment_calculation(self):
        # Principal = 40000 * 4 = 160000, rate = 7.5% / 12 = 0.00625, 120 months
        budget = _make_budget(
            tuition_fees=40000,
            program_years=4,
            interest_rate=7.5,
        )
        result = _compute_financial_planner(budget, 0)
        # M = P * (r * (1+r)^n) / ((1+r)^n - 1)
        # P = 160000, r = 0.00625, n = 120
        import math
        r = 0.00625
        n = 120
        P = 160000
        expected = P * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        assert abs(result.monthly_loan_payment - round(expected, 2)) < 0.01

    def test_total_debt_is_principal(self):
        budget = _make_budget(
            tuition_fees=25000,
            program_years=4,
        )
        result = _compute_financial_planner(budget, 0)
        # Principal = 25000 * 4 = 100000
        assert result.estimated_total_debt == 100000.0

    def test_lifetime_interest_positive(self):
        budget = _make_budget(
            tuition_fees=25000,
            program_years=4,
            interest_rate=7.5,
        )
        result = _compute_financial_planner(budget, 0)
        assert result.total_lifetime_interest > 0

    def test_zero_interest_monthly_payment(self):
        budget = _make_budget(
            tuition_fees=12000,
            program_years=4,
            interest_rate=0.0,
        )
        result = _compute_financial_planner(budget, 0)
        # Principal = 48000, 120 months, 0% → 48000/120 = 400
        assert result.monthly_loan_payment == 400.0
        assert result.total_lifetime_interest == 0.0

    def test_zero_principal_no_payment(self):
        budget = _make_budget(
            tuition_fees=10000,
            family_contribution=10000,
            interest_rate=7.5,
        )
        result = _compute_financial_planner(budget, 0)
        assert result.estimated_total_debt == 0
        assert result.monthly_loan_payment == 0
        assert result.total_lifetime_interest == 0


# ---------------------------------------------------------------------------
# Tests: planning goals
# ---------------------------------------------------------------------------


class TestPlanningGoals:
    def test_three_x_cushion(self):
        budget = _make_budget(tuition_fees=20000, housing_rent=10000)
        result = _compute_financial_planner(budget, 0)
        # COA = 30000, 3x = 90000
        assert result.three_x_cushion == 90000

    def test_five_x_safety_buffer(self):
        budget = _make_budget(tuition_fees=20000, housing_rent=10000)
        result = _compute_financial_planner(budget, 0)
        # COA = 30000, 5x = 150000
        assert result.five_x_safety_buffer == 150000

    def test_cushion_progress_pct(self):
        budget = _make_budget(
            tuition_fees=20000, housing_rent=10000,
            family_contribution=15000,
        )
        result = _compute_financial_planner(budget, 15000)
        # COA = 30000, 3x = 90000
        # Funding = 15000 (scholarships) + 15000 (income) = 30000
        # Progress = 30000 / 90000 * 100 = 33.3%
        assert abs(result.cushion_progress_pct - 33.3) < 0.1

    def test_cushion_progress_zero_coa(self):
        budget = _make_budget()
        result = _compute_financial_planner(budget, 0)
        assert result.cushion_progress_pct == 0.0

    def test_cushion_progress_fully_funded(self):
        budget = _make_budget(
            tuition_fees=10000, housing_rent=5000,
            family_contribution=30000,
        )
        result = _compute_financial_planner(budget, 20000)
        # COA = 15000, 3x = 45000
        # Funding = 20000 + 30000 = 50000
        # Progress = 50000 / 45000 * 100 = 111.1%
        assert result.cushion_progress_pct > 100


# ---------------------------------------------------------------------------
# Tests: return type
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_financial_planner_out(self):
        budget = _make_budget(tuition_fees=10000)
        result = _compute_financial_planner(budget, 5000)
        assert isinstance(result, FinancialPlannerOut)
        assert result.budget.tuition_fees == 10000
