"""SQLAlchemy model for tenants."""

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vinzy_engine.common.models import Base, TimestampMixin, generate_uuid


class TenantModel(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    api_key_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    hmac_key_version: Mapped[int] = mapped_column(Integer, default=0)
    config_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    zuultimate_tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
