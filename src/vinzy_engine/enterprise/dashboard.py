"""Enterprise license management dashboard.

Item 400: Dashboard data aggregation for enterprise license management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class LicenseUsageSummary:
    """Usage summary for a single license."""
    license_id: str
    user_email: str
    status: str
    tier: str
    total_usage: float
    last_active: datetime | None
    features_used: list[str] = field(default_factory=list)


@dataclass
class EnterpriseDashboardData:
    """Aggregated data for enterprise dashboard."""
    tenant_id: str
    total_licenses: int
    active_licenses: int
    suspended_licenses: int
    expired_licenses: int
    total_usage: float
    usage_by_tier: dict[str, float]
    usage_by_product: dict[str, float]
    active_users_30d: int
    license_utilization_pct: float
    top_users: list[LicenseUsageSummary]
    compliance_status: str
    alerts: list[str]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DashboardAlert:
    alert_id: str
    severity: str  # info, warning, critical
    message: str
    category: str  # usage, compliance, billing, security
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False


class EnterpriseDashboardService:
    """Generate enterprise license management dashboard data."""

    def __init__(self):
        self._alerts: list[DashboardAlert] = []
        self._alert_counter = 0

    def _next_alert_id(self) -> str:
        self._alert_counter += 1
        return f"ALERT-{self._alert_counter:06d}"

    def generate_dashboard(
        self,
        tenant_id: str,
        licenses: list[dict[str, Any]],
        usage_data: list[dict[str, Any]] | None = None,
    ) -> EnterpriseDashboardData:
        """Generate dashboard data from license and usage data."""
        usage_data = usage_data or []

        total = len(licenses)
        active = sum(1 for l in licenses if l.get("status") == "active")
        suspended = sum(1 for l in licenses if l.get("status") == "suspended")
        expired = sum(1 for l in licenses if l.get("status") == "expired")

        # Usage aggregation
        total_usage = sum(u.get("value", 0) for u in usage_data)
        usage_by_tier: dict[str, float] = {}
        usage_by_product: dict[str, float] = {}

        for lic in licenses:
            tier = lic.get("tier", "unknown")
            product = lic.get("product_code", "unknown")
            lic_usage = sum(
                u.get("value", 0)
                for u in usage_data
                if u.get("license_id") == lic.get("id")
            )
            usage_by_tier[tier] = usage_by_tier.get(tier, 0) + lic_usage
            usage_by_product[product] = usage_by_product.get(product, 0) + lic_usage

        # Active users (simplified: licenses with any usage)
        active_license_ids = {u.get("license_id") for u in usage_data}
        active_users_30d = len(active_license_ids)

        utilization = round(active / total * 100, 2) if total else 0

        # Top users
        top_users: list[LicenseUsageSummary] = []
        for lic in sorted(licenses, key=lambda l: sum(
            u.get("value", 0) for u in usage_data if u.get("license_id") == l.get("id")
        ), reverse=True)[:10]:
            lic_usage = sum(
                u.get("value", 0)
                for u in usage_data
                if u.get("license_id") == lic.get("id")
            )
            top_users.append(LicenseUsageSummary(
                license_id=lic.get("id", ""),
                user_email=lic.get("email", ""),
                status=lic.get("status", "unknown"),
                tier=lic.get("tier", "unknown"),
                total_usage=lic_usage,
                last_active=None,
            ))

        # Compliance check
        compliance_status = "compliant"
        alerts: list[str] = []
        if expired > 0:
            alerts.append(f"{expired} expired licenses need renewal")
        if utilization < 50:
            alerts.append(f"Low utilization: {utilization}%")
        if suspended > 0:
            alerts.append(f"{suspended} licenses suspended")
            compliance_status = "attention_needed"

        return EnterpriseDashboardData(
            tenant_id=tenant_id,
            total_licenses=total,
            active_licenses=active,
            suspended_licenses=suspended,
            expired_licenses=expired,
            total_usage=total_usage,
            usage_by_tier=usage_by_tier,
            usage_by_product=usage_by_product,
            active_users_30d=active_users_30d,
            license_utilization_pct=utilization,
            top_users=top_users,
            compliance_status=compliance_status,
            alerts=alerts,
        )

    def add_alert(self, severity: str, message: str, category: str) -> DashboardAlert:
        alert = DashboardAlert(
            alert_id=self._next_alert_id(),
            severity=severity,
            message=message,
            category=category,
        )
        self._alerts.append(alert)
        return alert

    def get_alerts(self, category: str | None = None, acknowledged: bool | None = None) -> list[DashboardAlert]:
        results = self._alerts
        if category:
            results = [a for a in results if a.category == category]
        if acknowledged is not None:
            results = [a for a in results if a.acknowledged == acknowledged]
        return results

    def acknowledge_alert(self, alert_id: str) -> None:
        for a in self._alerts:
            if a.alert_id == alert_id:
                a.acknowledged = True
                return
