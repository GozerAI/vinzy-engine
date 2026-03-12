"""Tests for client.py — LicenseClient SDK with resilience."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta

import httpx

from vinzy_engine.client import (
    LicenseClient,
    ClientActivationResult,
    ClientLicense,
    ClientUsageResult,
    ClientValidationResult,
)


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


class TestLicenseClientInit:
    def test_defaults(self):
        client = LicenseClient()
        assert client.server_url == "http://localhost:8080"
        assert client.license_key is None
        assert client.max_retries == 3
        client.close()

    def test_custom_params(self):
        client = LicenseClient(
            server_url="http://custom:9090/",
            license_key="my-key",
            api_key="admin-key",
            cache_ttl=600,
            timeout=10,
            max_retries=5,
        )
        assert client.server_url == "http://custom:9090"
        assert client.license_key == "my-key"
        assert client.api_key == "admin-key"
        assert client.max_retries == 5
        client.close()


class TestClientValidate:
    def test_valid_response(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({
            "valid": True,
            "code": "OK",
            "message": "License is valid",
            "license": {
                "id": "lic-1",
                "key": "test-key",
                "status": "active",
                "product_code": "ZUL",
                "customer_id": "cust-1",
                "tier": "pro",
                "features": ["api", "export"],
                "entitlements": {},
            },
            "features": ["api", "export"],
            "entitlements": [
                {"feature": "api", "enabled": True, "limit": None, "used": 0, "remaining": None},
            ],
            "lease": {
                "payload": {"license_id": "lic-1", "status": "active"},
                "signature": "abc",
                "lease_expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            },
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.validate(fingerprint="fp-123")
        assert result.valid is True
        assert result.code == "OK"
        assert result.license.product_code == "ZUL"
        assert len(result.entitlements) == 1
        assert result.lease is not None
        client.close()

    def test_invalid_response(self):
        client = LicenseClient(license_key="bad-key")
        mock_resp = _mock_response({
            "valid": False,
            "code": "NOT_FOUND",
            "message": "License not found",
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.validate()
        assert result.valid is False
        assert result.license is None
        client.close()


class TestClientActivate:
    def test_activate_success(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({
            "success": True,
            "machine_id": "mach-1",
            "code": "ACTIVATED",
            "message": "Activated",
            "license": {
                "id": "lic-1", "key": "test-key", "status": "active",
                "product_code": "ZUL", "customer_id": "c1", "tier": "standard",
            },
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.activate("fp-1", hostname="host")
        assert result.success is True
        assert result.machine_id == "mach-1"
        client.close()

    def test_deactivate(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({"success": True})
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        assert client.deactivate("fp-1") is True
        client.close()


class TestClientHeartbeat:
    def test_heartbeat_success(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({"success": True})
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        assert client.heartbeat("fp-1", "1.0") is True
        client.close()

    def test_heartbeat_failure(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({"success": False})
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        assert client.heartbeat("fp-1") is False
        client.close()


class TestClientUsage:
    def test_record_usage(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({
            "success": True,
            "metric": "api-calls",
            "value_added": 5.0,
            "total_value": 150.0,
            "limit": 1000,
            "remaining": 850.0,
            "code": "RECORDED",
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.record_usage("api-calls", 5.0)
        assert result.success is True
        assert result.total_value == 150.0
        assert result.remaining == 850.0
        client.close()

    def test_record_usage_no_limit(self):
        client = LicenseClient(license_key="test-key")
        mock_resp = _mock_response({
            "success": True,
            "metric": "events",
            "value_added": 1.0,
            "total_value": 1.0,
            "limit": None,
            "remaining": None,
            "code": "RECORDED",
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.record_usage("events")
        assert result.limit is None
        client.close()


class TestParseLicense:
    def test_with_expires_at(self):
        lic = LicenseClient._parse_license({
            "id": "1", "key": "k", "status": "active",
            "product_code": "ZUL", "customer_id": "c", "tier": "pro",
            "expires_at": "2027-01-01T00:00:00+00:00",
        })
        assert isinstance(lic.expires_at, datetime)

    def test_without_expires_at(self):
        lic = LicenseClient._parse_license({
            "id": "1", "key": "k", "status": "active",
            "product_code": "ZUL", "customer_id": "c", "tier": "pro",
        })
        assert lic.expires_at is None

    def test_invalid_expires_at(self):
        lic = LicenseClient._parse_license({
            "id": "1", "key": "k", "status": "active",
            "product_code": "ZUL", "customer_id": "c", "tier": "pro",
            "expires_at": "not-a-date",
        })
        assert lic.expires_at is None


# ── Phase 5: Resilience tests ──


class TestRetryOnTimeout:
    @patch("vinzy_engine.client.time.sleep")
    def test_retry_on_timeout(self, mock_sleep):
        client = LicenseClient(license_key="test-key", max_retries=3)
        client._http = MagicMock()
        client._http.post.side_effect = httpx.TimeoutException("timeout")

        result = client.validate()
        assert result.valid is False
        assert result.code == "NO_LEASE"  # falls back to cache, no cache available
        assert client._http.post.call_count == 3
        client.close()


class TestNoRetryOn4xx:
    def test_no_retry_on_404(self):
        client = LicenseClient(license_key="test-key", max_retries=3)
        client._http = MagicMock()
        client._http.get.return_value = _mock_response({}, status_code=404)

        result = client._request("get", "/validate")
        assert result["code"] == "CLIENT_ERROR"
        assert client._http.get.call_count == 1  # no retry
        client.close()


class TestRetryOn500:
    @patch("vinzy_engine.client.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        client = LicenseClient(license_key="test-key", max_retries=3)
        client._http = MagicMock()
        client._http.get.return_value = _mock_response({}, status_code=500)

        result = client._request("get", "/validate")
        assert result["code"] == "SERVER_ERROR"
        assert client._http.get.call_count == 3
        client.close()


class TestRetriesExhausted:
    @patch("vinzy_engine.client.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep):
        client = LicenseClient(license_key="test-key", max_retries=2)
        client._http = MagicMock()
        client._http.post.side_effect = httpx.TimeoutException("timeout")

        result = client._request("post", "/activate")
        assert result["code"] == "CONNECTION_ERROR"
        assert "2 retries exhausted" in result["error"]
        client.close()


class TestValidateFallbackToCache:
    @patch("vinzy_engine.client.time.sleep")
    def test_fallback_to_cached_lease(self, mock_sleep):
        client = LicenseClient(license_key="test-key", max_retries=1)
        client._http = MagicMock()
        client._http.post.side_effect = httpx.TimeoutException("timeout")

        # Pre-populate cached lease
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        client._cached_lease = {
            "payload": {"features": ["api"], "status": "active"},
            "signature": "sig",
            "lease_expires_at": future,
        }
        client._lease_cached_at = __import__("time").time()

        result = client.validate()
        assert result.valid is True
        assert result.code == "OFFLINE_VALID"
        assert result.features == ["api"]
        client.close()


class TestNoCacheReturnsNoLease:
    @patch("vinzy_engine.client.time.sleep")
    def test_no_cache(self, mock_sleep):
        client = LicenseClient(license_key="test-key", max_retries=1)
        client._http = MagicMock()
        client._http.post.side_effect = httpx.TimeoutException("timeout")

        result = client.validate()
        assert result.valid is False
        assert result.code == "NO_LEASE"
        client.close()


class TestCachesLeaseFromResponse:
    def test_caches_lease(self):
        client = LicenseClient(license_key="test-key")
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        mock_resp = _mock_response({
            "valid": True,
            "code": "OK",
            "message": "OK",
            "lease": {
                "payload": {"features": ["api"]},
                "signature": "sig",
                "lease_expires_at": future,
            },
        })
        client._http = MagicMock()
        client._http.post.return_value = mock_resp

        result = client.validate()
        assert result.valid is True
        assert client._cached_lease is not None
        assert client._cached_lease["payload"]["features"] == ["api"]
        client.close()


class TestValidateOffline:
    def test_validate_offline_valid(self):
        client = LicenseClient(license_key="test-key")
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        client._cached_lease = {
            "payload": {"features": ["api"]},
            "signature": "sig",
            "lease_expires_at": future,
        }
        result = client.validate_offline()
        assert result.valid is True
        assert result.code == "OFFLINE_VALID"
        client.close()

    def test_validate_offline_expired(self):
        client = LicenseClient(license_key="test-key")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        client._cached_lease = {
            "payload": {"features": ["api"]},
            "signature": "sig",
            "lease_expires_at": past,
        }
        result = client.validate_offline()
        assert result.valid is False
        assert result.code == "LEASE_EXPIRED"
        client.close()


class TestJsonDecodeError:
    def test_json_decode_error(self):
        client = LicenseClient(license_key="test-key")
        client._http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("err", "", 0)
        client._http.get.return_value = mock_resp

        result = client._request("get", "/validate")
        assert result["code"] == "JSON_ERROR"
        client.close()
