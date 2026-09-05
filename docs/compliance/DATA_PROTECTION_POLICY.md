# Data Protection Policy

**Document ID:** GRX-DP-003
**Version:** 1.0
**Last Updated:** 2026-09-05
**Owner:** GrantRx Engineering
**Classification:** Internal

---

## 1. Purpose

This policy defines the data protection standards for GrantRx, covering data classification, encryption, regulatory compliance considerations, and Row-Level Security (RLS) enforcement. It ensures that user data — particularly student education records and clinical training information — is protected against unauthorized access, disclosure, and loss.

## 2. Scope

This policy applies to:

- All data stored in the GrantRx Supabase PostgreSQL database
- All data transmitted between the frontend (Vercel), backend (Render), and database (Supabase)
- All data processed by automated workflows (GitHub Actions scrapers, digest workers)
- All third-party integrations (Stripe, Resend, OpenAI/LiteLLM)

## 3. Data Classification Matrix

GrantRx classifies all data into three tiers based on sensitivity and regulatory requirements:

### 3.1 Classification Tiers

| Tier | Classification | Description | Examples | Access |
|------|---------------|-------------|----------|--------|
| **1** | **Public** | Data approved for public disclosure | Scholarship listings, provider names, deadlines, portal URLs | All users (authenticated) |
| **2** | **Internal** | Operational data not for public release | System logs, scraper configurations, migration files, CI/CD configs | Admins, Developers |
| **3** | **Confidential / PII** | Sensitive user data requiring protection | Profiles (GPA, SAI, state, discipline), application notes, budget details, documents, checklist progress | Authenticated user (own data only) |

### 3.2 Classification by Database Table

| Table | Classification | Rationale |
|-------|---------------|-----------|
| `scholarships` | Public | Scholarship listings are publicly available information |
| `profiles` | Confidential / PII | Contains GPA, SAI score, state, discipline, demographic flags |
| `user_scholarships` | Confidential / PII | Contains application notes, documents, checklist progress |
| `student_college_budgets` | Confidential / PII | Contains financial budget details and loan configuration |
| `scholarship_dismissals` | Internal | User preference data (dismissed scholarships) |

### 3.3 Handling Requirements

| Requirement | Public | Internal | Confidential / PII |
|-------------|--------|----------|-------------------|
| Encryption at rest | Optional | Required | Required (AES-256) |
| Encryption in transit | Required | Required | Required (TLS 1.3) |
| Access logging | Optional | Required | Required |
| RLS enforcement | N/A | N/A | Required |
| Backup retention | Standard | Standard | Extended (7-day PITR) |
| Data minimization | N/A | Apply | Apply strictly |

## 4. Encryption

### 4.1 Encryption at Rest

- **Database:** Supabase PostgreSQL provides AES-256 encryption at rest for all stored data. This is enabled by default on all Supabase projects and cannot be disabled.
- **Backups:** Supabase automated backups are encrypted at rest using the same AES-256 standard.
- **Object Storage:** Any file attachments (if added in future) will be stored in Supabase Storage with AES-256 encryption.

### 4.2 Encryption in Transit

- **All API traffic:** TLS 1.3 is enforced for all connections between:
  - Frontend (Vercel) ↔ Backend (Render)
  - Backend (Render) ↔ Database (Supabase)
  - User browser ↔ Frontend (Vercel)
  - GitHub Actions ↔ Supabase (for scraper workflows)
- **Certificate management:** Vercel and Render manage TLS certificates automatically with auto-renewal.
- **Minimum TLS version:** TLS 1.2 is the minimum accepted version; TLS 1.3 is preferred. Older protocols (TLS 1.0, 1.1, SSL) are disabled.

### 4.3 Application-Level Encryption

- **Password hashing:** Supabase Auth uses bcrypt for password hashing.
- **JWT signing:** JWTs are signed using HMAC-SHA256 with keys managed by Supabase.
- **API keys:** All third-party API keys (Stripe, Resend, OpenAI) are stored as environment variables and never written to the database or logs.

## 5. Regulatory Compliance Considerations

### 5.1 FERPA (Family Educational Rights and Privacy Act)

GrantRx stores student education records that may fall under FERPA protections:

- **Applicable data:** GPA, academic discipline, clinical phase, enrollment status, application notes.
- **Safeguards implemented:**
  - Row-Level Security (RLS) ensures users can only access their own education records.
  - All education record data is classified as Confidential / PII (Tier 3).
  - Access to education records is logged.
  - Data is not shared with third parties without user consent.
- **User rights:** Users can request access to their stored data and request deletion via the profile endpoint.

### 5.2 HIPAA (Health Insurance Portability and Accountability Act)

GrantRx may store information related to clinical education and healthcare training:

- **Applicable data:** Clinical discipline, clinical phase, clinical lab fees, work/volunteer experience in healthcare settings.
- **Current posture:** GrantRx does not store Protected Health Information (PHI) as defined by HIPAA. The platform stores education-related data about clinical training, not patient health records.
- **Safeguards implemented:**
  - All user data is encrypted at rest and in transit.
  - RLS prevents cross-user data access.
  - If PHI is ever introduced, a full HIPAA compliance assessment will be conducted before deployment.
- **Limitation:** GrantRx is not currently a HIPAA-covered entity or business associate. If the platform's scope changes to include PHI, a Business Associate Agreement (BAA) with Supabase will be required.

### 5.3 Data Retention

| Data Type | Retention Period | Disposal Method |
|-----------|-----------------|-----------------|
| User profiles | Until account deletion | Hard delete on user request |
| User scholarships tracking | Until account deletion | Hard delete on user request |
| Application notes & documents | Until account deletion | Hard delete on user request |
| Audit logs | 12 months | Automated purge after retention period |
| Incident records | 24 months | Automated purge after retention period |
- **Right to deletion:** Users can request complete data deletion by contacting support. Deletion is processed within 30 days.

## 6. Row-Level Security (RLS) Enforcement

### 6.1 RLS Policy

Row-Level Security is enabled on all user-facing tables in the Supabase PostgreSQL database. RLS policies ensure that authenticated users can only read, write, update, or delete their own data.

### 6.2 RLS-Enabled Tables

| Table | RLS Status | Policy |
|-------|-----------|--------|
| `profiles` | **Enabled** | Users can SELECT, INSERT, UPDATE, DELETE only rows where `id = auth.uid()` |
| `user_scholarships` | **Enabled** | Users can SELECT, INSERT, UPDATE, DELETE only rows where `user_id = auth.uid()` |
| `student_college_budgets` | **Enabled** | Users can SELECT, INSERT, UPDATE, DELETE only rows where `user_id = auth.uid()` |

### 6.3 RLS Verification

RLS enforcement is verified via:

1. **Automated tests:** The test suite verifies that authenticated endpoints return only the current user's data.
2. **Manual verification:** Quarterly review of Supabase dashboard to confirm RLS policies are active.
3. **Security audit:** The `SECURITY_AUDIT_SUMMARY.md` document tracks RLS status.

### 6.4 Service Role Access

The Supabase service role key bypasses RLS and is used only for:

- Automated scraper workflows (GitHub Actions)
- Administrative operations (archival, digest generation)
- Database migrations

The service role key is **never** exposed to end users or the frontend application.

## 7. Third-Party Data Processing

### 7.1 Data Shared with Third Parties

| Third Party | Data Shared | Purpose | Safeguards |
|-------------|------------|---------|------------|
| **Stripe** | Email, subscription tier, billing plan | Payment processing | Stripe PCI-DSS compliance; no card data stored by GrantRx |
| **Resend** | Email address, digest content | Deadline reminder emails | Resend SOC 2 compliance; emails contain only public scholarship data |
| **OpenAI / LiteLLM** | Scholarship text, user notes (for essay outline) | AI Statement Coach | Data sent via TLS; OpenAI data retention policy applies |

### 7.2 Data Not Shared

- User GPAs, SAI scores, and financial budget details are **never** shared with third parties.
- Application notes and documents are **never** shared with third parties except when explicitly submitted to the AI Statement Coach by the user.

## 8. Data Breach Response

Data breaches involving Confidential / PII data are handled according to the [Incident Response Plan](./INCIDENT_RESPONSE_PLAN.md), including the 72-hour notification protocol.

## 9. Policy Review

This policy is reviewed annually or upon significant changes to the data architecture. All updates are versioned and tracked in Git.

---

**Approved by:** GrantRx Engineering
**Next review date:** 2027-09-05
