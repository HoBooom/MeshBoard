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
from app.core.config import settings
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
    ExecutionNodeRead,
    ExecutionSummaryRead,
    ExecutionTreeRead,
    ArchiveResultRead,
    ModelAnalyticsRead,
    OperationsAnalyticsRead,
    ParallelGroupAnalyticsRead,
    ConnectorStatusRead,
    ConnectorTestRead,
    HealthComponent,
    OperationsOverview,
    SystemHealth,
)
from app.services.runtime_control import runtime_control
from app.services.interaction_archive import archive_completed_interactions
from app.services.security_events import emit_security_event
from app.services.schema_compat import interaction_to_current_payload

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
        runtime = runtime_control.snapshot(a.agent_id)
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
                active_executions=runtime.active_executions,
                control_generation=runtime.generation,
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
    if payload.status == "ACTIVE":
        runtime = runtime_control.activate(agent.agent_id)
    else:
        runtime = runtime_control.suspend(agent.agent_id)
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
        active_executions=runtime.active_executions,
        control_generation=runtime.generation,
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


@router.post("/archive", response_model=ArchiveResultRead)
async def archive_interactions(
    retention_days: int = 90,
    dry_run: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireOpsWrite),
):
    """보존 기간이 지난 완료 실행을 불변 아카이브로 원자적으로 이관합니다."""
    try:
        return await archive_completed_interactions(
            db, retention_days=retention_days, dry_run=dry_run
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/analytics", response_model=OperationsAnalyticsRead)
async def operations_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """모델별 토큰/실행량과 병렬 그룹의 실제 절약 시간을 집계합니다."""
    model_rows = (
        await db.execute(
            select(
                Interaction.model_used,
                func.count(Interaction.interaction_id),
                func.count(Interaction.interaction_id).filter(Interaction.state == "FAILED"),
                func.coalesce(func.sum(Interaction.token_input), 0),
                func.coalesce(func.sum(Interaction.token_output), 0),
                func.coalesce(func.avg(Interaction.duration_ms), 0),
            )
            .where(Interaction.model_used.is_not(None))
            .group_by(Interaction.model_used)
            .order_by(func.count(Interaction.interaction_id).desc())
        )
    ).all()
    models = []
    pricing = settings.model_pricing
    for model, count, failed, token_input, token_output, average_duration in model_rows:
        rates = pricing.get(model)
        estimated_cost = None
        if rates:
            estimated_cost = round(
                (int(token_input) * rates["input"] + int(token_output) * rates["output"])
                / 1_000_000,
                6,
            )
        models.append(
            ModelAnalyticsRead(
                model=model,
                execution_count=count,
                failed_count=failed,
                token_input=int(token_input),
                token_output=int(token_output),
                total_tokens=int(token_input) + int(token_output),
                average_duration_ms=round(float(average_duration), 1),
                estimated_cost_usd=estimated_cost,
            )
        )

    parallel_rows = (
        await db.execute(
            select(
                Interaction.parallel_group_id,
                func.count(Interaction.interaction_id),
                func.min(Interaction.start_timestamp),
                func.max(Interaction.complete_timestamp),
                func.coalesce(func.sum(Interaction.duration_ms), 0),
            )
            .where(Interaction.parallel_group_id.is_not(None))
            .group_by(Interaction.parallel_group_id)
            .order_by(func.min(Interaction.start_timestamp).desc())
            .limit(20)
        )
    ).all()
    parallel_groups = []
    for group_id, count, started_at, completed_at, serial_duration in parallel_rows:
        wall_duration = (
            max(0, round((completed_at - started_at).total_seconds() * 1000))
            if completed_at and started_at
            else 0
        )
        serial_ms = int(serial_duration)
        parallel_groups.append(
            ParallelGroupAnalyticsRead(
                parallel_group_id=group_id,
                execution_count=count,
                wall_duration_ms=wall_duration,
                serial_duration_ms=serial_ms,
                saved_duration_ms=max(0, serial_ms - wall_duration),
            )
        )
    return OperationsAnalyticsRead(models=models, parallel_groups=parallel_groups)


@router.get("/connectors/security-webhook", response_model=ConnectorStatusRead)
async def security_webhook_status(
    current_user: User = Depends(get_current_user),
):
    url = settings.SECURITY_WEBHOOK_URL.strip()
    return ConnectorStatusRead(
        configured=bool(url),
        endpoint=url.split("?", 1)[0] if url else None,
    )


@router.post("/connectors/security-webhook/test", response_model=ConnectorTestRead)
async def test_security_webhook(
    current_user: User = Depends(RequireOpsWrite),
):
    result = await emit_security_event(
        "connector.test",
        severity="info",
        attributes={"requested_by": str(current_user.user_id)},
    )
    return ConnectorTestRead(**result)


# ── System Health ─────────────────────────────────────────────────
@router.get("/executions", response_model=List[ExecutionSummaryRead])
async def list_executions(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """최근 Agent Mesh 실행 트리의 루트와 노드 수를 반환합니다."""
    limit = max(1, min(limit, 100))
    node_counts = (
        select(
            Interaction.execution_tree_id.label("tree_id"),
            func.count(Interaction.interaction_id).label("node_count"),
        )
        .where(Interaction.execution_tree_id.is_not(None))
        .group_by(Interaction.execution_tree_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Interaction, node_counts.c.node_count)
            .join(node_counts, node_counts.c.tree_id == Interaction.execution_tree_id)
            .where(Interaction.tree_depth == 0)
            .order_by(Interaction.start_timestamp.desc())
            .limit(limit)
        )
    ).all()
    return [
        ExecutionSummaryRead(
            execution_tree_id=root.execution_tree_id,
            root_interaction_id=root.interaction_id,
            conversation_id=root.conversation_id,
            actor_name=root.actor_name,
            prompt=root.prompt,
            state=root.state,
            node_count=node_count,
            duration_ms=root.duration_ms,
            started_at=root.start_timestamp,
        )
        for root, node_count in rows
    ]


@router.get("/executions/{execution_tree_id}", response_model=ExecutionTreeRead)
async def get_execution_tree(
    execution_tree_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ltree 경로 순서로 실행의 위임·추론·도구 노드를 반환합니다."""
    rows = (
        await db.execute(
            select(Interaction)
            .where(Interaction.execution_tree_id == execution_tree_id)
            .order_by(Interaction.tree_path, Interaction.start_timestamp)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(404, "실행 트리를 찾을 수 없습니다.")
    return ExecutionTreeRead(
        execution_tree_id=execution_tree_id,
        nodes=[
            ExecutionNodeRead(
                interaction_id=row.interaction_id,
                parent_id=row.parent_id,
                execution_tree_id=row.execution_tree_id,
                tree_depth=row.tree_depth,
                tree_path=str(row.tree_path),
                actor_name=row.actor_name,
                target_name=row.target_name,
                kind=row.kind,
                state=row.state,
                duration_ms=row.duration_ms,
                reasoning_trace=row.reasoning_trace,
                results=row.results,
                tool_name=row.tool_name,
                error_message=row.error_message,
                start_timestamp=row.start_timestamp,
                payload=interaction_to_current_payload(row),
            )
            for row in rows
        ],
    )


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
        HealthComponent(name="API 서버", status="online", detail="FastAPI v1.0.0"),
        HealthComponent(name="PostgreSQL", status=db_status, detail=db_detail),
        HealthComponent(name="Agent Runtime", status="online", detail="LangGraph 실행기 가동 중"),
        HealthComponent(name="메시지 브로커", status="online", detail="구독 라우팅 활성"),
        HealthComponent(
            name="보안 이벤트 커넥터",
            status="online" if settings.SECURITY_WEBHOOK_URL else "degraded",
            detail="웹훅 구성됨" if settings.SECURITY_WEBHOOK_URL else "선택 설정 없음",
        ),
    ]
    return SystemHealth(components=components)
