"""SQLAlchemy models for machine activation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from vinzy_engine.common.models import Base, TimestampMixin, generate_uuid


class MachineModel(Base, TimestampMixin):
    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("license_id", "fingerprint", name="uq_machine_license_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    license_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("licenses.id"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    platform: Mapped[str] = mapped_column(String(50), default="")
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[str] = mapped_column(String(50), default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
