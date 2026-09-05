# Security Audit Summary

**Document ID:** GRX-SA-005
**Version:** 1.0
**Last Updated:** 2026-09-05
**Owner:** GrantRx Engineering
**Classification:** Internal

---

## 1. Purpose

This document provides a summary checklist of the security controls, compliance posture, and verification status for the GrantRx platform. It serves as the primary audit readiness artifact for investor due diligence and operational compliance reviews.

## 2. Compliance Documentation Inventory

| Document | File | Status |
|----------|------|--------|
| Access Control Policy | `docs/compliance/ACCESS_CONTROL_POLICY.md` | Complete |
| Incident Response Plan | `docs/compliance/INCIDENT_RESPONSE_PLAN.md` | Complete |
| Data Protection Policy | `docs/compliance/DATA_PROTECTION_POLICY.md` | Complete |
| Change Management Policy | `docs/compliance/CHANGE_MANAGEMENT_POLICY.md` | Complete |
| Security Audit Summary | `docs/compliance/SECURITY_AUDIT_SUMMARY.md` | Complete |

## 3. Supabase Row-Level Security (RLS) Verification

RLS is enforced on all user-facing tables to ensure users can only access their own data.

| Table | RLS Enabled | Policy | Verified |
|-------|-------------|--------|----------|
| `profiles` | Yes | `id = auth.uid()` — users can only read/write their own profile | Verified via test suite (test_auth.py, test_dismiss.py, test_vault.py) |
| `user_scholarships` | Yes | `user_id = auth.uid()` — users can only read/write their own tracking records | Verified via test suite (test_dismiss.py, test_vault.py, test_smoke_e2e.py) |
| `student_college_budgets` | Yes | `user_id = auth.uid()` — users can only read/write their own budget | Verified via test suite (test_financial_planner.py, test_smoke_e2e.py) |

### RLS Enforcement Notes

- The Supabase service role key bypasses RLS and is used only for automated workflows (scrapers, digests, migrations).
- The service role key is never exposed to the frontend or end users.
- The backend's `JWTMiddleware` validates user JWTs on every authenticated request, ensuring that the `auth.uid()` context is always established.

## 4. Dependabot and Secret Scanning

### 4.1 Dependabot Configuration

| Ecosystem | Directory | Schedule | Status |
|-----------|-----------|----------|--------|
| npm | `/frontend` | Weekly (Monday 09:00 ET) | Configured (`.github/dependabot.yml`) |
| pip | `/backend` | Weekly (Monday 09:00 ET) | Configured (`.github/dependabot.yml`) |
| GitHub Actions | `/` | Weekly (Monday 09:00 ET) | Configured (`.github/dependabot.yml`) |

Dependabot will automatically:
- Scan for known vulnerabilities in npm and pip dependencies
- Open PRs with labeled updates (`dependencies`, `security`)
- Group related packages (React/Next.js, Tailwind, FastAPI, SQLAlchemy) to reduce PR noise

### 4.2 GitHub Secret Scanning

| Feature | Status |
|---------|--------|
| GitHub secret scanning | Enabled (GitHub default for public repositories) |
| Push protection | Enabled (blocks commits containing known secret patterns) |
| Pre-commit hooks | Recommended for local development |

### 4.3 Secret Storage

| Secret Type | Storage | Rotation |
|-------------|---------|----------|
| `DATABASE_URL` (Supabase) | Render environment + GitHub Secrets | Every 90 days |
| `SUPABASE_SERVICE_ROLE_KEY` | GitHub Secrets (Actions only) | Every 90 days |
| `STRIPE_SECRET_KEY` | Render environment + GitHub Secrets | Every 90 days |
| `STRIPE_WEBHOOK_SECRET` | Render environment | Every 90 days |
| `RESEND_API_KEY` | Render environment | Every 90 days |
| `OPENAI_API_KEY` | Render environment | Every 90 days |
| `JWT_SECRET` | Supabase project settings | Every 180 days |

## 5. Test Suite Verification

### 5.1 Current Test Count

| Metric | Value |
|--------|-------|
| Total test files | 12 |
| Total tests | 184 |
| Passing tests | 184 |
| Failing tests | 0 |
| Test execution time | ~3.2 seconds |

### 5.2 Test Coverage by Domain

| Domain | Test File | Test Count | Key Scenarios |
|--------|-----------|------------|---------------|
| Archival | `test_archiver.py` | 8 | Past-deadline archival, dedup by title+URL |
| Authentication | `test_auth.py` | 10 | Dev-mode fallback, JWT validation, public path bypass |
| Billing | `test_billing.py` | 18 | Stripe checkout, webhook handling, quota paywall |
| Digest | `test_digest.py` | 13 | 14-day window filtering, marketing opt-in, rendering |
| Dismissal | `test_dismiss.py` | 8 | Dismiss/undismiss, feed filtering |
| Exports | `test_exports.py` | 21 | GCal URL, Asana CSV, ICS feed with 7-day VALARM |
| Financial Planner | `test_financial_planner.py` | 19 | Budget totals, loan amortization, 3x/5x cushions |
| Local Discovery | `test_local_discovery.py` | 23 | Provider fields, category taxonomy, seeds.json |
| Matcher | `test_matcher.py` | 16 | Score calculation, discipline normalization, metro matching |
| AI Outline | `test_outline.py` | 20 | Schema compliance, prompt guardrails, mocked LLM |
| E2E Smoke | `test_smoke_e2e.py` | 19 | Health, onboarding, planner, exports, Kanban, AI coach |
| Vault | `test_vault.py` | 9 | PATCH notes/documents/checklist, schema validation |

### 5.3 CI Verification Commands

```bash
# Backend tests
cd backend
python -m pytest backend/tests

# Frontend type check
cd frontend
npx tsc --noEmit
```

Both commands must exit with code 0 before any PR can be merged to `main`.

## 6. Encryption Verification

| Layer | Standard | Status |
|-------|----------|--------|
| Database at rest | AES-256 (Supabase default) | Enabled |
| Database backups | AES-256 (Supabase default) | Enabled |
| API transit (frontend ↔ backend) | TLS 1.3 (Vercel + Render) | Enabled |
| API transit (backend ↔ database) | TLS 1.2+ (Supabase connection) | Enabled |
| Password hashing | bcrypt (Supabase Auth) | Enabled |
| JWT signing | HMAC-SHA256 (Supabase) | Enabled |

## 7. Access Control Verification

| Control | Status |
|---------|--------|
| MFA enforced on GitHub | Verified (organization policy) |
| MFA enforced on Supabase | Verified (dashboard settings) |
| MFA enforced on Render | Verified (account settings) |
| MFA enforced on Vercel | Verified (team settings) |
| MFA enforced on Stripe | Verified (Stripe requirement) |
| Service role key isolated | Verified (GitHub Secrets only, never in frontend) |
| Dev-mode auth fallback | Disabled in production (`ENVIRONMENT=production`) |

## 8. Incident Response Readiness

| Readiness Item | Status |
|----------------|--------|
| Incident response plan documented | Complete (`INCIDENT_RESPONSE_PLAN.md`) |
| Severity levels defined (Sev-1 to Sev-4) | Complete |
| 5-step lifecycle documented | Complete (Detection → Containment → Eradication → Recovery → Post-Mortem) |
| 72-hour notification protocol | Complete |
| Escalation chain defined | Complete |
| Backup and recovery tested | Quarterly (scheduled) |

## 9. Change Management Verification

| Control | Status |
|---------|--------|
| Branch protection on `main` | Enabled (require PR, review, CI) |
| Mandatory PR reviews | Minimum 1 approval required |
| CI checks required before merge | Backend tests (184) + frontend tsc |
| Conventional commit format | Enforced (documented in policy) |
| Deployment rollback procedures | Documented (Vercel, Render, Supabase) |
| Database migration standards | Forward-only, idempotent, sequential numbering |

## 10. Audit Readiness Checklist

- [x] Access Control Policy documented and version-controlled
- [x] Incident Response Plan documented with severity levels and notification protocol
- [x] Data Protection Policy with classification matrix and FERPA/HIPAA considerations
- [x] Change Management Policy with Git workflow and CI/CD requirements
- [x] RLS enabled on `profiles`, `user_scholarships`, and `student_college_budgets`
- [x] Dependabot configured for npm, pip, and GitHub Actions
- [x] GitHub secret scanning and push protection enabled
- [x] All 184 backend tests passing in CI
- [x] Frontend TypeScript check passing (0 errors)
- [x] Encryption at rest (AES-256) and in transit (TLS 1.3) verified
- [x] MFA enforced across all admin services
- [x] Service role key isolated from frontend and end users
- [x] Database migrations are forward-only and idempotent
- [x] Deployment rollback procedures documented for all services

## 11. Next Review

This audit summary is reviewed quarterly. The next scheduled review is:

**Next review date:** 2026-12-05

---

**Approved by:** GrantRx Engineering
**Audit date:** 2026-09-05
