"""Tests for dashboard cookie-based session authentication."""

import pytest

from vinzy_engine.dashboard.auth import (
    create_session_cookie,
    verify_session_cookie,
)


class TestSessionCookie:
    """Cookie signing and verification."""

    def setup_method(self):
        import os
        os.environ["VINZY_SECRET_KEY"] = "test-secret-key"
        os.environ["VINZY_DB_URL"] = "sqlite+aiosqlite://"
        from vinzy_engine.common.config import get_settings
        get_settings.cache_clear()

    def test_create_and_verify(self):
        cookie = create_session_cookie("admin")
        payload = verify_session_cookie(cookie)
        assert payload is not None
        assert payload["role"] == "admin"

    def test_super_admin_role(self):
        cookie = create_session_cookie("super_admin")
        payload = verify_session_cookie(cookie)
        assert payload is not None
        assert payload["role"] == "super_admin"

    def test_invalid_cookie(self):
        payload = verify_session_cookie("garbage-value")
        assert payload is None

    def test_tampered_cookie(self):
        cookie = create_session_cookie("admin")
        # Tamper with the payload portion (before the dot separator)
        parts = cookie.split(".")
        if len(parts) >= 2:
            # Corrupt the payload portion
            tampered = "AAAA" + parts[0][4:] + "." + parts[1]
        else:
            tampered = "totally-invalid-cookie-value"
        payload = verify_session_cookie(tampered)
        assert payload is None
