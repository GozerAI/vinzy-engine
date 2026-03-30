"""Dependency injection singletons for Vinzy-Engine."""

from vinzy_engine.common.config import VinzySettings, get_settings
from vinzy_engine.common.database import DatabaseManager
from vinzy_engine.licensing.service import LicensingService
from vinzy_engine.activation.service import ActivationService
from vinzy_engine.usage.service import UsageService
from vinzy_engine.tenants.service import TenantService
from vinzy_engine.audit.service import AuditService
from vinzy_engine.anomaly.service import AnomalyService
from vinzy_engine.webhooks.service import WebhookService

_db: DatabaseManager | None = None
_licensing: LicensingService | None = None
_activation: ActivationService | None = None
_usage: UsageService | None = None
_tenants: TenantService | None = None
_audit: AuditService | None = None
_anomaly: AnomalyService | None = None
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


def get_tenant_service() -> TenantService:
    global _tenants
    if _tenants is None:
        _tenants = TenantService()
    return _tenants


def get_audit_service() -> AuditService:
    global _audit
    if _audit is None:
        _audit = AuditService(get_settings())
    return _audit


def get_anomaly_service() -> AnomalyService:
    global _anomaly
    if _anomaly is None:
        _anomaly = AnomalyService(
            get_settings(),
            audit_service=get_audit_service(),
            webhook_service=get_webhook_service(),
        )
    return _anomaly


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

    # Reset caches and background processors
    from vinzy_engine.common.caching import reset_all_caches, reset_invalidation_bus
    reset_all_caches()
    reset_invalidation_bus()

    from vinzy_engine.common.health import reset_health_monitor
    reset_health_monitor()

    from vinzy_engine.common.serialization import reset_serialization_benchmark
    reset_serialization_benchmark()

    from vinzy_engine.audit.batch import reset_batch_audit_writer
    reset_batch_audit_writer()

    from vinzy_engine.background import reset_background_processors
    reset_background_processors()
