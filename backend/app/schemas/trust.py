"""MeshBoard — 신뢰 관리(Trust Workbench) 스키마.

정책(Policy)·인증(Certification) 관리와 에이전트 신뢰 현황 응답 모델.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

POLICY_STATUSES = {"DRAFT", "ACTIVE", "REVOKED"}
CERT_STATES = {"PENDING", "PASSED", "FAILED", "REVOKED"}


# ── Policy ────────────────────────────────────────────────────────
class PolicyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    purpose: Optional[str] = None
    description: Optional[str] = None
    template: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="DRAFT", max_length=20)


class PolicyStatusUpdate(BaseModel):
    status: str = Field(..., max_length=20)


class PolicyTemplateValidate(BaseModel):
    template: Dict[str, Any] = Field(default_factory=dict)


class PolicyTemplateValidationResult(BaseModel):
    valid: bool
    errors: List[str] = Field(default_factory=list)
    supported_fields: List[str] = Field(default_factory=list)


class PolicyRead(BaseModel):
    policy_id: uuid.UUID
    name: str
    purpose: Optional[str] = None
    description: Optional[str] = None
    template: Dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime
    applied_count: int = 0

    model_config = {"from_attributes": True}


# ── Certification ─────────────────────────────────────────────────
class CertificationCreate(BaseModel):
    name: str = Field(..., max_length=255)
    notes: Optional[str] = None
    state: str = Field(default="PENDING", max_length=20)
    expires_at: Optional[datetime] = None


class CertificationStateUpdate(BaseModel):
    state: str = Field(..., max_length=20)
    notes: Optional[str] = None


class CertificationRead(BaseModel):
    certification_id: uuid.UUID
    name: str
    certifier_id: Optional[uuid.UUID] = None
    state: str
    notes: Optional[str] = None
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    linked_count: int = 0

    model_config = {"from_attributes": True}


# ── Agent Trust Posture ───────────────────────────────────────────
class TrustBadge(BaseModel):
    id: uuid.UUID
    name: str
    state: str  # cert state 또는 policy status


class AgentTrustRead(BaseModel):
    agent_id: uuid.UUID
    name: str
    version: str
    status: str
    visibility: str
    owner_name: Optional[str] = None
    certifications: List[TrustBadge] = Field(default_factory=list)
    policies: List[TrustBadge] = Field(default_factory=list)
    trust_level: str  # "certified" | "partial" | "unverified"


# ── Linking ───────────────────────────────────────────────────────
class AgentPolicyLink(BaseModel):
    policy_id: uuid.UUID


class AgentCertLink(BaseModel):
    certification_id: uuid.UUID


# ── Overview ──────────────────────────────────────────────────────
class TrustOverview(BaseModel):
    total_agents: int
    certified_agents: int
    partial_agents: int
    unverified_agents: int
    pending_certifications: int
    active_policies: int
    draft_policies: int
    uncertified_exposed_agents: int  # PUBLIC/DEPARTMENT 인데 인증 없는 에이전트
