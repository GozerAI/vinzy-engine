"""Tests for IP allowlist middleware."""

import pytest
from starlette.testclient import TestClient


class TestIPAllowlistMiddleware:
    def test_localhost_always_allowed(self):
        """127.0.0.1 is always in the allowlist, even with empty list."""
        import ipaddress
        from vinzy_engine.common.ip_filter import IPAllowlistMiddleware
        from starlette.applications import Starlette

        app = Starlette()
        mw = IPAllowlistMiddleware(app, allowlist=["10.0.0.0/8"])

        # Verify localhost IPs are in the networks
        assert any(
            ipaddress.ip_address("127.0.0.1") in net for net in mw._networks
        )
        assert any(
            ipaddress.ip_address("::1") in net for net in mw._networks
        )

    def test_blocked_ip_rejected(self):
        """An IP not in the allowlist should be rejected."""
        import ipaddress
        from vinzy_engine.common.ip_filter import IPAllowlistMiddleware
        from starlette.applications import Starlette

        app = Starlette()
        mw = IPAllowlistMiddleware(app, allowlist=["192.168.1.0/24"])

        # 8.8.8.8 is not in 192.168.1.0/24 or localhost
        assert not any(
            ipaddress.ip_address("8.8.8.8") in net for net in mw._networks
        )

    def test_cidr_matching(self):
        """Verify CIDR notation works."""
        import ipaddress
        from vinzy_engine.common.ip_filter import IPAllowlistMiddleware
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        async def homepage(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/", homepage)])
        mw = IPAllowlistMiddleware(app, allowlist=["10.0.0.0/8"])

        # Verify internal network list has the CIDR
        assert any(
            ipaddress.ip_address("10.1.2.3") in net
            for net in mw._networks
        )

    def test_single_ip_in_allowlist(self):
        """Single IP (not CIDR) should work."""
        import ipaddress
        from vinzy_engine.common.ip_filter import IPAllowlistMiddleware
        from starlette.applications import Starlette

        app = Starlette()
        mw = IPAllowlistMiddleware(app, allowlist=["203.0.113.50"])

        assert any(
            ipaddress.ip_address("203.0.113.50") in net
            for net in mw._networks
        )


class TestIPAllowlistConfig:
    def test_settings_have_ip_fields(self):
        from vinzy_engine.common.config import VinzySettings
        s = VinzySettings(
            ip_allowlist_enabled=True,
            ip_allowlist=["10.0.0.0/8", "192.168.1.0/24"],
        )
        assert s.ip_allowlist_enabled is True
        assert len(s.ip_allowlist) == 2

    def test_defaults_disabled(self):
        from vinzy_engine.common.config import VinzySettings
        s = VinzySettings()
        assert s.ip_allowlist_enabled is False
        assert s.ip_allowlist == []

    def test_app_skips_middleware_when_disabled(self, app):
        """When ip_allowlist_enabled is False, middleware is not added."""
        # The default fixture sets ip_allowlist_enabled=False
        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m, 'cls')]
        assert "IPAllowlistMiddleware" not in middleware_classes
