"""Self-sufficiency modules for Vinzy-Engine.

Provides automated operational capabilities:
- Webhook retry with dead letter queue
- License cache warming on startup
- Self-healing license validation with DB fallback
- Automated license cleanup for expired entries
- License usage report generation
"""

from vinzy_engine.self_sufficiency.webhook_retry import (
    DeadLetterEntry,
    DeadLetterQueue,
    WebhookRetryManager,
    get_dead_letter_queue,
    get_webhook_retry_manager,
    reset_webhook_retry,
)
from vinzy_engine.self_sufficiency.cache_warmer import (
    CacheWarmer,
    CacheWarmResult,
    get_cache_warmer,
    reset_cache_warmer,
)
from vinzy_engine.self_sufficiency.self_healing import (
    SelfHealingValidator,
    ValidationFallbackResult,
    get_self_healing_validator,
    reset_self_healing_validator,
)
from vinzy_engine.self_sufficiency.license_cleanup import (
    CleanupPolicy,
    CleanupResult,
    LicenseCleanupService,
    get_license_cleanup_service,
    reset_license_cleanup_service,
)
from vinzy_engine.self_sufficiency.report_generator import (
    ReportFormat,
    ReportType,
    LicenseReportGenerator,
    get_report_generator,
    reset_report_generator,
)

__all__ = [
    # webhook_retry
    "DeadLetterEntry",
    "DeadLetterQueue",
    "WebhookRetryManager",
    "get_dead_letter_queue",
    "get_webhook_retry_manager",
    "reset_webhook_retry",
    # cache_warmer
    "CacheWarmer",
    "CacheWarmResult",
    "get_cache_warmer",
    "reset_cache_warmer",
    # self_healing
    "SelfHealingValidator",
    "ValidationFallbackResult",
    "get_self_healing_validator",
    "reset_self_healing_validator",
    # license_cleanup
    "CleanupPolicy",
    "CleanupResult",
    "LicenseCleanupService",
    "get_license_cleanup_service",
    "reset_license_cleanup_service",
    # report_generator
    "ReportFormat",
    "ReportType",
    "LicenseReportGenerator",
    "get_report_generator",
    "reset_report_generator",
]
