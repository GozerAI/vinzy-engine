"""Tests for ZuultimateClient blind pass methods (Phase F.3)."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from vinzy_engine.provisioning.zuultimate_client import (
    CircuitBreakerOpen,
    ZuultimateClient,
)


@pytest.fixture
def client():
    return ZuultimateClient(
        base_url="http://zuultimate:8000",
        service_token="test-token",
        sleep_func=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# request_blind_pass
# ---------------------------------------------------------------------------


async def test_request_blind_pass_returns_token_and_shard(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "token": "bp_abc123",
        "purpose": "provisioning",
        "sovereignty_ring": "us",
        "expires_at": "2027-03-12T00:00:00+00:00",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        token, shard = await client.request_blind_pass("tenant-123")

    assert token == "bp_abc123"
    assert isinstance(shard, bytes)
    assert len(shard) == 32


async def test_request_blind_pass_sends_correct_payload(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"token": "bp_xyz"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await client.request_blind_pass("tenant-456", purpose="audit")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://zuultimate:8000/v1/vault/blind-pass"
    payload = call_args[1]["json"]
    assert payload["tenant_id"] == "tenant-456"
    assert payload["purpose"] == "audit"
    assert len(payload["client_key_shard"]) == 64  # hex of 32 bytes


async def test_request_blind_pass_records_failure_on_error(client):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.ConnectError):
            await client.request_blind_pass("tenant-fail")

    assert client.circuit_breaker._consecutive_failures == 1


async def test_request_blind_pass_circuit_breaker_open(client):
    # Open the circuit breaker
    for _ in range(5):
        client.circuit_breaker.record_failure()

    with pytest.raises(CircuitBreakerOpen):
        await client.request_blind_pass("tenant-blocked")


# ---------------------------------------------------------------------------
# verify_authorization
# ---------------------------------------------------------------------------


async def test_verify_authorization_returns_true(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {"valid": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.verify_authorization("lease-sig", "bp_token")

    assert result is True


async def test_verify_authorization_returns_false_on_invalid(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {"valid": False}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.verify_authorization("bad-sig", "bp_token")

    assert result is False


async def test_verify_authorization_returns_false_on_error(client):
    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await client.verify_authorization("lease-sig", "bp_token")

    assert result is False


async def test_verify_authorization_circuit_breaker_open(client):
    for _ in range(5):
        client.circuit_breaker.record_failure()

    with pytest.raises(CircuitBreakerOpen):
        await client.verify_authorization("lease-sig", "bp_token")


# ---------------------------------------------------------------------------
# revoke_blind_pass
# ---------------------------------------------------------------------------


async def test_revoke_blind_pass_success(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"revoked": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await client.revoke_blind_pass("bp_token_to_revoke")

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://zuultimate:8000/v1/vault/blind-pass/revoke"
    assert call_args[1]["json"]["token"] == "bp_token_to_revoke"
