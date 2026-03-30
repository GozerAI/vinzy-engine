"""Pydantic schemas for usage endpoints."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class UsageRecordRequest(BaseModel):
    key: str
    metric: str = Field(..., min_length=1, max_length=255)
    value: float = Field(default=1.0, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageRecordResponse(BaseModel):
    success: bool
    metric: str
    value_added: float
    total_value: float
    limit: Optional[float] = None
    remaining: Optional[float] = None
    code: str = ""


class UsageSummary(BaseModel):
    metric: str
    total_value: float
    record_count: int
    limit: Optional[float] = None
    remaining: Optional[float] = None
