# GrantRx production configuration

GrantRx uses environment variables as the source of truth for public URLs and branded identities. Do not hard-code deployment hostnames in application code.

Recommended production values:

```env
APP_URL=https://grantrx.com
API_BASE_URL=https://api.grantrx.com
PORTAL_RETURN_URL=https://grantrx.com/account
ALLOWED_ORIGINS=https://grantrx.com,https://www.grantrx.com
TRANSACTIONAL_FROM_EMAIL=hello@grantrx.com
DIGEST_FROM_EMAIL=digest@grantrx.com
PRIVACY_EMAIL=privacy@grantrx.com
CALENDAR_UID_DOMAIN=grantrx.com
```

Frontend:

```env
NEXT_PUBLIC_APP_URL=https://grantrx.com
NEXT_PUBLIC_API_URL=https://api.grantrx.com
NEXT_PUBLIC_PRIVACY_EMAIL=privacy@grantrx.com
# Optional GA4 measurement ID — when set, gtag.js loads and the
# early_access_* funnel events fire. Leave unset to disable analytics.
# NEXT_PUBLIC_GA_MEASUREMENT_ID=G-XXXXXXXXXX
```

The built-in URL fallbacks are localhost only. Production hosts must set the production values explicitly. This prevents a missing environment variable from silently routing users to an obsolete Vercel deployment or legacy domain.

## Early access / waitlist (R3)

`POST /api/v1/early-access` is public and persists leads to `waitlist_leads`
before any email-marketing sync. Optional environment variables:

```env
# EmailOctopus — server-side only. When unset, signups still persist and the
# lead's provider_sync_status is marked 'skipped' for later retry.
EMAILOCTOPUS_API_KEY=
EMAILOCTOPUS_LIST_ID=
# EMAILOCTOPUS_BASE_URL=https://emailoctopus.com/api/1.5
# EMAILOCTOPUS_TIMEOUT=5

# In-memory per-host rate limiting for the public signup endpoint.
# EARLY_ACCESS_RATE_LIMIT=10
# EARLY_ACCESS_RATE_WINDOW_SECONDS=300
```

## Catalog integrity invariants

- Curated seed URLs belong in `crawler_seeds`; they are not published scholarship records.
- Seed import must not invent award amounts, deadlines, GPA thresholds, disciplines, or other eligibility facts.
- Expired-scholarship archival is implemented by `app.services.archiver.archive_expired_scholarships`; scraper CLI paths call that same service rather than maintaining a second lifecycle rule.
