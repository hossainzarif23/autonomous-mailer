from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import TestCase

from app.services.auth_service import build_oauth_scopes, compute_token_expiry, gmail_scopes_granted


class AuthServiceTests(TestCase):
    def test_build_oauth_scopes_contains_required_scopes(self):
        scopes = build_oauth_scopes().split()
        self.assertIn("openid", scopes)
        self.assertIn("email", scopes)
        self.assertIn("profile", scopes)
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/gmail.send", scopes)

    def test_compute_token_expiry_uses_expires_at_when_present(self):
        expiry = compute_token_expiry({"expires_at": 1735689600})
        self.assertEqual(expiry, datetime.fromtimestamp(1735689600, tz=UTC))

    def test_compute_token_expiry_uses_expires_in_when_present(self):
        before = datetime.now(UTC)
        expiry = compute_token_expiry({"expires_in": 3600})
        after = datetime.now(UTC)
        self.assertIsNotNone(expiry)
        lower_bound = before + timedelta(seconds=3599)
        upper_bound = after + timedelta(seconds=3601)
        self.assertGreaterEqual(expiry, lower_bound)
        self.assertLessEqual(expiry, upper_bound)

    def test_gmail_scopes_granted_requires_both_scopes(self):
        both_scopes = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
        self.assertTrue(gmail_scopes_granted(both_scopes))
        self.assertFalse(gmail_scopes_granted("https://www.googleapis.com/auth/gmail.readonly"))
        self.assertFalse(gmail_scopes_granted(None))
