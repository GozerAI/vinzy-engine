"""Dependency injection singletons for Vinzy-Engine."""

import logging

from vinzy_engine.common.config import VinzySettings, get_settings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.activation.service import ActivationService
from vinzy_engine.usage.service import UsageService

_log = logging.getLogger("vinzy_engine.deps")

_db: DatabaseManager | None = None
_licensing: LicensingService | None = None
_activation: ActivationService | None = None
_usage: UsageService | None = None

# Optional service singletons (may be None if module is stubbed)
_tenants = None
_audit = None
_anomaly = None
_webhook = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager(get_settings())
    return _db


def get_webhook_service():
    global _webhook
    if _webhook is None:
        try:
            from vinzy_engine.webhooks.service import WebhookService
            _webhook = WebhookService(get_settings())
        except ImportError:
            _log.info("WebhookService not available (requires commercial license)")
            _webhook = None
    return _webhook


def get_audit_service():
    global _audit
    if _audit is None:
        try:
            from vinzy_engine.audit.service import AuditService
            _audit = AuditService(get_settings())
        except ImportError:
            _log.info("AuditService not available (requires commercial license)")
            _audit = None
    return _audit


def get_anomaly_service():
    global _anomaly
    if _anomaly is None:
        try:
            from vinzy_engine.anomaly.service import AnomalyService
            _anomaly = AnomalyService(
                get_settings(),
                audit_service=get_audit_service(),
                webhook_service=get_webhook_service(),
            )
        except ImportError:
            _log.info("AnomalyService not available (requires commercial license)")
            _anomaly = None
    return _anomaly


def get_licensing_service() -> LicensingService:
    global _licensing
    if _licensing is None:
        _licensing = LicensingService(
            get_settings(),
            audit_service=get_audit_service(),
            webhook_service=get_webhook_service(),
        )
    return _licensing


def get_activation_service() -> ActivationService:
    global _activation
    if _activation is None:
        _activation = ActivationService(
            get_settings(), get_licensing_service(),
            audit_service=get_audit_service(),
            webhook_service=get_webhook_service(),
        )
    return _activation


def get_usage_service() -> UsageService:
    global _usage
    if _usage is None:
        _usage = UsageService(
            get_settings(), get_licensing_service(),
            audit_service=get_audit_service(),
            anomaly_service=get_anomaly_service(),
            webhook_service=get_webhook_service(),
        )
    return _usage


def get_tenant_service():
    global _tenants
    if _tenants is None:
        try:
            from vinzy_engine.tenants.service import TenantService
            _tenants = TenantService()
        except ImportError:
            _log.info("TenantService not available (requires commercial license)")
            _tenants = None
    return _tenants


def reset_singletons() -> None:
    """Reset all singletons (for testing)."""
    global _db, _licensing, _activation, _usage, _tenants, _audit, _anomaly, _webhook
    _db = None
    _licensing = None
    _activation = None
    _usage = None
    _tenants = None
    _audit = None
    _anomaly = None
    _webhook = None
