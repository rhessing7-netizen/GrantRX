# Access Control Policy

**Document ID:** GRX-AC-001
**Version:** 1.0
**Last Updated:** 2026-09-05
**Owner:** GrantRx Engineering
**Classification:** Internal

---

## 1. Purpose

This policy defines the access control standards for GrantRx, a scholarship discovery and application platform for clinical and healthcare students. It establishes Role-Based Access Control (RBAC), Multi-Factor Authentication (MFA) requirements, and credential management protocols across all production services.

## 2. Scope

This policy applies to:

- All administrative and production services: GitHub, Supabase, Render, Vercel, Stripe
- All team members with access to GrantRx infrastructure, code, or user data
- All service accounts, API keys, and deployment credentials

## 3. Role-Based Access Control (RBAC)

### 3.1 Principle of Least Privilege

Every user, service account, and automated process is granted the minimum level of access required to perform its function. Access rights are reviewed quarterly and revoked when no longer needed.

### 3.2 Defined Roles

| Role | Description | Access Level |
|------|-------------|--------------|
| **Owner** | Full administrative control over all services | Read, write, delete, manage billing, manage users |
| **Admin** | Infrastructure and deployment management | Read, write, deploy, manage secrets |
| **Developer** | Code contribution and review | Read, write (scoped branches), PR creation |
| **Service Account** | Automated CI/CD and scraper processes | Scoped API keys with single-purpose permissions |
| **Auditor** | Read-only compliance review | Read-only access to logs, configs, and audit trails |

### 3.3 Access Provisioning

1. New access requests must be submitted via a tracked issue and approved by the Owner.
2. Access is provisioned within 24 hours of approval.
3. Default access for new developers is the **Developer** role only.

### 3.4 Access Deprovisioning

1. Access is revoked within 4 hours of role change or departure.
2. A quarterly access review is conducted to verify active users and remove stale accounts.
3. Service account keys are rotated every 90 days (see Section 5).

## 4. Multi-Factor Authentication (MFA)

### 4.1 Mandatory MFA Enforcement

MFA is **mandatory** for all administrative access to the following services:

| Service | MFA Method | Enforcement |
|---------|------------|-------------|
| **GitHub** | TOTP or hardware key | Enforced via organization policy |
| **Supabase** | TOTP | Enforced via Supabase dashboard settings |
| **Render** | TOTP | Enforced via Render account settings |
| **Vercel** | TOTP or hardware key | Enforced via Vercel team settings |
| **Stripe** | TOTP (required by Stripe) | Enforced by Stripe for dashboard access |

### 4.2 MFA Acceptable Methods

- **Preferred:** Hardware security keys (YubiKey, Titan) via WebAuthn/FIDO2
- **Acceptable:** TOTP authenticator apps (Google Authenticator, Authy, 1Password)
- **Prohibited:** SMS-based MFA (except as a Stripe-required fallback)

### 4.3 MFA Enforcement Verification

- MFA status is verified during the quarterly access review.
- Any account found without MFA enabled is suspended until remediated.

## 5. Password and Credential Management

### 5.1 Password Complexity Requirements

All user and admin passwords must meet the following minimum standards:

- Minimum length: 14 characters
- Must include at least one uppercase letter, one lowercase letter, one number, and one special character
- Must not match any known breached password (checked against Have I Been Pwned API or equivalent)
- Must not be reused from the last 5 passwords

### 5.2 Credential Rotation Protocol

| Credential Type | Rotation Frequency | Storage |
|-----------------|-------------------|---------|
| Admin passwords | Every 90 days | Password manager (1Password, Bitwarden) |
| Service API keys (Supabase, Stripe, Resend) | Every 90 days | GitHub Secrets / environment secrets |
| Database connection strings | Every 90 days | Render environment variables + GitHub Secrets |
| JWT signing keys | Every 180 days | Supabase project settings |
| OAuth client secrets | Every 180 days | Provider dashboards |
| Deployment tokens | Every 90 days | Vercel / Render project settings |

### 5.3 Secret Storage Standards

- **No secrets in code.** All secrets are stored as environment variables or GitHub Secrets.
- **No secrets in commits.** Pre-commit hooks and GitHub secret scanning are enabled to prevent accidental commits.
- **Secret access logging.** Access to production secrets is logged and reviewed monthly.

### 5.4 Service Account Management

- Each service account has a single, clearly defined purpose.
- Service account keys are scoped to the minimum required permissions.
- Unused service accounts are disabled within 7 days of identification.
- Service account activity is monitored for anomalous behavior.

## 6. Authentication Architecture

### 6.1 User Authentication

- Users authenticate via Supabase Auth using email/password or OAuth (Google, GitHub).
- JWT tokens are issued with a 1-hour expiry; refresh tokens are used for session persistence.
- The backend validates JWTs on every authenticated request via the `JWTMiddleware`.

### 6.2 Admin Authentication

- Admin endpoints (`/api/admin/*`) require `role: "service_role"` in the JWT payload.
- Admin tokens are issued only to service accounts and are never shared with end users.
- Admin actions are logged with timestamp, actor, and action details.

### 6.3 Development Environment

- In development mode (`ENVIRONMENT=development`), a demo token is accepted for local testing.
- The demo token is **never** accepted in production.
- Production deployments must set `ENVIRONMENT=production` to enforce strict JWT validation.

## 7. Compliance and Audit

### 7.1 Audit Logging

- All authentication events (login, logout, failed attempts) are logged.
- All access to user data is traceable to an authenticated user ID.
- Logs are retained for a minimum of 12 months.

### 7.2 Policy Review

This policy is reviewed annually or upon significant infrastructure changes. All updates are versioned and tracked in Git.

## 8. Enforcement

Violations of this policy may result in:

1. Immediate suspension of access (for active security risks)
2. Formal review and remediation plan (for procedural violations)
3. Termination of access (for repeated or willful violations)

---

**Approved by:** GrantRx Engineering
**Next review date:** 2027-09-05
