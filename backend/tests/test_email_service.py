"""Transactional email (Resend) dependency tests.

Covers the Checkpoint A finding that `resend` was imported lazily but
missing from requirements.txt. These tests verify:
  - the email module imports cleanly
  - the send path no-ops safely when RESEND_API_KEY is unset
  - the send path calls resend.Emails.send when a key is configured
    (with resend stubbed — no external send ever occurs in tests)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services import email_service


class TestEmailModuleImport:
    def test_module_imports(self):
        """The email service module and its send surface import cleanly."""
        assert callable(email_service._send)
        assert callable(email_service.welcome_email)
        import resend  # noqa: F401 — the pinned dependency must be installed


class TestSendWithoutApiKey:
    def test_missing_key_noops(self):
        """No RESEND_API_KEY → _send returns False without importing/sending."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("RESEND_API_KEY", None)
            assert email_service._send("t@example.com", "subj", "body") is False

    def test_welcome_email_missing_key_noops(self):
        import os

        os.environ.pop("RESEND_API_KEY", None)
        assert email_service.welcome_email("t@example.com", "Ada") is False


class TestSendWithStubbedResend:
    def test_send_calls_resend_once(self):
        """With a key set and a stubbed resend module, exactly one send call
        is made with the expected payload — never a real network request."""
        fake_resend = MagicMock()
        fake_resend.Emails.send.return_value = {"id": "email_1"}
        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch.dict(sys.modules, {"resend": fake_resend}),
        ):
            ok = email_service._send("t@example.com", "Hello", "Body text")
            assert ok is True
            fake_resend.Emails.send.assert_called_once()
            params = fake_resend.Emails.send.call_args.args[0]
            assert params["to"] == "t@example.com"
            assert params["subject"] == "Hello"

    def test_send_failure_returns_false(self):
        """A provider exception must not propagate — _send returns False."""
        fake_resend = MagicMock()
        fake_resend.Emails.send.side_effect = RuntimeError("provider down")
        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_test_key"}),
            patch.dict(sys.modules, {"resend": fake_resend}),
        ):
            assert email_service._send("t@example.com", "subj", "body") is False
