"""SQLAlchemy models for anomaly detection."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from vinzy_engine.common.models import Base, TimestampMixin, generate_uuid


class AnomalyModel(Base, TimestampMixin):
    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    license_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licenses.id"), nullable=False, index=True
    )
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(255), nullable=False)
    z_score: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_mean: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_stddev: Mapped[float] = mapped_column(Float, nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
