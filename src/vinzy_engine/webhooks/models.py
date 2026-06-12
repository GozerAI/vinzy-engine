"""SQLAlchemy models for webhook endpoints and delivery logs."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from vinzy_engine.common.models import Base, TimestampMixin, generate_uuid


class WebhookEndpointModel(Base, TimestampMixin):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    event_types: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)


class WebhookDeliveryModel(Base, TimestampMixin):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    endpoint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
