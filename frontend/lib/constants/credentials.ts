/**
 * Cascading credential hierarchy for healthcare students.
 * First the user selects a Degree Level, then a specific credential
 * within that level is revealed.
 */

export type DegreeLevel =
  | "doctoral"
  | "masters"
  | "undergraduate"
  | "certificate";

export const DEGREE_LEVELS: { value: DegreeLevel; label: string }[] = [
  { value: "doctoral", label: "Doctoral & Professional" },
  { value: "masters", label: "Master's Degree" },
  { value: "undergraduate", label: "Undergraduate Degree" },
  { value: "certificate", label: "Associate Degree / Certificate" },
];

export const CREDENTIALS_BY_LEVEL: Record<DegreeLevel, string[]> = {
  doctoral: [
    "Doctor of Pharmacy (PharmD)",
    "Doctor of Medicine (MD)",
    "Doctor of Osteopathic Medicine (DO)",
    "Doctor of Physical Therapy (DPT)",
    "Doctor of Nursing Practice (DNP)",
    "Doctor of Dental Surgery / Medicine (DDS/DMD)",
    "Doctor of Occupational Therapy (OTD)",
    "Doctor of Optometry (OD)",
    "Doctor of Podiatric Medicine (DPM)",
    "Doctor of Chiropractic (DC)",
    "Doctor of Veterinary Medicine (DVM)",
    "PhD / DrPH in Health Sciences",
    "Doctor of Psychology (PsyD)",
  ],
  masters: [
    "Master of Health Administration (MHA)",
    "Master of Public Health (MPH)",
    "Master of Science in Nursing (MSN)",
    "Physician Assistant Studies (MPAS/MSPA)",
    "Master of Social Work (MSW)",
    "Speech-Language Pathology (MS-SLP)",
  ],
  undergraduate: [
    "Bachelor of Science in Nursing (BSN)",
    "Biology / Pre-Med",
    "Chemistry / Biochemistry",
    "Exercise Science / Kinesiology",
    "Health Sciences / Public Health",
  ],
  certificate: [
    "Associate Degree in Nursing (ADN)",
    "Certificate / Diploma",
    "CNA (Certified Nursing Assistant)",
    "LPN / LVN (Licensed Practical Nurse)",
    "Medical Assistant Certificate",
    "Pharmacy Technician Certificate",
    "EMT / Paramedic Certificate",
    "Surgical Technology Certificate",
  ],
};
