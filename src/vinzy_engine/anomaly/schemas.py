"""Pydantic schemas for anomaly detection API responses."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AnomalyResponse(BaseModel):
    id: str
    license_id: str
    anomaly_type: str
    severity: str
    metric: str
    z_score: float
    baseline_mean: float
    baseline_stddev: float
    observed_value: float
    detail: dict[str, Any] = {}
    resolved: bool
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnomalyResolveRequest(BaseModel):
    resolved_by: str
