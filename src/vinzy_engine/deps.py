"""Dependency injection singletons for Vinzy-Engine."""

from vinzy_engine.common.config import VinzySettings, get_settings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.activation.service import ActivationService
from vinzy_engine.usage.service import UsageService
from vinzy_engine.webhooks.service import WebhookService

_db: DatabaseManager | None = None
_licensing: LicensingService | None = None
_activation: ActivationService | None = None
_usage: UsageService | None = None
_webhook: WebhookService | None = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager(get_settings())
    return _db


def get_webhook_service() -> WebhookService:
    global _webhook
    if _webhook is None:
        _webhook = WebhookService(get_settings())
    return _webhook


def get_licensing_service() -> LicensingService:
    global _licensing
    if _licensing is None:
        _licensing = LicensingService(
            get_settings(),
            webhook_service=get_webhook_service(),
        )
    return _licensing


def get_activation_service() -> ActivationService:
    global _activation
    if _activation is None:
        _activation = ActivationService(
            get_settings(), get_licensing_service(),
            webhook_service=get_webhook_service(),
        )
    return _activation


def get_usage_service() -> UsageService:
    global _usage
    if _usage is None:
        _usage = UsageService(
            get_settings(), get_licensing_service(),
            webhook_service=get_webhook_service(),
        )
    return _usage


def reset_singletons() -> None:
    """Reset all singletons (for testing)."""
    global _db, _licensing, _activation, _usage, _webhook
    _db = None
    _licensing = None
    _activation = None
    _usage = None
    _webhook = None
