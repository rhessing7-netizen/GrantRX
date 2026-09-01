import type { ClinicalDiscipline } from "@/lib/types";

// ---------------------------------------------------------------------------
// Undergraduate Science & Health Major Taxonomy
//
// Categorized list of undergraduate majors that map to GrantRx clinical
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
];

// Flat list of all majors (for backward compatibility with MultiSelect)
export const ALL_MAJORS: string[] = MAJOR_CATEGORIES.flatMap((c) => c.majors);

// ---------------------------------------------------------------------------
// Major -> Clinical Discipline mapping
//
// Maps undergraduate science/health majors to the backend's
// ClinicalDiscipline enum values used for scholarship matching.
// ---------------------------------------------------------------------------

const _MAJOR_TO_DISCIPLINE: Record<string, ClinicalDiscipline> = {
  // Pharmacy
  "Pre-Pharmacy": "pharmacy",

  // Medicine / Pre-clinical
  "Pre-Medicine": "medicine",
  "Pre-Dental": "medicine",
  "Pre-Veterinary": "medicine",
  "Pre-Physician Assistant": "medicine",
  "Biology": "medicine",
  "Molecular & Cellular Biology": "medicine",
  "Microbiology": "medicine",
  "Genetics": "medicine",
  "Neuroscience": "medicine",
  "Chemistry": "medicine",
  "Biochemistry": "medicine",
  "Organic Chemistry": "medicine",
  "Analytical Chemistry": "medicine",
  "Physics": "medicine",
  "Biophysics": "medicine",
  "Botany / Plant Biology": "medicine",
  "Zoology": "medicine",
  "Ecology & Evolutionary Biology": "medicine",
  "Astronomy / Astrophysics": "medicine",
  "Geology / Earth Science": "medicine",
  "Geophysics": "medicine",
  "Oceanography": "medicine",
  "Atmospheric Sciences / Meteorology": "medicine",
  "Medical Laboratory Science": "medicine",

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
  "Health Sciences": "public_health_emergency",
  "Global Health": "public_health_emergency",
  "Epidemiology": "public_health_emergency",
  "Healthcare Management / Administration": "public_health_emergency",
  "Health Informatics": "public_health_emergency",
  "Environmental Health": "public_health_emergency",
  "Environmental Science": "public_health_emergency",

  // Dental Hygiene -> medicine (closest clinical match)
  "Dental Hygiene": "medicine",
};

/**
 * Map an undergraduate major string to a ClinicalDiscipline enum value
 * used by the backend for scholarship matching.
 *
 * Returns "medicine" as a sensible pre-health fallback for unknown
 * science majors, since most general science students are pre-health.
 */
export function mapMajorToClinicalDiscipline(major: string): ClinicalDiscipline {
  if (!major) return "medicine";
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
  // Default: general science/pre-health -> medicine
  return "medicine";
}
