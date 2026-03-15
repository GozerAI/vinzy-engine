"""Refund automation with approval workflow.

Item 446: Automated refund processing with configurable approval thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RefundReason(str, Enum):
    DUPLICATE_CHARGE = "duplicate_charge"
    SERVICE_ISSUE = "service_issue"
    CUSTOMER_REQUEST = "customer_request"
    BILLING_ERROR = "billing_error"
    DOWNGRADE = "downgrade"
    CANCELLATION = "cancellation"
    FRAUD = "fraud"
    OTHER = "other"


class RefundStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalLevel(str, Enum):
    AUTO = "auto"
    MANAGER = "manager"
    FINANCE = "finance"
    EXECUTIVE = "executive"


@dataclass
class RefundPolicy:
    """Configurable refund approval policy."""
    auto_approve_threshold: float = 50.0
    manager_threshold: float = 200.0
    finance_threshold: float = 1000.0
    # Above finance_threshold requires executive approval
    auto_approve_reasons: list[RefundReason] = field(
        default_factory=lambda: [RefundReason.DUPLICATE_CHARGE, RefundReason.BILLING_ERROR]
    )
    max_refund_days: int = 90  # Days since charge
    partial_refund_allowed: bool = True


@dataclass
class RefundRequest:
    """A refund request."""
    refund_id: str
    license_id: str
    original_charge_id: str
    amount: float
    reason: RefundReason
    description: str = ""
    status: RefundStatus = RefundStatus.PENDING_APPROVAL
    approval_level: ApprovalLevel = ApprovalLevel.AUTO
    approved_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RefundEngine:
    """Automated refund processing with approval workflow."""

    def __init__(self, policy: RefundPolicy | None = None):
        self._policy = policy or RefundPolicy()
        self._requests: dict[str, RefundRequest] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"RFD-{self._counter:06d}"

    def _determine_approval_level(self, amount: float, reason: RefundReason) -> ApprovalLevel:
        if reason in self._policy.auto_approve_reasons:
            return ApprovalLevel.AUTO
        if amount <= self._policy.auto_approve_threshold:
            return ApprovalLevel.AUTO
        if amount <= self._policy.manager_threshold:
            return ApprovalLevel.MANAGER
        if amount <= self._policy.finance_threshold:
            return ApprovalLevel.FINANCE
        return ApprovalLevel.EXECUTIVE

    def request_refund(
        self,
        license_id: str,
        original_charge_id: str,
        amount: float,
        reason: RefundReason,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> RefundRequest:
        """Submit a refund request."""
        approval_level = self._determine_approval_level(amount, reason)
        status = RefundStatus.PENDING_APPROVAL

        # Auto-approve if meets criteria
        if approval_level == ApprovalLevel.AUTO:
            status = RefundStatus.APPROVED

        request = RefundRequest(
            refund_id=self._next_id(),
            license_id=license_id,
            original_charge_id=original_charge_id,
            amount=amount,
            reason=reason,
            description=description,
            status=status,
            approval_level=approval_level,
            approved_by="system" if status == RefundStatus.APPROVED else None,
            resolved_at=datetime.now(timezone.utc) if status == RefundStatus.APPROVED else None,
            metadata=metadata or {},
        )
        self._requests[request.refund_id] = request
        return request

    def approve(self, refund_id: str, approved_by: str) -> RefundRequest:
        """Approve a pending refund."""
        request = self._requests.get(refund_id)
        if request is None:
            raise ValueError(f"Refund not found: {refund_id}")
        if request.status != RefundStatus.PENDING_APPROVAL:
            raise ValueError(f"Refund {refund_id} is not pending approval")
        request.status = RefundStatus.APPROVED
        request.approved_by = approved_by
        request.resolved_at = datetime.now(timezone.utc)
        return request

    def reject(self, refund_id: str, rejected_by: str, reason: str = "") -> RefundRequest:
        """Reject a refund request."""
        request = self._requests.get(refund_id)
        if request is None:
            raise ValueError(f"Refund not found: {refund_id}")
        request.status = RefundStatus.REJECTED
        request.approved_by = rejected_by
        request.resolved_at = datetime.now(timezone.utc)
        if reason:
            request.metadata["rejection_reason"] = reason
        return request

    def process(self, refund_id: str) -> RefundRequest:
        """Process an approved refund."""
        request = self._requests.get(refund_id)
        if request is None:
            raise ValueError(f"Refund not found: {refund_id}")
        if request.status != RefundStatus.APPROVED:
            raise ValueError(f"Refund {refund_id} is not approved")
        request.status = RefundStatus.COMPLETED
        return request

    def get_request(self, refund_id: str) -> RefundRequest | None:
        return self._requests.get(refund_id)

    def get_pending(self, approval_level: ApprovalLevel | None = None) -> list[RefundRequest]:
        results = [r for r in self._requests.values() if r.status == RefundStatus.PENDING_APPROVAL]
        if approval_level:
            results = [r for r in results if r.approval_level == approval_level]
        return results

    def get_requests(self, license_id: str | None = None) -> list[RefundRequest]:
        results = list(self._requests.values())
        if license_id:
            results = [r for r in results if r.license_id == license_id]
        return results

    @property
    def policy(self) -> RefundPolicy:
        return self._policy
