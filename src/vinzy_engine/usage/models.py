"""SQLAlchemy models for usage tracking."""

from sqlalchemy import Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from vinzy_engine.common.models import Base, TimestampMixin, generate_uuid


class UsageRecordModel(Base, TimestampMixin):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    license_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licenses.id"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
