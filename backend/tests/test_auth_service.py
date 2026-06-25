from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.auth_service import build_oauth_scopes, compute_token_expiry, gmail_scopes_granted


def test_build_oauth_scopes_contains_required_scopes():
    scopes = build_oauth_scopes().split()
    assert "openid" in scopes
    assert "email" in scopes
    assert "profile" in scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert "https://www.googleapis.com/auth/gmail.send" in scopes


def test_compute_token_expiry_uses_expires_at_when_present():
    expiry = compute_token_expiry({"expires_at": 1735689600})
    assert expiry == datetime.fromtimestamp(1735689600, tz=UTC)


def test_compute_token_expiry_uses_expires_in_when_present():
    before = datetime.now(UTC)
    expiry = compute_token_expiry({"expires_in": 3600})
    after = datetime.now(UTC)
    assert expiry is not None
    assert before + timedelta(seconds=3599) <= expiry <= after + timedelta(seconds=3601)


def test_gmail_scopes_granted_requires_both_scopes():
    both = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
    assert gmail_scopes_granted(both) is True
    assert gmail_scopes_granted("https://www.googleapis.com/auth/gmail.readonly") is False
    assert gmail_scopes_granted(None) is False
