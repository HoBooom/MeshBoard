"""MeshBoard — 신뢰 관리(Trust Workbench) API.

회사 내부에서 에이전트 신뢰를 관리하기 위한 최소 기능을 제공한다.
- 정책(Policy) 발급/상태 변경
- 인증(Certification) 발급/심사 상태 변경
- 에이전트별 신뢰 현황 조회 및 정책·인증 연결
- 신뢰 운영 요약 지표

쓰기 작업은 governance / trust_ops 역할이 필요하다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import RequireRoles
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.certification import AgentCertification, Certification
from app.models.policy import AgentPolicy, Policy
from app.models.user import User
from app.schemas.trust import (
    CERT_STATES,
    POLICY_STATUSES,
    AgentCertLink,
    AgentPolicyLink,
    AgentTrustRead,
    CertificationCreate,
    CertificationRead,
    CertificationStateUpdate,
    PolicyCreate,
    PolicyRead,
    PolicyStatusUpdate,
    TrustBadge,
    TrustOverview,
)

router = APIRouter(prefix="/trust", tags=["trust"])

# 쓰기 권한 의존성
RequireTrustWrite = RequireRoles("admin", "governance", "trust_ops")

_EXPOSED_VISIBILITIES = {"PUBLIC", "DEPARTMENT"}


# ── Helpers ───────────────────────────────────────────────────────
async def _policy_applied_counts(db: AsyncSession) -> Dict[UUID, int]:
    rows = await db.execute(
        select(AgentPolicy.policy_id, func.count()).group_by(AgentPolicy.policy_id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def _cert_linked_counts(db: AsyncSession) -> Dict[UUID, int]:
    rows = await db.execute(
        select(AgentCertification.certification_id, func.count()).group_by(
            AgentCertification.certification_id
        )
    )
    return {row[0]: row[1] for row in rows.all()}


def _trust_level(certs: List[TrustBadge], policies: List[TrustBadge]) -> str:
    if any(c.state == "PASSED" for c in certs):
        return "certified"
    if certs or policies:
        return "partial"
    return "unverified"


# ── Policies ──────────────────────────────────────────────────────
@router.get("/policies", response_model=List[PolicyRead])
async def list_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """전체 정책 목록 (적용 에이전트 수 포함)."""
    result = await db.execute(select(Policy).order_by(Policy.created_at.desc()))
    policies = result.scalars().all()
    counts = await _policy_applied_counts(db)
    out: List[PolicyRead] = []
    for p in policies:
        data = PolicyRead.model_validate(p)
        out.append(data.model_copy(update={"applied_count": counts.get(p.policy_id, 0)}))
    return out


@router.post("/policies", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """정책 신규 발급."""
    if payload.status not in POLICY_STATUSES:
        raise HTTPException(422, f"status 는 {sorted(POLICY_STATUSES)} 중 하나여야 합니다.")
    policy = Policy(
        name=payload.name,
        purpose=payload.purpose,
        description=payload.description,
        template=payload.template,
        status=payload.status,
        created_by=current_user.user_id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return PolicyRead.model_validate(policy)


@router.patch("/policies/{policy_id}/status", response_model=PolicyRead)
async def update_policy_status(
    policy_id: UUID,
    payload: PolicyStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """정책 상태 변경 (DRAFT/ACTIVE/REVOKED)."""
    if payload.status not in POLICY_STATUSES:
        raise HTTPException(422, f"status 는 {sorted(POLICY_STATUSES)} 중 하나여야 합니다.")
    policy = (
        await db.execute(select(Policy).where(Policy.policy_id == policy_id))
    ).scalar_one_or_none()
    if policy is None:
        raise HTTPException(404, "정책을 찾을 수 없습니다.")
    policy.status = payload.status
    policy.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(policy)
    counts = await _policy_applied_counts(db)
    return PolicyRead.model_validate(policy).model_copy(
        update={"applied_count": counts.get(policy.policy_id, 0)}
    )


# ── Certifications ────────────────────────────────────────────────
@router.get("/certifications", response_model=List[CertificationRead])
async def list_certifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """전체 인증 목록 (연결 에이전트 수 포함)."""
    result = await db.execute(
        select(Certification).order_by(Certification.created_at.desc())
    )
    certs = result.scalars().all()
    counts = await _cert_linked_counts(db)
    out: List[CertificationRead] = []
    for c in certs:
        data = CertificationRead.model_validate(c)
        out.append(data.model_copy(update={"linked_count": counts.get(c.certification_id, 0)}))
    return out


@router.post(
    "/certifications", response_model=CertificationRead, status_code=status.HTTP_201_CREATED
)
async def create_certification(
    payload: CertificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """인증 신규 발급."""
    if payload.state not in CERT_STATES:
        raise HTTPException(422, f"state 는 {sorted(CERT_STATES)} 중 하나여야 합니다.")
    cert = Certification(
        name=payload.name,
        certifier_id=current_user.user_id,
        state=payload.state,
        notes=payload.notes,
        expires_at=payload.expires_at,
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    return CertificationRead.model_validate(cert)


@router.patch("/certifications/{cert_id}/state", response_model=CertificationRead)
async def update_certification_state(
    cert_id: UUID,
    payload: CertificationStateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """인증 심사 상태 변경 (PENDING/PASSED/FAILED/REVOKED)."""
    if payload.state not in CERT_STATES:
        raise HTTPException(422, f"state 는 {sorted(CERT_STATES)} 중 하나여야 합니다.")
    cert = (
        await db.execute(select(Certification).where(Certification.certification_id == cert_id))
    ).scalar_one_or_none()
    if cert is None:
        raise HTTPException(404, "인증을 찾을 수 없습니다.")
    cert.state = payload.state
    cert.certifier_id = current_user.user_id
    if payload.notes is not None:
        cert.notes = payload.notes
    if payload.state == "PASSED" and cert.issued_at is None:
        cert.issued_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(cert)
    counts = await _cert_linked_counts(db)
    return CertificationRead.model_validate(cert).model_copy(
        update={"linked_count": counts.get(cert.certification_id, 0)}
    )


# ── Agent Trust Posture ───────────────────────────────────────────
async def _build_agent_trust(db: AsyncSession) -> List[AgentTrustRead]:
    agents = (
        await db.execute(select(Agent).order_by(Agent.name))
    ).scalars().all()

    # owner 이름 매핑
    users = (await db.execute(select(User))).scalars().all()
    user_names = {u.user_id: u.name for u in users}

    # 에이전트별 인증
    cert_rows = await db.execute(
        select(AgentCertification.agent_id, Certification).join(
            Certification,
            Certification.certification_id == AgentCertification.certification_id,
        )
    )
    certs_by_agent: Dict[UUID, List[TrustBadge]] = {}
    for agent_id, cert in cert_rows.all():
        certs_by_agent.setdefault(agent_id, []).append(
            TrustBadge(id=cert.certification_id, name=cert.name, state=cert.state)
        )

    # 에이전트별 정책
    pol_rows = await db.execute(
        select(AgentPolicy.agent_id, Policy).join(
            Policy, Policy.policy_id == AgentPolicy.policy_id
        )
    )
    pols_by_agent: Dict[UUID, List[TrustBadge]] = {}
    for agent_id, pol in pol_rows.all():
        pols_by_agent.setdefault(agent_id, []).append(
            TrustBadge(id=pol.policy_id, name=pol.name, state=pol.status)
        )

    out: List[AgentTrustRead] = []
    for a in agents:
        certs = certs_by_agent.get(a.agent_id, [])
        pols = pols_by_agent.get(a.agent_id, [])
        out.append(
            AgentTrustRead(
                agent_id=a.agent_id,
                name=a.name,
                version=a.version,
                status=a.status,
                visibility=a.visibility,
                owner_name=user_names.get(a.owner_id),
                certifications=certs,
                policies=pols,
                trust_level=_trust_level(certs, pols),
            )
        )
    return out


@router.get("/agents", response_model=List[AgentTrustRead])
async def list_agent_trust(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """전체 에이전트의 신뢰 현황(인증·정책·신뢰등급)."""
    return await _build_agent_trust(db)


async def _ensure_agent(db: AsyncSession, agent_id: UUID) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(404, "에이전트를 찾을 수 없습니다.")
    return agent


@router.post("/agents/{agent_id}/policies", status_code=status.HTTP_204_NO_CONTENT)
async def link_policy(
    agent_id: UUID,
    payload: AgentPolicyLink,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """에이전트에 정책 연결."""
    await _ensure_agent(db, agent_id)
    policy = (
        await db.execute(select(Policy).where(Policy.policy_id == payload.policy_id))
    ).scalar_one_or_none()
    if policy is None:
        raise HTTPException(404, "정책을 찾을 수 없습니다.")
    exists = (
        await db.execute(
            select(AgentPolicy).where(
                AgentPolicy.agent_id == agent_id,
                AgentPolicy.policy_id == payload.policy_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            AgentPolicy(
                agent_id=agent_id,
                policy_id=payload.policy_id,
                applied_by=current_user.user_id,
            )
        )
        await db.commit()


@router.delete(
    "/agents/{agent_id}/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unlink_policy(
    agent_id: UUID,
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """에이전트에서 정책 연결 해제."""
    await db.execute(
        delete(AgentPolicy).where(
            AgentPolicy.agent_id == agent_id, AgentPolicy.policy_id == policy_id
        )
    )
    await db.commit()


@router.post("/agents/{agent_id}/certifications", status_code=status.HTTP_204_NO_CONTENT)
async def link_certification(
    agent_id: UUID,
    payload: AgentCertLink,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """에이전트에 인증 연결."""
    await _ensure_agent(db, agent_id)
    cert = (
        await db.execute(
            select(Certification).where(
                Certification.certification_id == payload.certification_id
            )
        )
    ).scalar_one_or_none()
    if cert is None:
        raise HTTPException(404, "인증을 찾을 수 없습니다.")
    exists = (
        await db.execute(
            select(AgentCertification).where(
                AgentCertification.agent_id == agent_id,
                AgentCertification.certification_id == payload.certification_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(
            AgentCertification(
                agent_id=agent_id, certification_id=payload.certification_id
            )
        )
        await db.commit()


@router.delete(
    "/agents/{agent_id}/certifications/{cert_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unlink_certification(
    agent_id: UUID,
    cert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireTrustWrite),
):
    """에이전트에서 인증 연결 해제."""
    await db.execute(
        delete(AgentCertification).where(
            AgentCertification.agent_id == agent_id,
            AgentCertification.certification_id == cert_id,
        )
    )
    await db.commit()


# ── Overview ──────────────────────────────────────────────────────
@router.get("/overview", response_model=TrustOverview)
async def trust_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """신뢰 운영 요약 지표."""
    agents = await _build_agent_trust(db)
    certified = sum(1 for a in agents if a.trust_level == "certified")
    partial = sum(1 for a in agents if a.trust_level == "partial")
    unverified = sum(1 for a in agents if a.trust_level == "unverified")
    uncertified_exposed = sum(
        1
        for a in agents
        if a.visibility in _EXPOSED_VISIBILITIES and a.trust_level != "certified"
    )

    pending_certs = (
        await db.execute(
            select(func.count())
            .select_from(Certification)
            .where(Certification.state == "PENDING")
        )
    ).scalar_one()
    active_policies = (
        await db.execute(
            select(func.count()).select_from(Policy).where(Policy.status == "ACTIVE")
        )
    ).scalar_one()
    draft_policies = (
        await db.execute(
            select(func.count()).select_from(Policy).where(Policy.status == "DRAFT")
        )
    ).scalar_one()

    return TrustOverview(
        total_agents=len(agents),
        certified_agents=certified,
        partial_agents=partial,
        unverified_agents=unverified,
        pending_certifications=pending_certs,
        active_policies=active_policies,
        draft_policies=draft_policies,
        uncertified_exposed_agents=uncertified_exposed,
    )
