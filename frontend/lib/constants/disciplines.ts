import type { ClinicalDiscipline } from "@/lib/types";

// ---------------------------------------------------------------------------
// Undergraduate Science & Health Major Taxonomy
//
// Categorized list of undergraduate majors that map to EdFintia clinical
// discipline enums for scholarship matching. Used by the OnboardingWizard
// and ProfileEditModal for major selection.
// ---------------------------------------------------------------------------

export interface MajorCategory {
  label: string;
  majors: string[];
}

export const MAJOR_CATEGORIES: MajorCategory[] = [
  {
    label: "Biological Sciences",
    majors: [
      "Biology",
      "Molecular & Cellular Biology",
      "Microbiology",
      "Genetics",
      "Neuroscience",
      "Botany / Plant Biology",
      "Zoology",
      "Ecology & Evolutionary Biology",
    ],
  },
  {
    label: "Chemical & Physical Sciences",
    majors: [
      "Chemistry",
      "Biochemistry",
      "Organic Chemistry",
      "Analytical Chemistry",
      "Physics",
      "Biophysics",
      "Astronomy / Astrophysics",
    ],
  },
  {
    label: "Earth & Environmental Sciences",
    majors: [
      "Geology / Earth Science",
      "Environmental Science",
      "Geophysics",
      "Oceanography",
      "Atmospheric Sciences / Meteorology",
    ],
  },
  {
    label: "Allied Health, Therapy & Kinesiology",
    majors: [
      "Exercise Science",
      "Kinesiology",
      "Pre-Physical Therapy",
      "Pre-Occupational Therapy",
      "Athletic Training",
      "Speech-Language Pathology",
      "Respiratory Therapy",
    ],
  },
  {
    label: "Public Health & Health Administration",
    majors: [
      "Public Health",
      "Health Sciences",
      "Global Health",
      "Epidemiology",
      "Healthcare Management / Administration",
      "Health Informatics",
      "Environmental Health",
    ],
  },
  {
    label: "Pre-Clinical & Nursing",
    majors: [
      "Pre-Medicine",
      "Pre-Nursing",
      "Pre-Pharmacy",
      "Pre-Dental",
      "Pre-Veterinary",
      "Pre-Physician Assistant",
      "Medical Laboratory Science",
      "Dental Hygiene",
      "Radiologic Technology",
    ],
  },
  {
    // C8: non-healthcare coverage — deliberately modest. Broad area labels
    // map to canonical area codes; "Other / Undecided" maps to
    // "interdisciplinary", not a guessed field.
    label: "Other Fields of Study",
    majors: [
      "Computer Science",
      "Engineering",
      "Business Administration",
      "Accounting",
      "Education / Teaching",
      "Psychology",
      "Social Work",
      "Communications",
      "Fine Arts / Design",
      "Law / Pre-Law",
      "Trades / Technical",
      "Agriculture",
      "Other / Undecided",
    ],
  },
];

// Flat list of all majors (for backward compatibility with MultiSelect)
export const ALL_MAJORS: string[] = MAJOR_CATEGORIES.flatMap((c) => c.majors);

// ---------------------------------------------------------------------------
// Major -> Clinical Discipline mapping
//
// Maps undergraduate science/health majors to the backend's
// ClinicalDiscipline enum values used for scholarship matching.
// ---------------------------------------------------------------------------

// Maps undergraduate major labels to canonical field-of-study codes.
// These MUST stay aligned with the backend registry
// (backend/scrapers/utils/taxonomy.py). Pre-C8 compatibility note: science
// majors that used to collapse into "medicine" now map to their real
// canonical codes; the backend's matching expansion preserves the
// pre-health eligibility behavior via compatibility edges.
const _MAJOR_TO_DISCIPLINE: Record<string, ClinicalDiscipline> = {
  // Pharmacy
  "Pre-Pharmacy": "pharmacy",

  // Medicine / Pre-clinical
  "Pre-Medicine": "medicine",
  "Pre-Dental": "dentistry",
  "Pre-Veterinary": "veterinary_medicine",
  "Pre-Physician Assistant": "physician_assistant",
  "Medical Laboratory Science": "medical_laboratory_science",

  // Biological sciences — real canonical code; backend compat edge keeps
  // medicine-eligibility (pre-health) matching.
  "Biology": "biological_sciences",
  "Molecular & Cellular Biology": "biological_sciences",
  "Microbiology": "biological_sciences",
  "Genetics": "biological_sciences",
  "Neuroscience": "biological_sciences",
  "Botany / Plant Biology": "biological_sciences",
  "Zoology": "biological_sciences",
  "Ecology & Evolutionary Biology": "biological_sciences",

  // Chemical & physical sciences — compat edge -> medicine.
  "Chemistry": "physical_sciences",
  "Biochemistry": "physical_sciences",
  "Organic Chemistry": "physical_sciences",
  "Analytical Chemistry": "physical_sciences",
  "Physics": "physical_sciences",
  "Biophysics": "physical_sciences",
  "Astronomy / Astrophysics": "physical_sciences",
  "Geology / Earth Science": "physical_sciences",
  "Geophysics": "physical_sciences",
  "Oceanography": "physical_sciences",
  "Atmospheric Sciences / Meteorology": "physical_sciences",

  // Nursing
  "Pre-Nursing": "nursing",

  // Therapeutics & Rehab
  "Exercise Science": "therapeutics_rehab",
  "Kinesiology": "therapeutics_rehab",
  "Pre-Physical Therapy": "therapeutics_rehab",
  "Pre-Occupational Therapy": "therapeutics_rehab",
  "Athletic Training": "therapeutics_rehab",
  "Speech-Language Pathology": "therapeutics_rehab",
  "Respiratory Therapy": "therapeutics_rehab",

  // Diagnostic Imaging
  "Radiologic Technology": "diagnostic_imaging",

  // Public Health & Emergency
  "Public Health": "public_health_emergency",
  "Global Health": "public_health_emergency",
  "Epidemiology": "public_health_emergency",
  "Healthcare Management / Administration": "public_health_emergency",
  "Health Informatics": "public_health_emergency",
  "Environmental Health": "public_health_emergency",
  "Environmental Science": "environmental_science",
  "Health Sciences": "health_professions",

  // Dental Hygiene — real code now; compat edge preserves medicine match.
  "Dental Hygiene": "dental_hygiene",

  // Other Fields of Study (C8)
  "Computer Science": "computer_science",
  "Engineering": "engineering",
  "Business Administration": "business_administration",
  "Accounting": "accounting",
  "Education / Teaching": "teaching_education",
  "Psychology": "psychology",
  "Social Work": "social_work",
  "Communications": "communications",
  "Fine Arts / Design": "design",
  "Law / Pre-Law": "law",
  "Trades / Technical": "trades_technical",
  "Agriculture": "agriculture",
  "Other / Undecided": "interdisciplinary",
};

/**
 * Map an undergraduate major string to its canonical field-of-study code
 * used by the backend for scholarship matching.
 *
 * Returns null for unrecognized values — an unknown field of study must
 * never be fabricated into a discipline (pre-C8 fell back to "medicine").
 */
export function mapMajorToClinicalDiscipline(major: string): ClinicalDiscipline | null {
  if (!major) return null;
  // Exact match
  if (major in _MAJOR_TO_DISCIPLINE) {
    return _MAJOR_TO_DISCIPLINE[major];
  }
  // Case-insensitive match
  const lower = major.toLowerCase().trim();
  for (const [key, val] of Object.entries(_MAJOR_TO_DISCIPLINE)) {
    if (key.toLowerCase() === lower) return val;
  }
  // Keyword-based fallback
  if (lower.includes("pharmacy")) return "pharmacy";
  if (lower.includes("nurs")) return "nursing";
  if (lower.includes("dental") || lower.includes("dentistry")) return "dentistry";
  if (lower.includes("physical therapy") || lower.includes("occupational therapy")
      || lower.includes("kinesi") || lower.includes("exercise")
      || lower.includes("athletic") || lower.includes("speech")
      || lower.includes("respiratory")) return "therapeutics_rehab";
  if (lower.includes("radiolog") || lower.includes("imaging")
      || lower.includes("sonograph")) return "diagnostic_imaging";
  if (lower.includes("public health") || lower.includes("epidemi")
      || lower.includes("health admin") || lower.includes("health inform")
      || lower.includes("global health") || lower.includes("environmental health")) {
    return "public_health_emergency";
  }
  if (lower.includes("computer") || lower.includes("software")) return "computer_science";
  if (lower.includes("engineer")) return "engineering";
  if (lower.includes("business") || lower.includes("accounting")
      || lower.includes("finance") || lower.includes("marketing")) return "business";
  if (lower.includes("teach") || lower.includes("education")) return "teaching_education";
  if (lower.includes("psych")) return "psychology";
  if (lower.includes("law") || lower.includes("legal")) return "law";
  if (lower.includes("agricultur")) return "agriculture";
  if (lower.includes("biolog") || lower.includes("microbio") || lower.includes("genetic")) {
    return "biological_sciences";
  }
  if (lower.includes("chemist") || lower.includes("physic")) return "physical_sciences";
  if (lower.includes("medicine") || lower.includes("medical")) return "medicine";
  // Unknown stays unknown — never a fabricated discipline.
  return null;
}
