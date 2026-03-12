"""Pydantic schemas for activation endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActivateRequest(BaseModel):
    key: str
    fingerprint: str
    hostname: str = ""
    platform: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeactivateRequest(BaseModel):
    key: str
    fingerprint: str


class DeactivateResponse(BaseModel):
    success: bool


class HeartbeatRequest(BaseModel):
    key: str
    fingerprint: str
    version: str = ""


class ActivateResponse(BaseModel):
    success: bool
    machine_id: Optional[str] = None
    code: str
    message: str
    license: Optional[dict[str, Any]] = None


class HeartbeatResponse(BaseModel):
    success: bool
    code: str = "OK"
    message: str = ""
