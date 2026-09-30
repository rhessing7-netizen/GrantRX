"""Email-marketing provider adapter (R3).

The EdFintia database is the source of truth for waitlist leads. The provider
layer is a delivery/segmentation sync that runs AFTER the lead row has been
committed — it is never a prerequisite for signup and a failure here can
never lose a captured lead.

Concrete provider: EmailOctopus API v1.5. Credentials live server-side only;
no API key ever reaches the frontend bundle.

Required env vars:
  EMAILOCTOPUS_API_KEY   - EmailOctopus API key
  EMAILOCTOPUS_LIST_ID   - ID of the early-access/waitlist contact list
Optional:
  EMAILOCTOPUS_BASE_URL  - API base override (tests/sandbox); defaults to
                           https://emailoctopus.com/api/1.5
  EMAILOCTOPUS_TIMEOUT   - HTTP timeout seconds (default 5)

When EMAILOCTOPUS_API_KEY / EMAILOCTOPUS_LIST_ID are unset,
``get_email_marketing_provider()`` returns None: local/dev still works, the
DB save still succeeds, and the lead is marked ``skipped`` for later retry.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Optional, Protocol

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://emailoctopus.com/api/1.5"
DEFAULT_TIMEOUT_SECONDS = 5

# Provider tag applied to every early-access contact.
TAG_WAITLIST = "WAITLIST"

# Public-form audience_type -> EmailOctopus tag. Maps only what the form
# genuinely knows; never inferred from sensitive data. Future segments
# (CREATOR, CAMPUS_AMBASSADOR, MEDIA, NONPROFIT, FOUNDING_USER) join this map
# when their specialized forms exist.
AUDIENCE_TAGS = {
    "student": "STUDENT",
    "parent": "PARENT",
    "college_staff": "COLLEGE",
    "counselor": "COUNSELOR",
    "scholarship_organization": "SCHOLARSHIP_ORGANIZATION",
    "other": "OTHER",
}

_MAX_ERROR_LEN = 200


def waitlist_tags_for_audience(audience_type: Optional[str]) -> list[str]:
    """Segment tags derived from the audience the visitor self-selected."""
    tags = [TAG_WAITLIST]
    mapped = AUDIENCE_TAGS.get(audience_type or "")
    if mapped:
        tags.append(mapped)
    return tags


@dataclass
class ProviderSyncResult:
    """Outcome of a provider subscribe/update attempt."""

    status: str  # "synced" | "failed" | "skipped"
    error: Optional[str] = None


class EmailMarketingProvider(Protocol):
    """Small provider boundary — route handlers never talk to vendor APIs."""

    name: str

    def subscribe_or_update(
        self,
        *,
        email: str,
        first_name: str,
        tags: list[str],
        fields: Optional[dict] = None,
    ) -> ProviderSyncResult:
        """Idempotently create or update a contact and apply segment tags."""
        ...


def _bounded_error(exc: BaseException | str) -> str:
    text = " ".join(str(exc).split())
    return text[:_MAX_ERROR_LEN]


class EmailOctopusProvider:
    """EmailOctopus API v1.5 adapter.

    Upserts contacts via ``PUT /lists/{list_id}/contacts/{email_md5}`` —
    the digest-keyed PUT is idempotent, so duplicate signups and sync retries
    never create duplicate contacts or explode.

    Double opt-in: the Founding Waitlist list is configured for double opt-in,
    and this adapter preserves it by OMITTING ``status`` from the payload.
    Per the EmailOctopus API, an omitted status defaults to PENDING on a
    double-opt-in list, which triggers the list's own confirmation email;
    EmailOctopus flips the contact to SUBSCRIBED only after the subscriber
    confirms. EdFintia never marks a contact subscribed directly.
    """

    name = "emailoctopus"

    def __init__(
        self,
        api_key: str,
        list_id: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._list_id = list_id
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def subscribe_or_update(
        self,
        *,
        email: str,
        first_name: str,
        tags: list[str],
        fields: Optional[dict] = None,
    ) -> ProviderSyncResult:
        normalized = email.strip().lower()
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()  # noqa: S324 - required by vendor API
        url = f"{self._base_url}/lists/{self._list_id}/contacts/{digest}"
        payload = {
            # api_key in the JSON body (also accepted by the vendor) keeps the
            # credential out of URLs and therefore out of HTTP logs.
            "api_key": self._api_key,
            "email_address": normalized,
            # `status` is deliberately OMITTED: on a double-opt-in list an
            # omitted status creates the contact as PENDING and fires the
            # list's own confirmation flow — sending "subscribed" would bypass
            # it. On the upsert path (existing contact), omitting status also
            # leaves the contact's current state untouched, so retries and
            # resubmissions can never regress a confirmed subscriber to
            # pending or resubscribe an unsubscribed contact.
            "fields": {"FirstName": first_name, **(fields or {})},
            "tags": {tag: True for tag in tags},
        }
        try:
            resp = requests.put(url, json=payload, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("EmailOctopus sync request failed: %s", exc)
            return ProviderSyncResult(status="failed", error=_bounded_error(exc))

        if 200 <= resp.status_code < 300:
            return ProviderSyncResult(status="synced")

        detail = ""
        try:
            detail = str(resp.json().get("error", {}).get("message", ""))
        except Exception:  # noqa: BLE001
            detail = resp.text[:_MAX_ERROR_LEN]
        logger.warning(
            "EmailOctopus sync returned HTTP %s: %s", resp.status_code, detail
        )
        return ProviderSyncResult(
            status="failed",
            error=_bounded_error(f"HTTP {resp.status_code}: {detail}"),
        )


def get_email_marketing_provider() -> Optional[EmailMarketingProvider]:
    """Return the configured provider, or None when unconfigured.

    Called per-request (not module-cached) so environment changes and test
    patching take effect without a restart.
    """
    api_key = os.getenv("EMAILOCTOPUS_API_KEY", "").strip()
    list_id = os.getenv("EMAILOCTOPUS_LIST_ID", "").strip()
    if not api_key or not list_id:
        return None
    base_url = os.getenv("EMAILOCTOPUS_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    try:
        timeout = float(os.getenv("EMAILOCTOPUS_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    return EmailOctopusProvider(
        api_key=api_key,
        list_id=list_id,
        base_url=base_url,
        timeout_seconds=timeout,
    )
