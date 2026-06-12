"""Rate limiting middleware for Vinzy-Engine using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from vinzy_engine.common.config import get_settings


def _default_limit() -> str:
    """Return the default rate limit string from settings."""
    settings = get_settings()
    return f"{settings.rate_limit_per_minute}/minute"


def _public_limit() -> str:
    """Stricter limit for unauthenticated public endpoints."""
    settings = get_settings()
    return f"{settings.rate_limit_public_per_minute}/minute"


def _admin_limit() -> str:
    """Limit for authenticated admin endpoints."""
    settings = get_settings()
    return f"{settings.rate_limit_admin_per_minute}/minute"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_default_limit],
)
