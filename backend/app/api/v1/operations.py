"""MeshBoard — 운영 관리(Operations Console) API.

회사 내부 운영자가 에이전트 전반을 운영하기 위한 최소 기능을 제공한다.
- 운영 현황 요약 지표
- 전체 에이전트 라이프사이클(상태) 관리
- 최근 실행 활동 로그
- 시스템 구성요소 상태

상태 변경은 release_manager / trust_ops 역할이 필요하다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import RequireRoles
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.interaction import Interaction
from app.models.user import User
from app.schemas.agent import AGENT_STATUSES
from app.schemas.operations import (
    ActivityRead,
    AgentOpsRead,
    AgentStatusBreakdown,
    AgentStatusUpdate,
    HealthComponent,
    OperationsOverview,
    SystemHealth,
)

router = APIRouter(prefix="/operations", tags=["operations"])

RequireOpsWrite = RequireRoles("admin", "trust_ops", "release_manager", "governance")


# ── Overview ──────────────────────────────────────────────────────
@router.get("/overview", response_model=OperationsOverview)
async def operations_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """운영 현황 요약 지표."""
    agents = (await db.execute(select(Agent))).scalars().all()

    status_counts = {"ACTIVE": 0, "DRAFT": 0, "DEPRECATED": 0, "SUSPENDED": 0}
    visibility_counts: Dict[str, int] = {}
    for a in agents:
        if a.status in status_counts:
            status_counts[a.status] += 1
        visibility_counts[a.visibility] = visibility_counts.get(a.visibility, 0) + 1

    total_interactions = (
        await db.execute(select(func.count()).select_from(Interaction))
    ).scalar_one()

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    interactions_24h = (
        await db.execute(
            select(func.count())
            .select_from(Interaction)
            .where(Interaction.start_timestamp >= since)
        )
    ).scalar_one()

    failed = (
        await db.execute(
            select(func.count())
            .select_from(Interaction)
            .where(Interaction.state == "FAILED")
        )
    ).scalar_one()

    completed = (
        await db.execute(
            select(func.count())
            .select_from(Interaction)
            .where(Interaction.state == "COMPLETED")
        )
    ).scalar_one()

    finished = completed + failed
    success_rate = round((completed / finished) * 100, 1) if finished else 100.0

    total_tokens = (
        await db.execute(
            select(
                func.coalesce(func.sum(Interaction.token_input), 0)
                + func.coalesce(func.sum(Interaction.token_output), 0)
            )
        )
    ).scalar_one() or 0

    return OperationsOverview(
        total_agents=len(agents),
        status_breakdown=AgentStatusBreakdown(**status_counts),
        visibility_breakdown=visibility_counts,
        total_interactions=total_interactions,
        interactions_24h=interactions_24h,
        failed_interactions=failed,
        success_rate=success_rate,
        total_tokens=int(total_tokens),
    )


# ── Agent Lifecycle ───────────────────────────────────────────────
@router.get("/agents", response_model=List[AgentOpsRead])
async def list_agents_ops(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """전체 에이전트 운영 목록 (상태/소유자/최근 활동)."""
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()

    users = (await db.execute(select(User))).scalars().all()
    user_names = {u.user_id: u.name for u in users}

    # 에이전트별 마지막 활동 시각
    last_rows = await db.execute(
        select(Interaction.actor_id, func.max(Interaction.start_timestamp))
        .where(Interaction.actor_type == "agent")
        .group_by(Interaction.actor_id)
    )
    last_activity: Dict[UUID, datetime] = {row[0]: row[1] for row in last_rows.all()}

    out: List[AgentOpsRead] = []
    for a in agents:
        out.append(
            AgentOpsRead(
                agent_id=a.agent_id,
                name=a.name,
                version=a.version,
                status=a.status,
                visibility=a.visibility,
                owner_name=user_names.get(a.owner_id),
                tool_count=len(a.tools or []),
                updated_at=a.updated_at,
                last_activity=last_activity.get(a.agent_id),
            )
        )
    return out


@router.patch("/agents/{agent_id}/status", response_model=AgentOpsRead)
async def update_agent_status(
    agent_id: UUID,
    payload: AgentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireOpsWrite),
):
    """에이전트 운영 상태 변경 (ACTIVE/DRAFT/DEPRECATED/SUSPENDED)."""
    if payload.status not in AGENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status 는 {sorted(AGENT_STATUSES)} 중 하나여야 합니다.",
        )
    agent = (
        await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(404, "에이전트를 찾을 수 없습니다.")

    agent.status = payload.status
    agent.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(agent)

    users = (await db.execute(select(User))).scalars().all()
    user_names = {u.user_id: u.name for u in users}
    return AgentOpsRead(
        agent_id=agent.agent_id,
        name=agent.name,
        version=agent.version,
        status=agent.status,
        visibility=agent.visibility,
        owner_name=user_names.get(agent.owner_id),
        tool_count=len(agent.tools or []),
        updated_at=agent.updated_at,
        last_activity=None,
    )


# ── Activity Log ──────────────────────────────────────────────────
@router.get("/activity", response_model=List[ActivityRead])
async def recent_activity(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최근 에이전트 실행 활동 로그."""
    limit = max(1, min(limit, 100))
    rows = (
        await db.execute(
            select(Interaction)
            .order_by(Interaction.start_timestamp.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        ActivityRead(
            interaction_id=i.interaction_id,
            actor_name=i.actor_name,
            target_name=i.target_name,
            kind=i.kind,
            state=i.state,
            start_timestamp=i.start_timestamp,
            duration_ms=i.duration_ms,
            model_used=i.model_used,
            error_message=i.error_message,
        )
        for i in rows
    ]


# ── System Health ─────────────────────────────────────────────────
@router.get("/health", response_model=SystemHealth)
async def system_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """시스템 구성요소 상태. DB 는 실제 연결을 점검한다."""
    db_status, db_detail = "online", "pgvector/pg15"
    try:
        await db.execute(select(1))
    except Exception:  # pragma: no cover - 방어적 처리
        db_status, db_detail = "offline", "연결 실패"

    components = [
        HealthComponent(name="API 서버", status="online", detail="FastAPI v0.1.0"),
        HealthComponent(name="PostgreSQL", status=db_status, detail=db_detail),
        HealthComponent(name="Agent Runtime", status="online", detail="LangGraph 실행기 가동 중"),
        HealthComponent(name="메시지 브로커", status="online", detail="구독 라우팅 활성"),
    ]
    return SystemHealth(components=components)
