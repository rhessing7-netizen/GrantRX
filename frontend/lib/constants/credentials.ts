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
  { value: "doctoral", label: "Doctoral / Professional Practice" },
  { value: "masters", label: "Master's Degree" },
  { value: "undergraduate", label: "Undergraduate (Bachelor's / Associate)" },
  { value: "certificate", label: "Post-Secondary Certificate / Diploma" },
];

export const CREDENTIALS_BY_LEVEL: Record<DegreeLevel, string[]> = {
  doctoral: [
    "PharmD (Doctor of Pharmacy)",
    "MD / DO (Medicine)",
    "DNP (Doctor of Nursing Practice)",
    "DPT (Doctor of Physical Therapy)",
    "OTD (Doctor of Occupational Therapy)",
    "DDS / DMD (Dental Medicine)",
    "PhD / DrPH (Public Health / Health Sciences)",
    "PsyD (Clinical Psychology)",
    "DPM (Podiatry)",
    "DC (Chiropractic)",
    "DVM (Veterinary)",
    "AuD (Audiology)",
  ],
  masters: [
    "MHA (Master of Health Administration)",
    "MPH (Master of Public Health)",
    "MSN (Master of Science in Nursing)",
    "MPAS (Master of Physician Assistant Studies)",
    "MSW (Master of Social Work)",
    "MS-SLP (Master of Speech-Language Pathology)",
    "MOT (Master of Occupational Therapy)",
    "MPT (Master of Physical Therapy)",
  ],
  undergraduate: [
    "BSN (Bachelor of Science in Nursing)",
    "ADN (Associate Degree in Nursing)",
    "BS Health Sciences",
    "BS Biology",
    "BS Chemistry",
    "BS Public Health",
    "BS Biomedical Sciences",
    "BA Psychology",
    "AS/AAS (Associate of Applied Science)",
  ],
  certificate: [
    "Certificate / Diploma",
    "CNA (Certified Nursing Assistant)",
    "LPN / LVN (Licensed Practical Nurse)",
    "Medical Assistant Certificate",
    "Pharmacy Technician Certificate",
    "EMT / Paramedic Certificate",
    "Surgical Technology Certificate",
  ],
};
