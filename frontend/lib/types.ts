export type ClinicalDiscipline =
  | "pharmacy"
  | "medicine"
  | "nursing"
  | "therapeutics_rehab"
  | "diagnostic_imaging"
  | "public_health_emergency";

export type AppStatus =
  | "saved"
  | "in_progress"
  | "submitted"
  | "awarded"
  | "archived";

export type SubscriptionTier = "free" | "premium";

export interface Profile {
  id: string;
  // Multi-select arrays (new preferred fields)
  disciplines: string[];
  target_credentials: string[];
  // Legacy single-choice fields (kept for backward compatibility)
  primary_discipline: ClinicalDiscipline | null;
  target_credential: string | null;
  clinical_phase: string | null;
  gpa: number | null;
  state_residence: string | null;
  metro_area: string | null;
  sai_score: number | null;
  first_gen: boolean;
  minority_flag: boolean;
  professional_affiliations: string[];
  hobbies: string[];
  subscription_tier: SubscriptionTier;
  full_name: string | null;
  email: string | null;
  terms_accepted_at: string | null;
  privacy_accepted_at: string | null;
  marketing_opt_in: boolean;
  marketing_opt_in_at: string | null;
  searches_used_this_week: number;
  search_cycle_reset_at: string | null;
  feed_token: string | null;
  stripe_subscription_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProfileCreate {
  disciplines?: string[];
  target_credentials?: string[];
  primary_discipline?: ClinicalDiscipline;
  target_credential?: string;
  clinical_phase?: string;
  gpa?: number | null;
  state_residence?: string;
  metro_area?: string;
  sai_score?: number | null;
  first_gen?: boolean;
  minority_flag?: boolean;
  professional_affiliations?: string[];
  hobbies?: string[];
  subscription_tier?: SubscriptionTier;
  full_name?: string;
  email?: string;
  terms_accepted?: boolean;
  privacy_accepted?: boolean;
  marketing_opt_in?: boolean;
}

export interface ProfileUpdate {
  disciplines?: string[];
  target_credentials?: string[];
  primary_discipline?: ClinicalDiscipline;
  target_credential?: string;
  clinical_phase?: string;
  gpa?: number | null;
  state_residence?: string;
  metro_area?: string;
  sai_score?: number | null;
  first_gen?: boolean;
  minority_flag?: boolean;
  professional_affiliations?: string[];
  hobbies?: string[];
  subscription_tier?: SubscriptionTier;
  full_name?: string;
  email?: string;
  terms_accepted?: boolean;
  privacy_accepted?: boolean;
  marketing_opt_in?: boolean;
}

export interface MatchedScholarship {
  scholarship_id: string;
  title: string;
  provider: string;
  portal_url: string;
  award_amount: number;
  deadline: string;
  score: number;
  missing_criteria: string[];
  is_locked: boolean;
  masked_title: string | null;
  masked_provider: string | null;
  metro_restrictions: string[];
  eligible_disciplines?: string[];
}

export interface MatchedFeed {
  results: MatchedScholarship[];
  total: number;
  visible: number;
  tier: SubscriptionTier;
  searches_used_this_week: number;
  search_limit: number | null;
  reset_at: string;
}

export interface Usage {
  tier: SubscriptionTier;
  searches_used_this_week: number;
  search_limit: number | null;
  remaining: number | null;
  reset_at: string;
  is_premium: boolean;
}

export interface VaultDocument {
  name: string;
  url: string;
  uploaded_at?: string | null;
  type: string;
}

export interface ChecklistItem {
  id: string;
  text: string;
  completed: boolean;
}

export interface UserScholarship {
  id: string;
  user_id: string;
  scholarship_id: string;
  status: AppStatus;
  custom_deadline_reminder: string | null;
  user_notes: string | null;
  application_notes: string | null;
  documents: VaultDocument[];
  checklist: ChecklistItem[];
  scholarship?: ScholarshipOut;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScholarshipOut {
  id: string;
  title: string;
  provider: string;
  portal_url: string;
  award_amount: number;
  deadline: string;
  eligible_disciplines: ClinicalDiscipline[];
  eligible_credentials: string[];
  min_gpa: number;
  max_sai: number | null;
  state_restrictions: string[];
  metro_restrictions: string[];
  required_affiliations: string[];
  matching_tags: string[];
  is_archived: boolean;
  estimated_next_cycle: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface UserScholarshipCreate {
  scholarship_id: string;
  status?: AppStatus;
  custom_deadline_reminder?: string | null;
  user_notes?: string | null;
  application_notes?: string | null;
  documents?: VaultDocument[];
  checklist?: ChecklistItem[];
}

export interface UserScholarshipUpdate {
  status?: AppStatus;
  custom_deadline_reminder?: string | null;
  user_notes?: string | null;
  application_notes?: string | null;
  documents?: VaultDocument[];
  checklist?: ChecklistItem[];
}

export const DISCIPLINE_LABELS: Record<ClinicalDiscipline, string> = {
  pharmacy: "Pharmacy",
  medicine: "Medicine",
  nursing: "Nursing",
  therapeutics_rehab: "Therapeutics & Rehab",
  diagnostic_imaging: "Diagnostic Imaging",
  public_health_emergency: "Public Health & Emergency",
};

// ---------------------------------------------------------------------------
// Comprehensive healthcare discipline/major directory (multi-select)
// ---------------------------------------------------------------------------

export const DISCIPLINE_OPTIONS: string[] = [
  "Pharmacy (PharmD)",
  "Pre-Pharmacy",
  "Pharmaceutical Sciences",
  "Medicinal Chemistry",
  "Pharmacology & Toxicology",
  "Pharmacy Technician",
  "Medicine (MD)",
  "Osteopathic Medicine (DO)",
  "Pre-Med",
  "Podiatry (DPM)",
  "Chiropractic (DC)",
  "Naturopathic Medicine (ND)",
  "Nursing (BSN)",
  "Practical Nursing (LPN/LVN)",
  "Registered Nursing (ADN)",
  "Nurse Practitioner (MSN/FNP/AGNP)",
  "Nurse Anesthesia (CRNA)",
  "Nurse Midwifery (CNM)",
  "Doctor of Nursing Practice (DNP)",
  "Dentistry (DDS/DMD)",
  "Pre-Dental",
  "Dental Hygiene",
  "Dental Assisting",
  "Physician Assistant (PA/MPAS)",
  "Pre-PA",
  "Physical Therapy (DPT/PTA)",
  "Occupational Therapy (OTD/COTA)",
  "Speech-Language Pathology (MS-SLP)",
  "Audiology (AuD)",
  "Respiratory Therapy (RRT)",
  "Athletic Training (MSAT)",
  "Exercise Science/Kinesiology",
  "Public Health (MPH/DrPH)",
  "Health Administration (MHA)",
  "Health Informatics",
  "Medical Laboratory Science (MLS/MLT)",
  "Radiologic Technology / Imaging",
  "Sonography/Ultrasound",
  "Clinical Psychology (PsyD/PhD)",
  "Mental Health Counseling (LPC/LMHC)",
  "Clinical Social Work (MSW/LCSW)",
  "Dietetics & Clinical Nutrition (RD/RDN)",
  "Emergency Medical Services (EMT/Paramedic)",
  "Veterinary Medicine (DVM)",
  "Pre-Vet",
];

export const CREDENTIAL_OPTIONS: string[] = [
  "Certificate / Diploma",
  "Associate Degree (AS/AAS/ADN)",
  "Bachelor's Degree (BS/BA/BSN)",
  "Master's Degree (MS/MSN/MPAS/MPH/MHA/MSW)",
  "Doctoral / Professional Practice (PharmD, MD, DO, DDS, DMD, DNP, DPT, OTD, AuD, DPM, DVM, PsyD, PhD, DrPH)",
];

export const AFFILIATION_OPTIONS = [
  "APhA",
  "AMA",
  "AACN",
  "ASHP",
  "APTA",
  "ANA",
  "SNMA",
  "LULAC",
  "NSNA",
];

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export interface CalendarEvent {
  tracking_id: string;
  scholarship_id: string;
  title: string;
  provider: string;
  deadline: string;
  status: AppStatus;
  award_amount: number;
  custom_deadline_reminder: string | null;
  user_notes: string | null;
}

export interface CalendarFeedInfo {
  feed_url: string;
  feed_token: string;
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------

export type BillingPlan = "monthly" | "annual";

export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

// ---------------------------------------------------------------------------
// Financial Planner
// ---------------------------------------------------------------------------

export interface StudentCollegeBudget {
  tuition_fees: number;
  books_supplies: number;
  clinical_lab_fees: number;
  housing_rent: number;
  food_groceries: number;
  utilities_wifi: number;
  transportation: number;
  health_insurance: number;
  personal_misc: number;
  family_contribution: number;
  work_study_wages: number;
  other_grants: number;
  program_years: number;
  interest_rate: number;
}

export interface StudentCollegeBudgetUpdate {
  tuition_fees?: number;
  books_supplies?: number;
  clinical_lab_fees?: number;
  housing_rent?: number;
  food_groceries?: number;
  utilities_wifi?: number;
  transportation?: number;
  health_insurance?: number;
  personal_misc?: number;
  family_contribution?: number;
  work_study_wages?: number;
  other_grants?: number;
  program_years?: number;
  interest_rate?: number;
}

export interface FinancialPlanner {
  budget: StudentCollegeBudget;
  total_direct_educational: number;
  total_living_personal: number;
  total_annual_expenses: number;
  total_non_loan_income: number;
  total_planned_scholarships: number;
  net_unfunded_annual: number;
  estimated_total_debt: number;
  monthly_loan_payment: number;
  total_lifetime_interest: number;
  three_x_cushion: number;
  five_x_safety_buffer: number;
  cushion_progress_pct: number;
}
