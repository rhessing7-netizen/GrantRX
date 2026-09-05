"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { FinancialPlanner, StudentCollegeBudgetUpdate } from "@/lib/types";

function fmt(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function money(n: number): string {
  return `$${fmt(n)}`;
}

// Budget field configuration for the accordion sections
const DIRECT_EDUCATIONAL_FIELDS: { key: keyof StudentCollegeBudgetUpdate; label: string }[] = [
  { key: "tuition_fees", label: "Tuition & Fees" },
  { key: "books_supplies", label: "Books & Supplies" },
  { key: "clinical_lab_fees", label: "Clinical/Lab Fees" },
];

const LIVING_PERSONAL_FIELDS: { key: keyof StudentCollegeBudgetUpdate; label: string }[] = [
  { key: "housing_rent", label: "Housing & Rent" },
  { key: "food_groceries", label: "Food & Groceries" },
  { key: "utilities_wifi", label: "Utilities & Wi-Fi" },
  { key: "transportation", label: "Transportation" },
  { key: "health_insurance", label: "Health Insurance" },
  { key: "personal_misc", label: "Personal / Misc" },
];

const INCOME_FIELDS: { key: keyof StudentCollegeBudgetUpdate; label: string }[] = [
  { key: "family_contribution", label: "Family Contribution" },
  { key: "work_study_wages", label: "Work-Study Wages" },
  { key: "other_grants", label: "Other Grants" },
];

export function CollegeFinancialPlanner() {
  const [planner, setPlanner] = useState<FinancialPlanner | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSection, setOpenSection] = useState<string | null>("direct");

  // Local editable budget state
  const [budget, setBudget] = useState<Record<string, number>>({});
  const [programYears, setProgramYears] = useState(4);
  const [interestRate, setInterestRate] = useState(7.5);

  const loadPlanner = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getFinancialPlanner();
      setPlanner(data);
      setBudget({
        tuition_fees: data.budget.tuition_fees,
        books_supplies: data.budget.books_supplies,
        clinical_lab_fees: data.budget.clinical_lab_fees,
        housing_rent: data.budget.housing_rent,
        food_groceries: data.budget.food_groceries,
        utilities_wifi: data.budget.utilities_wifi,
        transportation: data.budget.transportation,
        health_insurance: data.budget.health_insurance,
        personal_misc: data.budget.personal_misc,
        family_contribution: data.budget.family_contribution,
        work_study_wages: data.budget.work_study_wages,
        other_grants: data.budget.other_grants,
      });
      setProgramYears(data.budget.program_years);
      setInterestRate(data.budget.interest_rate);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load financial planner";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlanner();
  }, [loadPlanner]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const update: StudentCollegeBudgetUpdate = {
        ...budget,
        program_years: programYears,
        interest_rate: interestRate,
      };
      const data = await api.updateFinancialPlanner(update);
      setPlanner(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save budget";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const updateField = (key: string, value: number) => {
    setBudget((prev) => ({ ...prev, [key]: value }));
  };

  // Local computed totals (for live preview before saving)
  const localDirect = DIRECT_EDUCATIONAL_FIELDS.reduce(
    (sum, f) => sum + (budget[f.key as string] || 0), 0,
  );
  const localLiving = LIVING_PERSONAL_FIELDS.reduce(
    (sum, f) => sum + (budget[f.key as string] || 0), 0,
  );
  const localIncome = INCOME_FIELDS.reduce(
    (sum, f) => sum + (budget[f.key as string] || 0), 0,
  );
  const localCOA = localDirect + localLiving;

  // Use live local values if available, fall back to server data
  const totalDirect = planner ? planner.total_direct_educational : localDirect;
  const totalLiving = planner ? planner.total_living_personal : localLiving;
  const totalCOA = planner ? planner.total_annual_expenses : localCOA;
  const totalIncome = planner ? planner.total_non_loan_income : localIncome;
  const plannedScholarships = planner?.total_planned_scholarships ?? 0;
  const netUnfunded = planner?.net_unfunded_annual ?? Math.max(0, localCOA - localIncome);
  const totalDebt = planner?.estimated_total_debt ?? 0;
  const monthlyPayment = planner?.monthly_loan_payment ?? 0;
  const lifetimeInterest = planner?.total_lifetime_interest ?? 0;
  const threeXCushion = planner?.three_x_cushion ?? totalCOA * 3;
  const cushionPct = planner?.cushion_progress_pct ?? 0;

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="font-serif text-3xl font-bold text-textPrimary">
          Financial Planner
        </h1>
        <div className="rounded-2xl bg-cardBg p-8 text-center text-textSecondary">
          Loading your financial planner…
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl font-bold text-textPrimary">
        Financial Planner
      </h1>
      <p className="text-sm text-textSecondary">
        Plan your college budget, track funding gaps, and simulate loan impact over a 10-year repayment period.
      </p>

      {error && (
        <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Top: 3x Application Cushion Progress Meter */}
      <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-serif text-lg font-semibold text-textPrimary">
              3x Application Cushion
            </h2>
            <p className="mt-0.5 text-xs text-textSecondary">
              Funding progress toward 3× your annual Cost of Attendance
            </p>
          </div>
          <span className={`text-2xl font-bold ${cushionPct >= 100 ? "text-aquamarine" : cushionPct >= 50 ? "text-blueEnergy" : "text-textSecondary"}`}>
            {cushionPct.toFixed(1)}%
          </span>
        </div>
        <div className="mt-4 h-4 overflow-hidden rounded-full bg-slate-100 p-0.5">
          <div
            className="h-full rounded-full bg-gradient-to-r from-skyAqua via-blueEnergy to-aquamarine transition-all duration-700 ease-out"
            style={{ width: `${Math.min(100, cushionPct)}%` }}
          />
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-textSecondary">
          <span>Funded: {money(plannedScholarships + totalIncome)}</span>
          <span>Goal: {money(threeXCushion)}</span>
        </div>
      </section>

      {/* 3-column dashboard */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">

        {/* Col 1: Budget Sheet (collapsible accordion) */}
        <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-5">
          <h2 className="font-serif text-base font-semibold text-textPrimary mb-4">
            Annual Budget Sheet
          </h2>

          {/* Direct School Costs */}
          <AccordionSection
            title="Direct School Costs"
            total={totalDirect}
            isOpen={openSection === "direct"}
            onToggle={() => setOpenSection(openSection === "direct" ? null : "direct")}
          >
            {DIRECT_EDUCATIONAL_FIELDS.map((f) => (
              <BudgetInput
                key={f.key}
                label={f.label}
                value={budget[f.key as string] ?? 0}
                onChange={(v) => updateField(f.key as string, v)}
              />
            ))}
          </AccordionSection>

          {/* Living & Housing */}
          <AccordionSection
            title="Living & Housing"
            total={totalLiving}
            isOpen={openSection === "living"}
            onToggle={() => setOpenSection(openSection === "living" ? null : "living")}
          >
            {LIVING_PERSONAL_FIELDS.map((f) => (
              <BudgetInput
                key={f.key}
                label={f.label}
                value={budget[f.key as string] ?? 0}
                onChange={(v) => updateField(f.key as string, v)}
              />
            ))}
          </AccordionSection>

          {/* Total COA */}
          <div className="mt-4 flex items-center justify-between rounded-xl bg-surfaceBg px-4 py-3">
            <span className="text-sm font-medium text-textSecondary">Total Annual COA</span>
            <span className="font-serif text-lg font-bold text-textPrimary">{money(totalCOA)}</span>
          </div>

          <button
            onClick={handleSave}
            disabled={saving}
            className="mt-4 w-full rounded-full bg-crayolaBlue px-4 py-2 text-sm font-medium text-surfaceBg hover:bg-blueEnergy disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Budget"}
          </button>
        </section>

        {/* Col 2: Funding & Inflows */}
        <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-5">
          <h2 className="font-serif text-base font-semibold text-textPrimary mb-4">
            Funding & Inflows
          </h2>

          <AccordionSection
            title="Income & Resources"
            total={totalIncome}
            isOpen={openSection === "income"}
            onToggle={() => setOpenSection(openSection === "income" ? null : "income")}
          >
            {INCOME_FIELDS.map((f) => (
              <BudgetInput
                key={f.key}
                label={f.label}
                value={budget[f.key as string] ?? 0}
                onChange={(v) => updateField(f.key as string, v)}
              />
            ))}
          </AccordionSection>

          {/* Planned scholarships */}
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between rounded-xl bg-aquamarine/10 border border-aquamarine/30 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-textPrimary">Planned Scholarships</p>
                <p className="text-xs text-textSecondary">From saved & tracked awards</p>
              </div>
              <span className="font-serif text-lg font-bold text-textPrimary">
                {money(plannedScholarships)}
              </span>
            </div>

            {/* Net deficit */}
            <div className={`flex items-center justify-between rounded-xl px-4 py-3 ${
              netUnfunded > 0
                ? "bg-red-50 border border-red-200"
                : "bg-aquamarine/10 border border-aquamarine/30"
            }`}>
              <div>
                <p className="text-sm font-medium text-textPrimary">
                  {netUnfunded > 0 ? "Net Unfunded (Annual)" : "Surplus (Annual)"}
                </p>
                <p className="text-xs text-textSecondary">COA − (Scholarships + Income)</p>
              </div>
              <span className={`font-serif text-lg font-bold ${
                netUnfunded > 0 ? "text-red-600" : "text-aquamarine"
              }`}>
                {money(Math.abs(netUnfunded))}
              </span>
            </div>
          </div>
        </section>

        {/* Col 3: Loan Breakdown & Debt Impact */}
        <section className="bg-white/95 backdrop-blur-md rounded-2xl border border-slate-200 shadow-xs p-5">
          <h2 className="font-serif text-base font-semibold text-textPrimary mb-4">
            Loan Breakdown & Debt Impact
          </h2>

          {/* Loan config inputs */}
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-textSecondary">
                Program Years
              </label>
              <input
                type="number"
                min={1}
                max={10}
                value={programYears}
                onChange={(e) => setProgramYears(parseInt(e.target.value) || 4)}
                className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-3 py-2 text-sm text-textPrimary"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-textSecondary">
                Interest Rate (%)
              </label>
              <input
                type="number"
                step="0.1"
                min={0}
                max={20}
                value={interestRate}
                onChange={(e) => setInterestRate(parseFloat(e.target.value) || 7.5)}
                className="mt-1 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg px-3 py-2 text-sm text-textPrimary"
              />
            </div>
          </div>

          {/* Computed loan metrics */}
          <div className="mt-4 space-y-3">
            <MetricCard
              label="Estimated Total Debt"
              sublabel={`${programYears}yr × unfunded annual`}
              value={money(totalDebt)}
              accent="text-textPrimary"
            />
            <MetricCard
              label="Monthly Payment"
              sublabel="10-year (120 mo) amortization"
              value={money(monthlyPayment)}
              accent="text-blueEnergy"
            />
            <MetricCard
              label="Lifetime Interest"
              sublabel="Total interest over 10 years"
              value={money(lifetimeInterest)}
              accent="text-red-600"
            />
          </div>

          {/* 5x safety buffer */}
          <div className="mt-4 rounded-xl bg-surfaceBg px-4 py-3">
            <p className="text-xs text-textSecondary">5× Safety Buffer</p>
            <p className="mt-1 font-serif text-lg font-bold text-textPrimary">
              {money(planner?.five_x_safety_buffer ?? totalCOA * 5)}
            </p>
          </div>

          <button
            onClick={handleSave}
            disabled={saving}
            className="mt-4 w-full rounded-full bg-crayolaBlue px-4 py-2 text-sm font-medium text-surfaceBg hover:bg-blueEnergy disabled:opacity-50"
          >
            {saving ? "Recalculating…" : "Recalculate Loan Impact"}
          </button>
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AccordionSection({
  title,
  total,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  total: number;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-slate-100 last:border-0">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between py-3 text-left"
      >
        <span className="text-sm font-medium text-textPrimary">{title}</span>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-textSecondary">{money(total)}</span>
          <svg
            className={`h-4 w-4 text-textSecondary transition-transform ${isOpen ? "rotate-180" : ""}`}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      {isOpen && <div className="space-y-2 pb-3">{children}</div>}
    </div>
  );
}

function BudgetInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="text-xs text-textSecondary flex-1">{label}</label>
      <div className="relative w-32">
        <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-textSecondary">$</span>
        <input
          type="number"
          min={0}
          value={value}
          onChange={(e) => onChange(parseInt(e.target.value) || 0)}
          className="w-full rounded-lg border border-textSecondary/20 bg-surfaceBg pl-5 pr-2 py-1.5 text-xs text-textPrimary"
        />
      </div>
    </div>
  );
}

function MetricCard({
  label,
  sublabel,
  value,
  accent,
}: {
  label: string;
  sublabel: string;
  value: string;
  accent: string;
}) {
  return (
    <div className="rounded-xl bg-surfaceBg px-4 py-3">
      <p className="text-xs text-textSecondary">{label}</p>
      <p className={`mt-1 font-serif text-xl font-bold ${accent}`}>{value}</p>
      <p className="mt-0.5 text-xs text-textSecondary/60">{sublabel}</p>
    </div>
  );
}
