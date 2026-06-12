"""Pydantic schemas for webhook API endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WebhookEndpointCreate(BaseModel):
    url: str
    secret: str = Field(..., min_length=16)
    event_types: list[str] = []
    description: str = ""
    max_retries: int = Field(3, ge=0, le=10)
    timeout_seconds: int = Field(10, ge=1, le=60)


class WebhookEndpointUpdate(BaseModel):
    url: Optional[str] = None
    secret: Optional[str] = Field(None, min_length=16)
    event_types: Optional[list[str]] = None
    description: Optional[str] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=60)
    status: Optional[str] = Field(None, pattern=r"^(active|paused|disabled)$")


class WebhookEndpointResponse(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    url: str
    description: str
    event_types: list[str] = []
    status: str
    max_retries: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: str
    endpoint_id: str
    event_type: str
    payload: dict[str, Any] = {}
    status: str
    attempts: int
    last_response_code: Optional[int] = None
    last_error: Optional[str] = None
    next_retry_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WebhookTestRequest(BaseModel):
    pass
