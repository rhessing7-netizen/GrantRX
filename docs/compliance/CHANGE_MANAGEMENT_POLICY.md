# Change Management Policy

**Document ID:** GRX-CM-004
**Version:** 1.0
**Last Updated:** 2026-09-05
**Owner:** GrantRx Engineering
**Classification:** Internal

---

## 1. Purpose

This policy defines the change management standards for GrantRx, covering Git workflow, code review requirements, CI/CD pipeline enforcement, and deployment rollback procedures. It ensures that all changes to production code are reviewed, tested, and deployable with minimal risk.

## 2. Scope

This policy applies to:

- All code changes to the GrantRx repository (frontend, backend, scrapers, infrastructure)
- All database migrations and schema changes
- All configuration changes (environment variables, CI/CD pipelines, GitHub settings)
- All deployment operations to Vercel (frontend), Render (backend), and Supabase (database)

## 3. Git Workflow Standards

### 3.1 Branch Strategy

GrantRx follows a trunk-based development model with feature branches:

| Branch | Purpose | Protection |
|--------|---------|------------|
| `main` | Production-ready code; auto-deploys to staging/production | Protected: requires PR, review, passing CI |
| `feature/*` | New features or enhancements | Deleted after merge |
| `fix/*` | Bug fixes | Deleted after merge |
| `docs/*` | Documentation changes | Deleted after merge |
| `hotfix/*` | Urgent production fixes | Merged directly to `main` with expedited review |

### 3.2 Branch Protection Rules

The `main` branch is protected with the following rules:

1. **Require pull request before merging:** No direct commits to `main`.
2. **Require approvals:** Minimum 1 approval from a code owner or reviewer.
3. **Require status checks to pass:** All required CI checks must pass before merge.
4. **Require branches to be up to date:** PR branch must be current with `main` before merge.
5. **Restrict who can push:** Only the Owner and Admins can merge PRs.
6. **Allow force pushes:** Disabled (never allowed on `main`).
7. **Allow deletions:** Disabled (never allowed on `main`).

### 3.3 Commit Standards

- **Conventional commits:** All commits follow the conventional commit format:
  - `feat(scope): description` — new feature
  - `fix(scope): description` — bug fix
  - `test(scope): description` — test additions or changes
  - `docs(scope): description` — documentation changes
  - `refactor(scope): description` — code refactoring
  - `chore(scope): description` — maintenance tasks
- **Atomic commits:** Each commit represents a single logical change.
- **Descriptive messages:** Commit messages explain the "why" not just the "what."

### 3.4 Pull Request Standards

Every PR must include:

1. **Description:** Clear summary of the change and its purpose.
2. **Related issue:** Link to the tracked issue (if applicable).
3. **Testing notes:** How the change was tested (unit tests, manual verification).
4. **Breaking changes:** Explicit callout of any breaking changes.
5. **Checklist confirmation:**
   - [ ] Code follows project style guidelines
   - [ ] Self-review completed
   - [ ] Tests added/updated and passing
   - [ ] Documentation updated (if applicable)

## 4. Mandatory Code Review

### 4.1 Review Requirements

- **Minimum reviewers:** 1 approval required for all PRs.
- **Self-review:** PR authors must self-review their code before requesting review.
- **Review scope:** Reviewers verify correctness, security, performance, and adherence to project conventions.
- **Review timeout:** PRs awaiting review for more than 48 hours are escalated.

### 4.2 Review Checklist

Reviewers verify:

- [ ] No secrets or credentials in code
- [ ] No hardcoded environment-specific values
- [ ] Input validation on all user-facing endpoints
- [ ] Proper error handling (no silent failures)
- [ ] SQL queries use ORM (no raw SQL injection risks)
- [ ] New dependencies are justified and vetted
- [ ] Tests cover the new functionality
- [ ] No breaking changes without migration plan

## 5. CI/CD Pipeline Requirements

### 5.1 Required Checks Before Merge

All PRs must pass the following CI checks before merging to `main`:

| Check | Command | Required |
|-------|---------|----------|
| Backend tests | `python -m pytest backend/tests` | Yes |
| Frontend type check | `npx tsc --noEmit` | Yes |
| Lint (if configured) | `npm run lint` / `ruff check` | Yes (when configured) |
| Build verification | `npm run build` | Yes (frontend) |

### 5.2 Current Test Suite

The GrantRx test suite includes **184 tests** across 12 test files:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_archiver.py` | 8 | Scholarship archival and dedup |
| `test_auth.py` | 10 | JWT middleware and dev-mode auth |
| `test_billing.py` | 18 | Stripe checkout and webhook handling |
| `test_digest.py` | 13 | Deadline digest worker |
| `test_dismiss.py` | 8 | Scholarship dismiss/undismiss |
| `test_exports.py` | 21 | GCal, Asana CSV, ICS exports |
| `test_financial_planner.py` | 19 | Budget calculations and loan amortization |
| `test_local_discovery.py` | 23 | Provider alignment and local fields |
| `test_matcher.py` | 16 | Scholarship matching algorithm |
| `test_outline.py` | 20 | AI essay outline generation |
| `test_smoke_e2e.py` | 19 | End-to-end launch smoke tests |
| `test_vault.py` | 9 | Application vault PATCH operations |
| **Total** | **184** | |

### 5.3 Deployment Pipeline

#### Frontend (Vercel)

1. Code merged to `main` triggers automatic Vercel deployment.
2. Vercel runs the build (`npm run build`) and deploys to the preview environment.
3. Production deployment is promoted manually after preview verification.

#### Backend (Render)

1. Code merged to `main` triggers automatic Render deployment.
2. Render runs the build and deploys to the web service.
3. Health check (`GET /health`) is verified post-deployment.

#### Database (Supabase)

1. Migration SQL files are committed to `backend/migrations/`.
2. Migrations are applied manually via a script or Supabase dashboard.
3. Migration application is verified by checking column/table existence.

### 5.4 Scheduled Workflows

GitHub Actions workflows run on schedule:

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `scheduled_scrape.yml` | Daily | Run scholarship scrapers |
| `scheduled_ingestion.yml` | Daily | Ingest, repair, and send deadline digests |

## 6. Deployment Rollback Procedures

### 6.1 Frontend Rollback (Vercel)

1. Navigate to the Vercel project dashboard.
2. Go to **Deployments** and find the last known good deployment.
3. Click the **...** menu and select **Promote to Production**.
4. Verify the rollback by checking the frontend in the browser.
5. **Time to rollback:** < 5 minutes.

### 6.2 Backend Rollback (Render)

1. Navigate to the Render service dashboard.
2. Go to **Deploys** and find the last known good deploy.
3. Click **Rollback** on the previous deploy.
4. Verify the rollback by checking `GET /health` and key endpoints.
5. **Time to rollback:** < 10 minutes.

### 6.3 Database Rollback (Supabase)

1. **Schema changes (migrations):**
   - If a migration fails, the `IF NOT EXISTS` guards prevent partial application.
   - To reverse a migration, write a new migration file (e.g., `012_revert_011.sql`) that drops the added columns/tables.
   - Never edit or delete an applied migration file.
2. **Data restoration:**
   - Use Supabase Point-in-Time Recovery (PITR) to restore the database to a timestamp before the incident.
   - PITR is available for up to 7 days of history.
   - **Time to rollback:** < 1 hour (including verification).

### 6.4 Full-Stack Rollback

For Sev-1 incidents requiring a full rollback:

1. Roll back the frontend via Vercel (Step 6.1).
2. Roll back the backend via Render (Step 6.2).
3. Roll back the database via Supabase PITR (Step 6.3).
4. Verify all services are healthy and consistent.
5. Communicate restoration to users.
6. Conduct a post-mortem (per the Incident Response Plan).

## 7. Database Migration Standards

### 7.1 Migration File Naming

Migrations are numbered sequentially: `NNN_description.sql` (e.g., `011_add_provider_alignment_and_local_fields.sql`).

### 7.2 Migration Requirements

- All migrations use `IF NOT EXISTS` / `IF EXISTS` guards for idempotency.
- Migrations are forward-only — no destructive changes without a revert migration.
- Each migration is tested locally before committing.
- Migration files are never edited after being applied to production.

### 7.3 Current Migration Inventory

| Migration | Description |
|-----------|-------------|
| 001 | Initial schema |
| 002 | Stripe and feed token |
| 003 | User identity and consent |
| 004 | Multi-select disciplines and credentials |
| 005 | Metro restrictions |
| 006 | Metro area on profiles |
| 007 | Database indexes |
| 008 | Is dismissed on user scholarships |
| 009 | Documents and checklist on user scholarships |
| 010 | Financial planner |
| 011 | Provider alignment and local fields |

## 8. Emergency Changes

### 8.1 Hotfix Procedure

For urgent production issues that cannot wait for a standard PR:

1. Create a `hotfix/*` branch from `main`.
2. Make the minimal change required to resolve the issue.
3. Open a PR with the `hotfix` label.
4. Request expedited review (minimum 1 approval).
5. Merge and deploy immediately.
6. Create a follow-up PR for any additional fixes or tests.
7. Document the hotfix in the incident ticket.

### 8.2 Emergency Deployment

If CI is failing due to infrastructure issues (not code issues):

1. The Owner may authorize a manual deployment bypass.
2. The bypass is documented in the incident ticket.
3. CI is restored and the code is re-verified within 24 hours.

## 9. Policy Review

This policy is reviewed annually or upon significant changes to the CI/CD pipeline. All updates are versioned and tracked in Git.

---

**Approved by:** GrantRx Engineering
**Next review date:** 2027-09-05
