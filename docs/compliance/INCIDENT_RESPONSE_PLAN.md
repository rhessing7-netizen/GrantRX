# Incident Response Plan

**Document ID:** GRX-IR-002
**Version:** 1.0
**Last Updated:** 2026-09-05
**Owner:** GrantRx Engineering
**Classification:** Internal

---

## 1. Purpose

This document defines the incident response plan for GrantRx, covering security breaches, data leaks, service outages, and other operational incidents. It establishes severity levels, a structured incident lifecycle, escalation chains, and notification protocols to ensure rapid, coordinated response.

## 2. Scope

This plan applies to:

- All GrantRx production infrastructure (Supabase, Render, Vercel, Stripe, GitHub)
- All user data incidents involving personally identifiable information (PII)
- All service availability incidents affecting end users
- All security events detected via monitoring, user reports, or third-party notifications

## 3. Incident Severity Levels

Incidents are classified into four severity levels based on impact, scope, and urgency:

### Sev-1: Critical

- **Definition:** Full service outage or confirmed data breach involving PII.
- **Impact:** All users affected; data integrity or confidentiality compromised.
- **Response Time:** Immediate (within 15 minutes of detection)
- **Examples:**
  - Database breach exposing user profiles or financial data
  - Complete API outage on Render
  - Stripe webhook compromise affecting billing
  - Unauthorized admin access

### Sev-2: High

- **Definition:** Partial service degradation or limited-scope data exposure.
- **Impact:** Subset of users affected; core functionality impaired but not fully down.
- **Response Time:** Within 1 hour of detection
- **Examples:**
  - Scholarship matching feed returning errors for 50%+ of users
  - Authentication service intermittent failures
  - Scraper pipeline failure affecting data freshness
  - Single tenant's data exposed to another tenant

### Sev-3: Medium

- **Definition:** Minor functionality issue or non-user-facing system failure.
- **Impact:** Limited user impact; workaround available.
- **Response Time:** Within 4 hours of detection
- **Examples:**
  - Export endpoints returning incorrect formatting
  - Digest email delivery delays
  - Non-critical background job failures
  - UI rendering bugs on non-core pages

### Sev-4: Low

- **Definition:** Cosmetic issue or internal-only system anomaly.
- **Impact:** No direct user impact.
- **Response Time:** Next business day
- **Examples:**
  - Log noise or deprecation warnings
  - Documentation errors
  - Non-blocking test failures in CI

## 4. Incident Lifecycle

Every incident follows a 5-step lifecycle:

### Step 1: Detection

- **Sources:** Automated monitoring alerts, user reports, Dependabot alerts, GitHub security advisories, Supabase anomaly detection, Stripe fraud alerts.
- **Action:** The first responder acknowledges the alert and performs initial triage to confirm the incident is real (not a false positive).
- **Output:** An incident ticket is created with a severity assignment (Sev-1 through Sev-4).

### Step 2: Containment

- **Goal:** Stop the bleeding — prevent further damage or data exfiltration.
- **Actions (severity-dependent):**
  - **Sev-1/Sev-2:** Rotate compromised credentials, revoke active sessions, isolate affected services, block malicious IPs, disable compromised service accounts.
  - **Sev-3/Sev-4:** Apply hotfix or rollback deployment, disable affected feature flag.
- **Output:** Containment actions are logged in the incident ticket with timestamps.

### Step 3: Eradication

- **Goal:** Remove the root cause completely.
- **Actions:**
  - Identify and patch the vulnerability or misconfiguration.
  - Remove malicious code, unauthorized access points, or corrupted data.
  - Update firewall rules, RLS policies, or access controls as needed.
  - Deploy the fix to production via the standard CI/CD pipeline.
- **Output:** Root cause is identified and documented; fix is deployed and verified.

### Step 4: Recovery

- **Goal:** Restore full service and verify system integrity.
- **Actions:**
  - Restore data from backups if data loss occurred.
  - Run full test suite (`python -m pytest backend/tests`) to verify system integrity.
  - Monitor system for 24 hours to confirm stability.
  - Communicate service restoration to affected users.
- **Output:** System is confirmed stable; monitoring returns to normal.

### Step 5: Post-Mortem

- **Goal:** Learn from the incident and prevent recurrence.
- **Actions:**
  - Conduct a blameless post-mortem within 5 business days of incident resolution.
  - Document: timeline, root cause, impact, containment actions, lessons learned.
  - Create action items with assigned owners and deadlines.
  - Share post-mortem with the team and update relevant policies.
- **Output:** Post-mortem document is filed in `docs/compliance/incidents/` and action items are tracked to completion.

## 5. Escalation Chain

### 5.1 Primary Escalation Path

```
Detection → First Responder (On-Call Engineer)
                ↓
         Severity Assessment
                ↓
    ┌──── Sev-1/Sev-2 ────┐    ┌──── Sev-3/Sev-4 ────┐
    ↓                     ↓    ↓                      ↓
Engineering Lead    Notify Owner    Assign Developer    Log Ticket
    ↓                     ↓
Notify Legal       Notify Affected
(if PII breach)     Users (if Sev-1)
```

### 5.2 Escalation Contacts

| Role | Responsibility | Contact Method |
|------|---------------|----------------|
| **On-Call Engineer** | First response, triage, containment | Pager / Slack on-call channel |
| **Engineering Lead** | Sev-1/Sev-2 escalation, resource coordination | Phone / Slack |
| **Owner** | Executive escalation, external communication | Phone / Email |
| **Legal Counsel** | PII breach notification compliance | Email (engaged within 24h for Sev-1) |

### 5.3 External Escalation

- **Supabase Support:** For database-level incidents, open a support ticket via the Supabase dashboard.
- **Render Support:** For hosting infrastructure issues, contact Render support.
- **Stripe Support:** For billing or payment processing incidents, contact Stripe support.
- **GitHub Security:** For repository security advisories, use GitHub's security advisory feature.

## 6. Notification Protocol

### 6.1 72-Hour User Data Breach Notification

For any incident involving exposure of user PII (Sev-1 or Sev-2 with data exposure):

| Timeframe | Action |
|-----------|--------|
| **0–4 hours** | Confirm breach scope; contain and eradicate |
| **4–24 hours** | Prepare breach notification; consult legal counsel |
| **24–48 hours** | Draft user-facing notification with: nature of breach, data affected, steps taken, user action required |
| **48–72 hours** | Send notification to all affected users via email; post public notice if required by law |
| **72 hours** | File compliance report with relevant authorities (if applicable under FERPA, state law, or contractual obligations) |

### 6.2 Internal Communication

- **Sev-1:** Real-time updates every 30 minutes until contained.
- **Sev-2:** Updates every 2 hours until contained.
- **Sev-3/4:** Daily updates until resolved.

### 6.3 User Communication Templates

Pre-approved templates are maintained for:

- Data breach notification
- Service outage notification
- Security advisory notification
- Service restoration notification

Templates are stored in `docs/compliance/templates/` and reviewed annually.

## 7. Backup and Recovery

### 7.1 Database Backups

- Supabase provides automated daily backups with point-in-time recovery (PITR) for up to 7 days.
- Critical data (profiles, user_scholarships, student_college_budgets) is included in the standard backup scope.

### 7.2 Recovery Testing

- Backup restoration is tested quarterly to verify data integrity and recovery time.
- Recovery time objective (RTO): 4 hours for Sev-1 incidents.
- Recovery point objective (RPO): 24 hours (maximum acceptable data loss).

## 8. Incident Documentation

All incidents are documented with the following minimum information:

- Incident ID and title
- Severity level
- Detection time and method
- Timeline of all actions taken
- Root cause analysis
- Impact assessment (users affected, data exposed, downtime duration)
- Resolution and verification
- Post-mortem document reference
- Action items and status

Incident records are retained for a minimum of 24 months.

## 9. Plan Review

This incident response plan is reviewed annually and after any Sev-1 or Sev-2 incident. Updates are versioned and tracked in Git.

---

**Approved by:** GrantRx Engineering
**Next review date:** 2027-09-05
