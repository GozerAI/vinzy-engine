"""Pydantic schemas for licensing endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# ── Products ──

class ProductCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=3, pattern=r"^[A-Z]{1,3}$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    default_tier: str = "standard"
    features: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    default_tier: str
    features: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Customers ──

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=255)
    company: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerResponse(BaseModel):
    id: str
    name: str
    email: str
    company: str
    metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Licenses ──

class LicenseCreate(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=3)
    customer_id: str
    tier: str = "standard"
    machines_limit: int = Field(default=3, ge=1)
    days_valid: int = Field(default=365, ge=1)
    features: dict[str, Any] = Field(default_factory=dict)
    entitlements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LicenseUpdate(BaseModel):
    status: Optional[str] = None
    tier: Optional[str] = None
    machines_limit: Optional[int] = None
    features: Optional[dict[str, Any]] = None
    entitlements: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class LicenseResponse(BaseModel):
    id: str
    key: str  # only returned at creation time
    status: str
    product_code: str
    customer_id: str
    tier: str
    machines_limit: int
    machines_used: int
    expires_at: Optional[datetime]
    features: dict[str, Any]
    entitlements: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class LicenseSummary(BaseModel):
    id: str
    status: str
    product_code: str
    customer_id: str
    tier: str
    machines_used: int
    machines_limit: int
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Validation ──

class ValidationRequest(BaseModel):
    key: str
    fingerprint: Optional[str] = None


class EntitlementResponse(BaseModel):
    feature: str
    enabled: bool
    limit: Optional[int] = None
    used: int = 0
    remaining: Optional[int] = None


class ValidationLicense(BaseModel):
    """License info as returned by validation (features is a list of names)."""
    id: str
    key: str
    status: str
    product_code: str
    customer_id: str
    tier: str
    machines_limit: Optional[int] = None
    machines_used: int = 0
    expires_at: Optional[datetime] = None
    features: list[str] = Field(default_factory=list)
    entitlements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LeaseResponse(BaseModel):
    """Signed lease for offline validation."""
    payload: dict[str, Any]
    signature: str
    lease_expires_at: str


class AgentEntitlementResponse(BaseModel):
    """Per-agent entitlement info."""
    model_config = {"protected_namespaces": ()}

    agent_code: str
    enabled: bool
    token_limit: Optional[int] = None
    model_tier: str = "standard"


class AgentValidationRequest(BaseModel):
    key: str
    agent_code: str


class AgentValidationResponse(BaseModel):
    """Result of agent-level license validation."""
    model_config = {"protected_namespaces": ()}

    valid: bool
    code: str
    message: str
    agent_code: str
    enabled: bool = False
    token_limit: Optional[int] = None
    model_tier: Optional[str] = None


class DeactivateResponse(BaseModel):
    success: bool


class ComposedSourceResponse(BaseModel):
    product_code: str
    license_id: str
    value: Any


class ComposedFeatureResponse(BaseModel):
    feature: str
    effective_value: Any
    strategy: str
    sources: list[ComposedSourceResponse] = Field(default_factory=list)


class ComposedEntitlementsResponse(BaseModel):
    customer_id: str
    total_products: int
    features: list[ComposedFeatureResponse] = Field(default_factory=list)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    valid: bool
    code: str
    message: str
    license: Optional[ValidationLicense] = None
    features: list[str] = Field(default_factory=list)
    entitlements: list[EntitlementResponse] = Field(default_factory=list)
    agents: list[AgentEntitlementResponse] = Field(default_factory=list)
    lease: Optional[LeaseResponse] = None
