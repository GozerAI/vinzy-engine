"""Pydantic schemas for audit chain API responses."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: str
    license_id: str
    event_type: str
    actor: str
    detail: dict[str, Any] = {}
    prev_hash: Optional[str] = None
    event_hash: str
    signature: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditChainVerification(BaseModel):
    valid: bool
    events_checked: int
    break_at: Optional[str] = None
