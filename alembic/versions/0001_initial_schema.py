"""Full initial schema for Vinzy-Engine including zuultimate_tenant_id

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    """Check if a table already exists (handles create_all before migrate)."""
    from sqlalchemy import inspect as sa_inspect
    conn = op.get_bind()
    return name in sa_inspect(conn).get_table_names()


def upgrade() -> None:
    # ── tenants ──────────────────────────────────────────────────────────────
    if not _table_exists("tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False),
            sa.Column("api_key_hash", sa.String(64), nullable=False),
            sa.Column("hmac_key_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("config_overrides", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("zuultimate_tenant_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
            sa.UniqueConstraint("api_key_hash"),
        )
        op.create_index("ix_tenants_slug", "tenants", ["slug"])
        op.create_index("ix_tenants_api_key_hash", "tenants", ["api_key_hash"])
        op.create_index("ix_tenants_zuultimate_tenant_id", "tenants", ["zuultimate_tenant_id"])

    # ── products ─────────────────────────────────────────────────────────────
    if not _table_exists("products"):
        op.create_table(
            "products",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("code", sa.String(3), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("default_tier", sa.String(50), nullable=False, server_default="standard"),
            sa.Column("features", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "code", name="uq_product_tenant_code"),
        )
        op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
        op.create_index("ix_products_code", "products", ["code"])

    # ── customers ─────────────────────────────────────────────────────────────
    if not _table_exists("customers"):
        op.create_table(
            "customers",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("company", sa.String(255), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "email", name="uq_customer_tenant_email"),
        )
        op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
        op.create_index("ix_customers_email", "customers", ["email"])

    # ── licenses ──────────────────────────────────────────────────────────────
    if not _table_exists("licenses"):
        op.create_table(
            "licenses",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("tier", sa.String(50), nullable=False, server_default="standard"),
            sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id"), nullable=False),
            sa.Column("machines_limit", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("machines_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("features", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("entitlements", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key_hash"),
        )
        op.create_index("ix_licenses_tenant_id", "licenses", ["tenant_id"])
        op.create_index("ix_licenses_key_hash", "licenses", ["key_hash"])
        op.create_index("ix_licenses_status", "licenses", ["status"])

    # ── entitlements ──────────────────────────────────────────────────────────
    if not _table_exists("entitlements"):
        op.create_table(
            "entitlements",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
            sa.Column("feature", sa.String(255), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("limit", sa.Integer(), nullable=True),
            sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_entitlements_license_id", "entitlements", ["license_id"])

    # ── machines ──────────────────────────────────────────────────────────────
    if not _table_exists("machines"):
        op.create_table(
            "machines",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("hostname", sa.String(255), nullable=False, server_default=""),
            sa.Column("platform", sa.String(50), nullable=False, server_default=""),
            sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.String(50), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("license_id", "fingerprint", name="uq_machine_license_fingerprint"),
        )
        op.create_index("ix_machines_license_id", "machines", ["license_id"])
        op.create_index("ix_machines_fingerprint", "machines", ["fingerprint"])

    # ── usage_records ─────────────────────────────────────────────────────────
    if not _table_exists("usage_records"):
        op.create_table(
            "usage_records",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
            sa.Column("metric", sa.String(255), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_usage_records_license_id", "usage_records", ["license_id"])
        op.create_index("ix_usage_records_metric", "usage_records", ["metric"])

    # ── audit_events ──────────────────────────────────────────────────────────
    if not _table_exists("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("actor", sa.String(255), nullable=False, server_default="system"),
            sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("prev_hash", sa.String(64), nullable=True),
            sa.Column("event_hash", sa.String(64), nullable=False),
            sa.Column("signature", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_events_license_id", "audit_events", ["license_id"])
        op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    # ── anomalies ─────────────────────────────────────────────────────────────
    if not _table_exists("anomalies"):
        op.create_table(
            "anomalies",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("license_id", sa.String(36), sa.ForeignKey("licenses.id"), nullable=False),
            sa.Column("anomaly_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("metric", sa.String(255), nullable=False),
            sa.Column("z_score", sa.Float(), nullable=False),
            sa.Column("baseline_mean", sa.Float(), nullable=False),
            sa.Column("baseline_stddev", sa.Float(), nullable=False),
            sa.Column("observed_value", sa.Float(), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("resolved", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("resolved_by", sa.String(255), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_anomalies_license_id", "anomalies", ["license_id"])
        op.create_index("ix_anomalies_anomaly_type", "anomalies", ["anomaly_type"])
        op.create_index("ix_anomalies_severity", "anomalies", ["severity"])
        op.create_index("ix_anomalies_resolved", "anomalies", ["resolved"])

    # ── webhook_endpoints ─────────────────────────────────────────────────────
    if not _table_exists("webhook_endpoints"):
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
            sa.Column("url", sa.String(2048), nullable=False),
            sa.Column("secret", sa.String(255), nullable=False),
            sa.Column("description", sa.String(255), nullable=False, server_default=""),
            sa.Column("event_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])
        op.create_index("ix_webhook_endpoints_status", "webhook_endpoints", ["status"])

    # ── webhook_deliveries ────────────────────────────────────────────────────
    if not _table_exists("webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("endpoint_id", sa.String(36), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_response_code", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.String(1024), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
        op.create_index("ix_webhook_deliveries_event_type", "webhook_deliveries", ["event_type"])
        op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("anomalies")
    op.drop_table("audit_events")
    op.drop_table("usage_records")
    op.drop_table("machines")
    op.drop_table("entitlements")
    op.drop_table("licenses")
    op.drop_table("customers")
    op.drop_table("products")
    op.drop_table("tenants")
