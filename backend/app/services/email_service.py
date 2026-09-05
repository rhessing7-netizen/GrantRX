"""Transactional email service for GrantRx.

Sends welcome, payment receipt, and dunning (failed payment) notifications
via the Resend API. All sends are graceful — if RESEND_API_KEY is not set or
the resend package is not installed, the function logs a warning and returns
without raising.

Templates:
  - welcome_email:        Sent on initial profile onboarding completion.
  - payment_receipt:      Sent on successful Stripe invoice payment.
  - dunning_notification: Sent when a Stripe invoice payment attempt fails.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

FROM_EMAIL = os.getenv("TRANSACTIONAL_FROM_EMAIL", "hello@grantrx.app")
APP_URL = os.getenv("APP_URL", "https://grant-rx.vercel.app")


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------


def _send(to: str, subject: str, text: str, html: Optional[str] = None) -> bool:
    """Send an email via Resend. Returns True on success, False on failure."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.info("RESEND_API_KEY not set — skipping email to %s", to)
        return False
    try:
        import resend  # type: ignore
    except ImportError:
        logger.warning("resend package not installed — skipping email to %s", to)
        return False

    try:
        resend.api_key = api_key
        params: dict = {"from": FROM_EMAIL, "to": to, "subject": subject, "text": text}
        if html:
            params["html"] = html
        resend.Emails.send(params)
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def welcome_email(to: str, name: Optional[str] = None) -> bool:
    """Send a welcome email after profile onboarding completion."""
    first = name.split(" ")[0] if name else "there"
    subject = "Welcome to GrantRx — your scholarship journey starts now"
    text = f"""Hi {first},

Welcome to GrantRx! Your profile is set up and you're ready to start
discovering scholarships tailored to your clinical discipline, GPA,
geographic area, and professional affiliations.

Here's what you can do next:
  • Browse your matched scholarship feed
  • Save promising awards to your Kanban board
  • Use the Financial Planner to project your 10-year loan amortization
  • Export deadlines to Google Calendar or Asana

Get started: {APP_URL}

— The GrantRx Team
"""
    html = f"""<html><body style="font-family: 'Sora', sans-serif; color: #1a1a2e; max-width: 560px; margin: 0 auto;">
<h1 style="font-family: 'Fraunces', serif; color: #5C7AFF;">Welcome to GrantRx</h1>
<p>Hi {first},</p>
<p>Your profile is set up and you're ready to start discovering scholarships tailored to your clinical discipline, GPA, geographic area, and professional affiliations.</p>
<p><strong>Here's what you can do next:</strong></p>
<ul>
  <li>Browse your matched scholarship feed</li>
  <li>Save promising awards to your Kanban board</li>
  <li>Use the Financial Planner to project your 10-year loan amortization</li>
  <li>Export deadlines to Google Calendar or Asana</li>
</ul>
<p><a href="{APP_URL}" style="background: #5C7AFF; color: #fff; padding: 12px 24px; border-radius: 999px; text-decoration: none; display: inline-block;">Get Started</a></p>
<p style="color: #64748b; font-size: 14px;">— The GrantRx Team</p>
</body></html>"""
    return _send(to, subject, text, html)


def payment_receipt(
    to: str,
    name: Optional[str] = None,
    amount: Optional[str] = None,
    plan: Optional[str] = None,
    invoice_url: Optional[str] = None,
) -> bool:
    """Send a payment receipt email after a successful Stripe invoice payment."""
    first = name.split(" ")[0] if name else "there"
    amount_display = amount or "your subscription"
    plan_display = plan or "Premium"
    subject = f"GrantRx Premium — payment receipt ({amount_display})"
    text = f"""Hi {first},

Your GrantRx {plan_display} subscription has been charged successfully.

Amount: {amount_display}
Plan: {plan_display}

{"View your invoice: " + invoice_url if invoice_url else ""}

You now have unlimited keyword searches, unmasked scholarship details, and
deadline reminder digests.

Manage your subscription: {APP_URL}

— The GrantRx Team
"""
    html = f"""<html><body style="font-family: 'Sora', sans-serif; color: #1a1a2e; max-width: 560px; margin: 0 auto;">
<h1 style="font-family: 'Fraunces', serif; color: #73FBD3;">Payment Received</h1>
<p>Hi {first},</p>
<p>Your GrantRx {plan_display} subscription has been charged successfully.</p>
<p><strong>Amount:</strong> {amount_display}<br><strong>Plan:</strong> {plan_display}</p>
{f'<p><a href="{invoice_url}">View your invoice</a></p>' if invoice_url else ''}
<p>You now have unlimited keyword searches, unmasked scholarship details, and deadline reminder digests.</p>
<p><a href="{APP_URL}" style="background: #5C7AFF; color: #fff; padding: 12px 24px; border-radius: 999px; text-decoration: none; display: inline-block;">Manage Subscription</a></p>
<p style="color: #64748b; font-size: 14px;">— The GrantRx Team</p>
</body></html>"""
    return _send(to, subject, text, html)


def dunning_notification(
    to: str,
    name: Optional[str] = None,
    amount: Optional[str] = None,
    attempt: Optional[int] = None,
    next_attempt: Optional[str] = None,
    invoice_url: Optional[str] = None,
) -> bool:
    """Send a dunning email when a Stripe invoice payment attempt fails."""
    first = name.split(" ")[0] if name else "there"
    amount_display = amount or "your subscription"
    attempt_display = f" (attempt #{attempt})" if attempt else ""
    subject = f"Action needed: GrantRx Premium payment failed{attempt_display}"
    text = f"""Hi {first},

We were unable to charge your payment method for your GrantRx Premium
subscription{attempt_display}.

Amount due: {amount_display}

{f"Next retry: {next_attempt}" if next_attempt else "We will retry automatically."}

{"Update your payment method: " + invoice_url if invoice_url else f"Update your payment method: {APP_URL}"}

If the payment is not completed, your subscription will be downgraded to
the Free tier. You can update your card anytime via the billing portal.

— The GrantRx Team
"""
    html = f"""<html><body style="font-family: 'Sora', sans-serif; color: #1a1a2e; max-width: 560px; margin: 0 auto;">
<h1 style="font-family: 'Fraunces', serif; color: #ef4444;">Payment Failed</h1>
<p>Hi {first},</p>
<p>We were unable to charge your payment method for your GrantRx Premium subscription{attempt_display}.</p>
<p><strong>Amount due:</strong> {amount_display}</p>
<p>{f"<strong>Next retry:</strong> {next_attempt}" if next_attempt else "We will retry automatically."}</p>
<p><a href="{invoice_url or APP_URL}" style="background: #5C7AFF; color: #fff; padding: 12px 24px; border-radius: 999px; text-decoration: none; display: inline-block;">Update Payment Method</a></p>
<p style="color: #64748b; font-size: 14px;">If the payment is not completed, your subscription will be downgraded to the Free tier.</p>
<p style="color: #64748b; font-size: 14px;">— The GrantRx Team</p>
</body></html>"""
    return _send(to, subject, text, html)
