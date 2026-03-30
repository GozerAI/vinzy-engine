"""Pydantic schemas for tenant endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    hmac_key_version: int = 0
    config_overrides: dict[str, Any] = {}


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    hmac_key_version: int
    config_overrides: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantCreateResponse(TenantResponse):
    """Includes the raw API key — only returned once at creation time."""
    api_key: str


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    hmac_key_version: Optional[int] = None
    config_overrides: Optional[dict[str, Any]] = None
