"""
LicenseClient SDK — sync client for Vinzy-Engine.

Used by external services and API consumers to validate licenses,
activate machines, and record usage.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx


@dataclass
class ClientLicense:
    """License info returned by the SDK."""

    id: str
    key: str
    status: str
    product_code: str
    customer_id: str
    tier: str
    machines_limit: Optional[int] = None
    machines_used: int = 0
    expires_at: Optional[datetime] = None
    features: list[str] = field(default_factory=list)
    entitlements: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientEntitlement:
    """Entitlement info returned by the SDK."""

    feature: str
    enabled: bool
    limit: Optional[int] = None
    used: int = 0
    remaining: Optional[int] = None


@dataclass
class ClientValidationResult:
    """Result of validate() call."""

    valid: bool
    code: str = ""
    message: str = ""
    license: Optional[ClientLicense] = None
    features: list[str] = field(default_factory=list)
    entitlements: list[ClientEntitlement] = field(default_factory=list)
    lease: Optional[dict[str, Any]] = None


@dataclass
class ClientActivationResult:
    """Result of activate() call."""

    success: bool
    machine_id: Optional[str] = None
    code: str = ""
    message: str = ""
    license: Optional[ClientLicense] = None


@dataclass
class ClientUsageResult:
    """Result of record_usage() call."""

    success: bool
    metric: str = ""
    value_added: float = 0.0
    total_value: float = 0.0
    limit: Optional[float] = None
    remaining: Optional[float] = None
    code: str = ""


class LicenseClient:
    """
    Synchronous HTTP client for Vinzy-Engine.

    Can be wrapped in async by consumers; designed for simplicity in sync contexts.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8080",
        license_key: Optional[str] = None,
        api_key: Optional[str] = None,
        cache_ttl: int = 300,
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff_base: float = 0.5,
        lease_cache_path: Optional[str] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.license_key = license_key
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.lease_cache_path = lease_cache_path
        self._cached_lease: Optional[dict[str, Any]] = None
        self._lease_cached_at: Optional[float] = None
        self._http = httpx.Client(
            base_url=self.server_url,
            timeout=timeout,
        )

        # Load persisted lease if available
        if self.lease_cache_path:
            self._load_persisted_lease()

    def _admin_headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["X-Vinzy-Api-Key"] = self.api_key
        return headers

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Central HTTP method with retry and structured error handling.

        Retries on:
        - httpx.TimeoutException
        - 5xx status codes
        - 429 (rate limit)

        No retry on other 4xx errors.

        Returns parsed JSON on success, or structured error dict on failure.
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = getattr(self._http, method)(path, **kwargs)
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_backoff_base * (2 ** attempt))
                        continue
                    return {
                        "error": f"Server error: {resp.status_code}",
                        "code": "SERVER_ERROR",
                    }
                if resp.status_code >= 400:
                    return {
                        "error": f"Client error: {resp.status_code}",
                        "code": "CLIENT_ERROR",
                    }
                return resp.json()
            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_backoff_base * (2 ** attempt))
                    continue
            except httpx.HTTPError as e:
                last_error = str(e)
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_backoff_base * (2 ** attempt))
                    continue
            except json.JSONDecodeError:
                return {"error": "Invalid JSON response", "code": "JSON_ERROR"}

        return {"error": f"All {self.max_retries} retries exhausted: {last_error}", "code": "CONNECTION_ERROR"}

    def _persist_lease(self, lease: dict[str, Any]) -> None:
        """Save lease to disk for offline fallback."""
        if not self.lease_cache_path:
            return
        try:
            Path(self.lease_cache_path).write_text(
                json.dumps(lease), encoding="utf-8"
            )
        except OSError:
            pass

    def _load_persisted_lease(self) -> None:
        """Load lease from disk."""
        if not self.lease_cache_path:
            return
        try:
            data = Path(self.lease_cache_path).read_text(encoding="utf-8")
            self._cached_lease = json.loads(data)
            self._lease_cached_at = time.time()
        except (OSError, json.JSONDecodeError):
            pass

    def _is_lease_fresh(self) -> bool:
        """Check if cached lease is within the cache_ttl freshness window."""
        if self._lease_cached_at is None:
            return False
        return (time.time() - self._lease_cached_at) < self.cache_ttl

    @staticmethod
    def _parse_license(data: dict) -> ClientLicense:
        expires_at = None
        if data.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(data["expires_at"])
            except (ValueError, TypeError):
                pass

        return ClientLicense(
            id=data.get("id", ""),
            key=data.get("key", ""),
            status=data.get("status", ""),
            product_code=data.get("product_code", ""),
            customer_id=data.get("customer_id", ""),
            tier=data.get("tier", ""),
            machines_limit=data.get("machines_limit"),
            machines_used=data.get("machines_used", 0),
            expires_at=expires_at,
            features=data.get("features", []),
            entitlements=data.get("entitlements", {}),
            metadata=data.get("metadata", {}),
        )

    # ── Validation ──

    def validate(self, fingerprint: str = "") -> ClientValidationResult:
        """Validate the configured license key against the server.

        On successful validation, caches the lease for offline fallback.
        On connection failure, falls back to cached lease if available.
        """
        body: dict[str, Any] = {"key": self.license_key or ""}
        if fingerprint:
            body["fingerprint"] = fingerprint

        data = self._request("post", "/validate", json=body)

        # Connection error — try offline fallback
        if "error" in data and data.get("code") == "CONNECTION_ERROR":
            return self._validate_from_cache()

        license_obj = None
        if data.get("license"):
            license_obj = self._parse_license(data["license"])

        entitlements = []
        for ent in data.get("entitlements", []):
            entitlements.append(ClientEntitlement(
                feature=ent.get("feature", ""),
                enabled=ent.get("enabled", False),
                limit=ent.get("limit"),
                used=ent.get("used", 0),
                remaining=ent.get("remaining"),
            ))

        # Cache lease from response
        lease = data.get("lease")
        if lease and data.get("valid"):
            self._cached_lease = lease
            self._lease_cached_at = time.time()
            self._persist_lease(lease)

        return ClientValidationResult(
            valid=data.get("valid", False),
            code=data.get("code", ""),
            message=data.get("message", ""),
            license=license_obj,
            features=data.get("features", []),
            entitlements=entitlements,
            lease=lease,
        )

    def _validate_from_cache(self) -> ClientValidationResult:
        """Attempt offline validation using cached lease."""
        if self._cached_lease is None:
            return ClientValidationResult(
                valid=False,
                code="NO_LEASE",
                message="No cached lease available for offline validation",
            )

        # Check lease expiry
        try:
            lease_expires_str = self._cached_lease.get("lease_expires_at", "")
            lease_expires = datetime.fromisoformat(lease_expires_str)
            if lease_expires.tzinfo is None:
                lease_expires = lease_expires.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= lease_expires:
                return ClientValidationResult(
                    valid=False,
                    code="LEASE_EXPIRED",
                    message="Cached lease has expired",
                )
        except (ValueError, TypeError):
            return ClientValidationResult(
                valid=False,
                code="LEASE_INVALID",
                message="Cached lease has invalid expiry",
            )

        payload = self._cached_lease.get("payload", {})
        return ClientValidationResult(
            valid=True,
            code="OFFLINE_VALID",
            message="Validated from cached lease (server unreachable)",
            features=payload.get("features", []),
            lease=self._cached_lease,
        )

    def validate_offline(self) -> ClientValidationResult:
        """Explicitly validate using only the cached lease (no server contact)."""
        return self._validate_from_cache()

    # ── Activation ──

    def activate(
        self,
        fingerprint: str,
        hostname: str = "",
        platform: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ClientActivationResult:
        """Activate the license on a machine."""
        body = {
            "key": self.license_key or "",
            "fingerprint": fingerprint,
            "hostname": hostname,
            "platform": platform,
            "metadata": metadata or {},
        }
        data = self._request("post", "/activate", json=body)

        if "error" in data:
            return ClientActivationResult(
                success=False, code=data.get("code", "ERROR"),
                message=data.get("error", ""),
            )

        license_obj = None
        if data.get("license"):
            license_obj = self._parse_license(data["license"])

        return ClientActivationResult(
            success=data.get("success", False),
            machine_id=data.get("machine_id"),
            code=data.get("code", ""),
            message=data.get("message", ""),
            license=license_obj,
        )

    def deactivate(self, fingerprint: str) -> bool:
        """Deactivate the license from a machine."""
        body = {
            "key": self.license_key or "",
            "fingerprint": fingerprint,
        }
        data = self._request("post", "/deactivate", json=body)
        if "error" in data:
            return False
        return data.get("success", False)

    # ── Heartbeat ──

    def heartbeat(self, fingerprint: str, version: str = "") -> bool:
        """Send heartbeat for an activated machine."""
        body = {
            "key": self.license_key or "",
            "fingerprint": fingerprint,
            "version": version,
        }
        data = self._request("post", "/heartbeat", json=body)
        if "error" in data:
            return False
        return data.get("success", False)

    # ── Usage ──

    def record_usage(
        self,
        metric: str,
        value: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> ClientUsageResult:
        """Record metered usage."""
        body = {
            "key": self.license_key or "",
            "metric": metric,
            "value": value,
            "metadata": metadata or {},
        }
        data = self._request("post", "/usage/record", json=body)

        if "error" in data:
            return ClientUsageResult(
                success=False, metric=metric,
                code=data.get("code", "ERROR"),
            )

        return ClientUsageResult(
            success=data.get("success", False),
            metric=data.get("metric", metric),
            value_added=data.get("value_added", 0.0),
            total_value=data.get("total_value", 0.0),
            limit=data.get("limit"),
            remaining=data.get("remaining"),
            code=data.get("code", ""),
        )

    # ── Agent Entitlements ──

    def validate_agent(self, agent_code: str) -> ClientValidationResult:
        """Validate configured license key for a specific agent."""
        body: dict[str, Any] = {"key": self.license_key or "", "agent_code": agent_code}
        data = self._request("post", "/validate/agent", json=body)
        if "error" in data:
            return ClientValidationResult(
                valid=False, code=data.get("code", "ERROR"),
                message=data.get("error", ""),
            )
        return ClientValidationResult(
            valid=data.get("valid", False),
            code=data.get("code", ""),
            message=data.get("message", ""),
        )

    def get_entitled_agents(self) -> list[str]:
        """Extract entitled agent codes from a validation response."""
        body: dict[str, Any] = {"key": self.license_key or ""}
        data = self._request("post", "/validate", json=body)
        if "error" in data or not data.get("valid", False):
            return []
        agents = data.get("agents", [])
        return [a["agent_code"] for a in agents if a.get("enabled", True)]

    # ── Composition ──

    def get_composed_entitlements(self, customer_id: str) -> dict[str, Any]:
        """Get composed entitlements across all products for a customer."""
        data = self._request(
            "get", f"/entitlements/composed/{customer_id}",
            headers=self._admin_headers(),
        )
        return data

    # ── Webhooks ──

    @staticmethod
    def verify_webhook_signature(
        payload_body: str | bytes,
        signature: str,
        secret: str,
    ) -> bool:
        """Verify an incoming webhook's HMAC-SHA256 signature.

        Args:
            payload_body: The raw request body (string or bytes).
            signature: The value of the X-Vinzy-Signature header.
            secret: The webhook endpoint's shared secret.

        Returns:
            True if the signature is valid, False otherwise.
        """
        if isinstance(payload_body, bytes):
            payload_body = payload_body.decode("utf-8")
        expected = hmac.new(
            secret.encode("utf-8"),
            payload_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ── Lifecycle ──

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()
