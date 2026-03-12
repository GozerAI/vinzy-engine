"""SQLAlchemy models for licensing."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vinzy_engine.common.models import Base, SoftDeleteMixin, TimestampMixin, generate_uuid


class ProductModel(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_product_tenant_code"),
        # Partial index: enforce unique code when tenant_id IS NULL (single-tenant mode)
        Index(
            "uq_product_code_global",
            "code",
            unique=True,
            sqlite_where=text("tenant_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    default_tier: Mapped[str] = mapped_column(String(50), default="standard")
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    licenses: Mapped[list["LicenseModel"]] = relationship(back_populates="product")


class CustomerModel(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_customer_tenant_email"),
        # Partial index: enforce unique email when tenant_id IS NULL (single-tenant mode)
        Index(
            "uq_customer_email_global",
            "email",
            unique=True,
            sqlite_where=text("tenant_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    licenses: Mapped[list["LicenseModel"]] = relationship(back_populates="customer")


class LicenseModel(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=True, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    tier: Mapped[str] = mapped_column(String(50), default="standard")

    product_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("products.id"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=False
    )

    machines_limit: Mapped[int] = mapped_column(Integer, default=3)
    machines_used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    features: Mapped[dict] = mapped_column(JSON, default=dict)
    entitlements: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    product: Mapped["ProductModel"] = relationship(back_populates="licenses")
    customer: Mapped["CustomerModel"] = relationship(back_populates="licenses")


class EntitlementModel(Base, TimestampMixin):
    __tablename__ = "entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    license_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licenses.id"), nullable=False, index=True
    )
    feature: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used: Mapped[int] = mapped_column(Integer, default=0)
