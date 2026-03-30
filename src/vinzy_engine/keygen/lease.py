"""Signed leases for offline license validation.

A lease is a time-limited, HMAC-signed snapshot of a license's state.
Clients receive it from /validate and can verify it offline without
contacting the server, providing graceful degradation during outages.
"""

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class LeasePayload:
    """The data signed into a lease."""

    license_id: str
    status: str
    features: list[str]
    entitlements: list[dict[str, Any]]
    tier: str
    product_code: str
    issued_at: str  # ISO format
    expires_at: str  # ISO format


def create_lease(
    payload: LeasePayload,
    hmac_key: str,
    ttl_seconds: int = 86400,
) -> dict[str, Any]:
    """Create a signed lease from a payload.

    Args:
        payload: The lease data to sign
        hmac_key: HMAC signing key
        ttl_seconds: Lease validity duration in seconds

    Returns:
        Dict with 'payload', 'signature', 'lease_expires_at' fields
    """
    now = datetime.now(timezone.utc)
    lease_expires = datetime(
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        tzinfo=timezone.utc,
    )
    from datetime import timedelta
    lease_expires = lease_expires + timedelta(seconds=ttl_seconds)

    payload_dict = asdict(payload)
    # Canonical JSON for deterministic signing
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))

    # Include expiry in the signed message
    message = f"{canonical}|{lease_expires.isoformat()}".encode()
    signature = hmac.new(
        hmac_key.encode(), message, hashlib.sha256
    ).hexdigest()

    return {
        "payload": payload_dict,
        "signature": signature,
        "lease_expires_at": lease_expires.isoformat(),
    }


def verify_lease(lease: dict[str, Any], hmac_key: str) -> bool:
    """Verify a lease's signature and check expiry.

    Args:
        lease: Dict with 'payload', 'signature', 'lease_expires_at'
        hmac_key: HMAC signing key

    Returns:
        True if signature is valid and lease has not expired
    """
    try:
        payload_dict = lease["payload"]
        signature = lease["signature"]
        lease_expires_str = lease["lease_expires_at"]
    except (KeyError, TypeError):
        return False

    # Reconstruct canonical message
    canonical = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
    message = f"{canonical}|{lease_expires_str}".encode()
    expected_sig = hmac.new(
        hmac_key.encode(), message, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False

    # Check expiry
    try:
        lease_expires = datetime.fromisoformat(lease_expires_str)
        if lease_expires.tzinfo is None:
            lease_expires = lease_expires.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False

    now = datetime.now(timezone.utc)
    return now < lease_expires
