"""End-to-end provisioning lifecycle test.

Verify the full tenant lifecycle including retry logic, circuit breaker,
graceful degradation, and structured logging.
"""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from vinzy_engine.provisioning.zuultimate_client import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    ZuultimateClient,
    _CB_FAILURE_THRESHOLD,
    _CB_RECOVERY_TIMEOUT,
    _MAX_RETRIES,
)


def _make_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response with the given status code."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    resp.request = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"Error {status_code}", request=resp.request, response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_client(**kwargs) -> ZuultimateClient:
    """Build a ZuultimateClient with a no-op sleep to avoid real delays."""
    return ZuultimateClient(
        base_url="https://zuultimate.test",
        service_token="svc_test",
        sleep_func=AsyncMock(),
        **kwargs,
    )


def _patch_httpx(mock_client: AsyncMock):
    """Return a context manager that patches httpx.AsyncClient."""
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=mock_client)


_PROVISION_KWARGS = dict(
    name="Test Corp",
    slug="test-corp-ab12",
    owner_email="admin@test.com",
    owner_username="admin",
    owner_password="securepass",
    plan="pro",
)


class TestFullProvisioningLifecycle:
    """Happy-path: provision tenant, verify response, confirm circuit stays closed."""

    async def test_full_provisioning_lifecycle(self):
        """Provision a tenant and verify the returned tenant_id."""
        zuul_response = {
            "tenant_id": "t_lifecycle_001",
            "user_id": "u_001",
            "api_key": "gzr_key",
            "plan": "pro",
            "entitlements": ["trendscope:full"],
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = _make_response(201, zuul_response)

        zc = _make_client()

        with _patch_httpx(mock_client):
            result = await zc.provision_tenant(**_PROVISION_KWARGS)

        assert result["tenant_id"] == "t_lifecycle_001"
        assert result["plan"] == "pro"
        assert zc.circuit_breaker.state is CircuitState.CLOSED
        mock_client.post.assert_called_once()

        # Verify the payload sent
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["X-Service-Token"] == "svc_test"
        assert call_kwargs.kwargs["json"]["name"] == "Test Corp"


class TestRetryOn5xx:
    """Retry behavior for server errors."""

    async def test_provisioning_retries_on_5xx(self):
        """Return 500 twice then 200 — verify retry succeeds."""
        success_resp = _make_response(201, {"tenant_id": "t_retry_ok"})
        fail_resp_500 = MagicMock(spec=httpx.Response)
        fail_resp_500.status_code = 500
        fail_resp_500.is_success = False
        fail_resp_500.request = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.side_effect = [fail_resp_500, fail_resp_500, success_resp]

        zc = _make_client()

        with _patch_httpx(mock_client):
            result = await zc.provision_tenant(**_PROVISION_KWARGS)

        assert result["tenant_id"] == "t_retry_ok"
        assert mock_client.post.call_count == 3
        assert zc.circuit_breaker.state is CircuitState.CLOSED

    async def test_retries_exhausted_raises(self):
        """All retries fail with 500 — verify exception raised."""
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.is_success = False
        fail_resp.request = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = fail_resp

        zc = _make_client()

        with _patch_httpx(mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        assert mock_client.post.call_count == _MAX_RETRIES + 1


class TestNoRetryOn4xx:
    """Client errors should not trigger retries."""

    async def test_no_retry_on_4xx(self):
        """Return 400 — verify no retry attempted."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _make_response(400)

        zc = _make_client()

        with _patch_httpx(mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        mock_client.post.assert_called_once()

    async def test_no_retry_on_404(self):
        """Return 404 — verify no retry attempted."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _make_response(404)

        zc = _make_client()

        with _patch_httpx(mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        mock_client.post.assert_called_once()


class TestCircuitBreakerOpens:
    """Circuit breaker opens after consecutive failures."""

    async def test_circuit_breaker_opens_after_failures(self):
        """Trigger 5 consecutive failures then verify the 6th request is rejected immediately."""
        zc = _make_client()

        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.is_success = False
        fail_resp.request = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = fail_resp

        # Exhaust retries multiple times to accumulate failures in the breaker
        # Each call does up to 4 attempts (1 + 3 retries), recording a failure each time
        with _patch_httpx(mock_client):
            for _ in range(2):
                try:
                    await zc.provision_tenant(**_PROVISION_KWARGS)
                except (httpx.HTTPStatusError, CircuitBreakerOpen):
                    pass

        # Circuit should be open now (at least 5 consecutive failures recorded)
        assert zc.circuit_breaker.state is CircuitState.OPEN

        # Next request should be rejected immediately without HTTP call
        mock_client.post.reset_mock()
        with _patch_httpx(mock_client):
            with pytest.raises(CircuitBreakerOpen):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        mock_client.post.assert_not_called()


class TestCircuitBreakerHalfOpen:
    """Circuit breaker transitions to HALF_OPEN and recovers on probe success."""

    async def test_circuit_breaker_half_open_probe(self):
        """After failures and recovery timeout, allow one probe and recover on success."""
        zc = _make_client()
        cb = zc.circuit_breaker

        # Force the breaker open
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state is CircuitState.OPEN

        # Simulate time passing beyond recovery timeout
        cb._opened_at = time.monotonic() - _CB_RECOVERY_TIMEOUT - 1
        assert cb.state is CircuitState.HALF_OPEN

        # Probe request succeeds
        success_resp = _make_response(201, {"tenant_id": "t_recovered"})
        mock_client = AsyncMock()
        mock_client.post.return_value = success_resp

        with _patch_httpx(mock_client):
            result = await zc.provision_tenant(**_PROVISION_KWARGS)

        assert result["tenant_id"] == "t_recovered"
        assert cb.state is CircuitState.CLOSED

    async def test_circuit_breaker_half_open_probe_fails(self):
        """After recovery timeout, a failed probe re-opens the breaker."""
        zc = _make_client()
        cb = zc.circuit_breaker

        # Force the breaker open then transition to half-open
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        cb._opened_at = time.monotonic() - _CB_RECOVERY_TIMEOUT - 1
        assert cb.state is CircuitState.HALF_OPEN

        # Probe request fails
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.is_success = False
        fail_resp.request = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = fail_resp

        with _patch_httpx(mock_client):
            with pytest.raises((httpx.HTTPStatusError, CircuitBreakerOpen)):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        assert cb.state is CircuitState.OPEN


class TestGracefulDegradation:
    """Vinzy-engine continues provisioning when Zuultimate is unreachable."""

    async def test_graceful_degradation_when_zuultimate_down(self, client, admin_headers):
        """Mock all Zuultimate calls failing — verify provisioning completes without tenant_id."""
        # Set up product first
        resp = await client.post(
            "/products",
            json={"code": "AGW", "name": "Agent Gateway"},
            headers=admin_headers,
        )
        assert resp.status_code == 201

        with patch.object(
            ZuultimateClient,
            "provision_tenant",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ), patch.dict("os.environ", {"VINZY_STRIPE_WEBHOOK_SECRET": "whsec_test"}), patch(
            "vinzy_engine.provisioning.router.verify_stripe_signature",
            return_value=True,
        ):
            payload = {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_degrade_001",
                        "customer_email": "degrade@example.com",
                        "customer_details": {
                            "name": "Degrade Buyer",
                            "email": "degrade@example.com",
                        },
                        "metadata": {
                            "product_code": "AGW",
                            "tier": "pro",
                            "company": "Degrade Corp",
                        },
                    }
                },
            }

            resp = await client.post(
                "/webhooks/stripe",
                json=payload,
                headers=admin_headers,
            )
            # Provisioning succeeds even without Zuultimate
            assert resp.status_code in (200, 202), resp.text

        # Verify customer was still created
        cust_resp = await client.get("/customers", headers=admin_headers)
        assert cust_resp.status_code == 200
        emails = [c["email"] for c in cust_resp.json()]
        assert "degrade@example.com" in emails


class TestStructuredLogging:
    """Verify log entries contain duration, status, and circuit state."""

    async def test_structured_logging_on_success(self, caplog):
        """Verify success log contains duration_ms, status_code, and circuit_state."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _make_response(201, {"tenant_id": "t_log"})

        zc = _make_client()

        with caplog.at_level(logging.INFO, logger="vinzy_engine.provisioning.zuultimate_client"):
            with _patch_httpx(mock_client):
                await zc.provision_tenant(**_PROVISION_KWARGS)

        assert any("Zuultimate provision succeeded" in rec.message for rec in caplog.records)
        info_records = [r for r in caplog.records if "succeeded" in r.message]
        assert len(info_records) >= 1
        rec = info_records[0]
        assert hasattr(rec, "duration_ms")
        assert hasattr(rec, "status_code")
        assert hasattr(rec, "circuit_state")
        assert rec.circuit_state == "closed"

    async def test_structured_logging_on_failure(self, caplog):
        """Verify failure log contains attempt number and circuit state."""
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.is_success = False
        fail_resp.request = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = fail_resp

        zc = _make_client()

        with caplog.at_level(logging.WARNING, logger="vinzy_engine.provisioning.zuultimate_client"):
            with _patch_httpx(mock_client):
                with pytest.raises((httpx.HTTPStatusError, CircuitBreakerOpen)):
                    await zc.provision_tenant(**_PROVISION_KWARGS)

        warning_records = [r for r in caplog.records if "will retry" in r.message or "OPEN" in r.message]
        assert len(warning_records) >= 1
        for rec in warning_records:
            assert hasattr(rec, "circuit_state")

    async def test_structured_logging_on_connection_error(self, caplog):
        """Verify connection error log contains error details."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        zc = _make_client()

        with caplog.at_level(logging.WARNING, logger="vinzy_engine.provisioning.zuultimate_client"):
            with _patch_httpx(mock_client):
                with pytest.raises((httpx.ConnectError, CircuitBreakerOpen)):
                    await zc.provision_tenant(**_PROVISION_KWARGS)

        conn_records = [r for r in caplog.records if "connection error" in r.message]
        assert len(conn_records) >= 1
        assert hasattr(conn_records[0], "error")


class TestCircuitBreakerUnit:
    """Direct unit tests for the CircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Verify breaker starts in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state is CircuitState.CLOSED

    def test_stays_closed_under_threshold(self):
        """Verify breaker stays closed with fewer failures than the threshold."""
        cb = CircuitBreaker()
        for _ in range(_CB_FAILURE_THRESHOLD - 1):
            cb.record_failure()
        assert cb.state is CircuitState.CLOSED

    def test_opens_at_threshold(self):
        """Verify breaker opens exactly at the failure threshold."""
        cb = CircuitBreaker()
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_success_resets_counter(self):
        """Verify a success resets the failure counter."""
        cb = CircuitBreaker()
        for _ in range(_CB_FAILURE_THRESHOLD - 1):
            cb.record_failure()
        cb.record_success()
        assert cb.state is CircuitState.CLOSED
        # Should need full threshold again
        for _ in range(_CB_FAILURE_THRESHOLD - 1):
            cb.record_failure()
        assert cb.state is CircuitState.CLOSED

    def test_allow_request_when_closed(self):
        """Verify requests are allowed when circuit is closed."""
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_reject_request_when_open(self):
        """Verify requests are rejected when circuit is open."""
        cb = CircuitBreaker()
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.allow_request() is False

    def test_allow_request_when_half_open(self):
        """Verify one probe request is allowed in HALF_OPEN state."""
        cb = CircuitBreaker()
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        cb._opened_at = time.monotonic() - _CB_RECOVERY_TIMEOUT - 1
        assert cb.state is CircuitState.HALF_OPEN
        assert cb.allow_request() is True
