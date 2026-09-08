-- Migration 016: Create crawler_seeds queue table for autonomous seed discovery.
--
-- Stores both manually curated seeds (from seeds.json) and dynamically
-- discovered directory hubs. The crawler pulls the next batch from this
-- table and enqueues newly discovered hub URLs during traversal.

CREATE TABLE IF NOT EXISTS crawler_seeds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url TEXT UNIQUE NOT NULL,
  source_name TEXT,
  category TEXT DEFAULT 'discovered_directory',
  priority INTEGER DEFAULT 1,
  status TEXT DEFAULT 'queued',  -- 'queued', 'crawled', 'failed', 'ignored'
  error_count INTEGER DEFAULT 0,
  last_crawled_at TIMESTAMP WITH TIME ZONE NULL,
  discovered_from_url TEXT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Composite index for the "next batch" query: queued/crawled seeds ordered
-- by priority DESC then oldest-crawled-first (NULLS FIRST = never crawled).
CREATE INDEX IF NOT EXISTS idx_crawler_seeds_status_priority_last_crawled
  ON crawler_seeds (status, priority DESC, last_crawled_at ASC);

-- Unique index on URL (in addition to the column constraint) for fast
-- ON CONFLICT (url) DO NOTHING upserts.
CREATE UNIQUE INDEX IF NOT EXISTS idx_crawler_seeds_url_unique
  ON crawler_seeds (url);

-- Seed the table with existing entries from scrapers/seeds.json.
-- These are inserted with status='queued' and priority=1 so the first
-- dynamic-queue run picks them up immediately.
INSERT INTO crawler_seeds (url, source_name, category, priority, status)
SELECT
  item->>'url',
  item->>'name',
  COALESCE(item->>'category', 'discovered_directory'),
  1,
  'queued'
FROM jsonb_array_elements(
  '[
    {"url":"https://www.clevelandfoundation.org/scholarships/","name":"The Cleveland Foundation","category":"regional_foundation"},
    {"url":"https://www.akroncf.org/students-scholarships/","name":"Akron Community Foundation","category":"community_foundation"},
    {"url":"https://www.waynecountycommunityfoundation.org/scholarships","name":"Wayne County Community Foundation","category":"community_foundation"},
    {"url":"https://www.starkcf.org/for-students/scholarships","name":"Stark Community Foundation","category":"community_foundation"},
    {"url":"https://www.columbusfoundation.org/students/scholarships","name":"The Columbus Foundation","category":"community_foundation"},
    {"url":"https://www.cincinnatistatemedical.org/scholarships","name":"Greater Cincinnati Foundation Scholarships","category":"community_foundation"},
    {"url":"https://odh.ohio.gov/know-our-programs/primary-care-office/loan-repayment-programs","name":"Ohio Department of Health (ODH) Loan Repayments","category":"state_agency"},
    {"url":"https://highered.ohio.gov/initiatives/affordability/nealp","name":"Ohio Nurse Education Assistance Loan Program (NEALP)","category":"state_agency"},
    {"url":"https://my.clevelandclinic.org/departments/nursing/nursing-education/aspire","name":"Cleveland Clinic ASPIRE Nurse Scholars","category":"health_system"},
    {"url":"https://www.metrohealth.org/foundation/scholarships","name":"MetroHealth System Foundation Grants","category":"health_system"},
    {"url":"https://www.neomed.edu/financialaid/scholarships/external/","name":"Northeast Ohio Medical University (NEOMED) External Awards","category":"academic_institution"},
    {"url":"https://pittsburghfoundation.org/scholarshipsearch","name":"The Pittsburgh Foundation","category":"regional_foundation"},
    {"url":"https://www.philafound.org/students/scholarships/","name":"The Philadelphia Foundation","category":"community_foundation"},
    {"url":"https://www.eriecommunityfoundation.org/scholarships","name":"The Erie Community Foundation","category":"community_foundation"},
    {"url":"https://www.health.pa.gov/topics/Health-Planning/Pages/Primary-Care-Loan-Repayment-Program.aspx","name":"Pennsylvania Primary Care Loan Repayment Program (PCLRP)","category":"state_agency"},
    {"url":"https://www.pheaa.org/funding-opportunities/index.shtml","name":"PHEAA Health Professions Grants","category":"state_agency"},
    {"url":"https://www.geisinger.org/education/scholarships-and-fellowships","name":"Geisinger Primary Care Scholars Program","category":"health_system"},
    {"url":"https://www.upmc.com/careers/students-and-trainees/nursing-programs","name":"UPMC Schools of Nursing Tuition Assistance","category":"health_system"},
    {"url":"https://www.duq.edu/admissions-and-aid/tuition-and-financial-aid/types-of-aid/scholarships/external-scholarships.php","name":"Duquesne University External Health Scholarships","category":"university_listing"},
    {"url":"https://www.pharmacy.pitt.edu/admissions-and-aid/scholarships-and-financial-aid","name":"University of Pittsburgh School of Pharmacy Awards","category":"academic_institution"},
    {"url":"https://cof.org/page/community-foundation-locator","name":"Council on Foundations — Community Foundation Locator","category":"regional_foundation"},
    {"url":"https://www.nycommunitytrust.org/information-for/scholarship-applicants/","name":"The New York Community Trust","category":"community_foundation"},
    {"url":"https://www.calfund.org/nonprofits/scholarships/","name":"California Community Foundation","category":"community_foundation"},
    {"url":"https://www.cct.org/what-we-offer/scholarships/","name":"The Chicago Community Trust","category":"community_foundation"},
    {"url":"https://www.cftexas.org/scholarships","name":"Communities Foundation of Texas","category":"community_foundation"},
    {"url":"https://ghcf.org/scholarships/","name":"Greater Houston Community Foundation","category":"community_foundation"},
    {"url":"https://cfgreateratlanta.org/scholarships/","name":"Community Foundation for Greater Atlanta","category":"community_foundation"},
    {"url":"https://www.thecommunityfoundation.org/scholarships","name":"Greater Washington Community Foundation","category":"community_foundation"},
    {"url":"https://miamifoundation.org/scholarships/","name":"The Miami Foundation","category":"community_foundation"},
    {"url":"https://www.azfoundation.org/scholarships/","name":"Arizona Community Foundation","category":"community_foundation"},
    {"url":"https://www.tbf.org/what-we-do/scholarships","name":"The Boston Foundation","category":"community_foundation"},
    {"url":"https://www.iegives.org/students/scholarships/","name":"Inland Empire Community Foundation","category":"community_foundation"},
    {"url":"https://www.siliconvalleycf.org/scholarships","name":"Silicon Valley Community Foundation","category":"community_foundation"},
    {"url":"https://cfsem.org/apply/scholarships/","name":"Community Foundation for Southeast Michigan","category":"community_foundation"},
    {"url":"https://www.seattlefoundation.org/scholarships/","name":"Seattle Foundation","category":"community_foundation"},
    {"url":"https://www.minneapolisfoundation.org/scholarships/","name":"The Minneapolis Foundation","category":"community_foundation"},
    {"url":"https://cftampabay.org/scholarships/","name":"Community Foundation of Tampa Bay","category":"community_foundation"},
    {"url":"https://www.sdfoundation.org/students/community-scholarship-program/","name":"San Diego Foundation","category":"community_foundation"},
    {"url":"https://denverfoundation.org/scholarships/","name":"The Denver Foundation","category":"community_foundation"},
    {"url":"https://cffound.org/scholarships/","name":"Central Florida Foundation","category":"community_foundation"},
    {"url":"https://www.duq.edu/financial-aid/scholarships-and-grants/external-scholarships","name":"Duquesne University — External Scholarships","category":"academic_institution"},
    {"url":"https://oaa.osu.edu/scholarships-and-awards/outside-scholarships.html","name":"Ohio State University — Outside Scholarships","category":"academic_institution"},
    {"url":"https://www.pitt.edu/admissions/financial-aid/scholarships/outside-scholarships","name":"University of Pittsburgh — Outside Scholarships","category":"academic_institution"},
    {"url":"https://my.clevelandclinic.org/about/careers/students-and-new-grads/aspire-program","name":"Cleveland Clinic ASPIRE Program","category":"employer_tuition_benefit"},
    {"url":"https://my.clevelandclinic.org/about/careers/benefits/tuition-assistance","name":"Cleveland Clinic Tuition Assistance","category":"employer_tuition_benefit"},
    {"url":"https://careers.kaiserpermanente.org/jobs/allied-health","name":"Kaiser Permanente — Allied Health Pipeline","category":"clinical_employee_pipeline"},
    {"url":"https://www.va.gov/education/health-professional-training/","name":"VA Health Professional Education (NNEI / EISP / VANEEP)","category":"government_employee_benefit"},
    {"url":"https://www.ihs.gov/scholarship/loanrepayment/","name":"Indian Health Service Loan Repayment Program","category":"government_employee_benefit"},
    {"url":"https://www.nhsf.org/scholarships/","name":"National Health Service Corps Scholarships","category":"government_employee_benefit"},
    {"url":"https://www.americorps.gov/for-organizations/funding-opportunities","name":"AmeriCorps Funding Opportunities","category":"government_employee_benefit"},
    {"url":"https://www.guildeducation.com/partners","name":"Guild Education — Employer Partner Network","category":"employer_tuition_benefit"},
    {"url":"https://www.instride.com/education-programs","name":"InStride — Education Programs","category":"employer_tuition_benefit"},
    {"url":"https://www.brighthorizons.com/clients/ed-assist","name":"Bright Horizons EdAssist Solutions","category":"employer_tuition_benefit"},
    {"url":"https://www.academicworks.com/","name":"AcademicWorks — Platform Discovery","category":"accrediting_body"}
  ]'::jsonb
) AS item
ON CONFLICT (url) DO NOTHING;
