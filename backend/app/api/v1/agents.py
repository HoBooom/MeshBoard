"""
MeshBoard — Creator Workbench API

에이전트 메타데이터 등록/수정과 구독 규칙(AGENT_SUBSCRIPTION_RULES) 관리,
그리고 실제 LLM 기반 에이전트 실행(invoke) 엔드포인트를 제공합니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.agent import Agent, AgentSubscriptionRule
from app.models.user import User
from app.schemas.agent import (
    AGENT_STATUSES,
    AGENT_VISIBILITIES,
    RULE_PRIORITIES,
    AgentCreate,
    AgentRead,
    AgentUpdate,
    InvokeRequest,
    InvokeResponse,
    SubscriptionRuleCreate,
    SubscriptionRuleRead,
    ToolDescriptor,
)
from app.services.agent_runtime import invoke_agent
from app.services.tool_catalog import TOOL_REGISTRY, list_tool_descriptors


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Helpers ──────────────────────────────────────────────────────


def _ensure_valid_agent_payload(status_value: str, visibility: str) -> None:
    if status_value not in AGENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status 는 {sorted(AGENT_STATUSES)} 중 하나여야 합니다.",
        )
    if visibility not in AGENT_VISIBILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"visibility 는 {sorted(AGENT_VISIBILITIES)} 중 하나여야 합니다.",
        )


def _ensure_valid_tools(tool_ids: List[str]) -> None:
    unknown = [t for t in tool_ids if t not in TOOL_REGISTRY]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"등록되지 않은 도구(MCP) 가 포함되어 있습니다: {unknown}",
        )


def _ensure_valid_rule(rule: SubscriptionRuleCreate) -> None:
    if rule.min_priority not in RULE_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"min_priority 는 {sorted(RULE_PRIORITIES)} 중 하나여야 합니다.",
        )


async def _get_rule_for_agent(
    db: AsyncSession, agent_id: UUID
) -> Optional[AgentSubscriptionRule]:
    stmt = select(AgentSubscriptionRule).where(
        AgentSubscriptionRule.agent_id == agent_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _agent_to_read(
    agent: Agent, rule: Optional[AgentSubscriptionRule]
) -> AgentRead:
    data = AgentRead.model_validate(agent)
    if rule is not None:
        data = data.model_copy(
            update={"subscription_rule": SubscriptionRuleRead.model_validate(rule)}
        )
    return data


async def _load_owned_agent(
    db: AsyncSession, agent_id: UUID, user: User
) -> Agent:
    stmt = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 에이전트를 찾을 수 없습니다.",
        )
    if agent.owner_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 에이전트에 대한 편집 권한이 없습니다.",
        )
    return agent


# ── Tool Catalog ─────────────────────────────────────────────────


@router.get("/tools", response_model=List[ToolDescriptor])
async def list_tools(current_user: User = Depends(get_current_user)):
    """크리에이터가 UI 에서 선택할 수 있는 내장/외부 도구(MCP) 카탈로그를 반환합니다."""
    return [ToolDescriptor(**tool) for tool in list_tool_descriptors()]


# ── CRUD ─────────────────────────────────────────────────────────


@router.get("", response_model=List[AgentRead])
async def list_my_agents(
    include_all_statuses: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 사용자가 소유한 에이전트 목록을 반환합니다 (구독 규칙 포함)."""
    stmt = select(Agent).where(Agent.owner_id == current_user.user_id)
    if not include_all_statuses:
        stmt = stmt.where(Agent.status != "DEPRECATED")
    stmt = stmt.order_by(Agent.created_at.desc())

    result = await db.execute(stmt)
    agents = result.scalars().all()

    responses: List[AgentRead] = []
    for agent in agents:
        rule = await _get_rule_for_agent(db, agent.agent_id)
        responses.append(_agent_to_read(agent, rule))
    return responses


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 에이전트 상세 정보를 반환합니다 (소유자 또는 PUBLIC 에이전트만)."""
    stmt = select(Agent).where(Agent.agent_id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 에이전트를 찾을 수 없습니다.",
        )

    if agent.owner_id != current_user.user_id and agent.visibility != "PUBLIC":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이 에이전트에 대한 조회 권한이 없습니다.",
        )

    rule = await _get_rule_for_agent(db, agent.agent_id)
    return _agent_to_read(agent, rule)


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    에이전트 신규 등록.

    - 초기 상태는 `DRAFT` (본 feature PH3-creator-001 규칙).
    - 구독 규칙(subscription_rule) 이 포함되면 AGENT_SUBSCRIPTION_RULES 에 동시 저장.
    """
    _ensure_valid_agent_payload(payload.status, payload.visibility)
    _ensure_valid_tools(payload.tools)

    dup_stmt = select(Agent).where(Agent.name == payload.name)
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"이미 '{payload.name}' 이름의 에이전트가 존재합니다.",
        )

    agent = Agent(
        name=payload.name,
        version=payload.version,
        purpose=payload.purpose,
        description=payload.description,
        approach=payload.approach,
        owner_id=current_user.user_id,
        status=payload.status,
        visibility=payload.visibility,
        agent_card=payload.agent_card,
        roles=payload.roles,
        collaborators=payload.collaborators,
        tools=payload.tools,
        metadata_=payload.metadata_,
    )
    db.add(agent)
    await db.flush()

    rule: Optional[AgentSubscriptionRule] = None
    if payload.subscription_rule is not None:
        _ensure_valid_rule(payload.subscription_rule)
        rule = AgentSubscriptionRule(
            agent_id=agent.agent_id,
            watch_domains=payload.subscription_rule.watch_domains,
            watch_intents=payload.subscription_rule.watch_intents,
            watch_tags=payload.subscription_rule.watch_tags,
            watch_senders=payload.subscription_rule.watch_senders,
            watch_roles=payload.subscription_rule.watch_roles,
            ignore_senders=payload.subscription_rule.ignore_senders,
            ignore_tags=payload.subscription_rule.ignore_tags,
            min_priority=payload.subscription_rule.min_priority,
            is_active=payload.subscription_rule.is_active,
        )
        db.add(rule)

    await db.flush()
    await db.refresh(agent)
    if rule is not None:
        await db.refresh(rule)

    return _agent_to_read(agent, rule)


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """에이전트 부분 수정 — 소유자만 가능."""
    agent = await _load_owned_agent(db, agent_id, current_user)

    updates = payload.model_dump(exclude_unset=True, by_alias=False)

    if "status" in updates and updates["status"] not in AGENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status 는 {sorted(AGENT_STATUSES)} 중 하나여야 합니다.",
        )
    if "visibility" in updates and updates["visibility"] not in AGENT_VISIBILITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"visibility 는 {sorted(AGENT_VISIBILITIES)} 중 하나여야 합니다.",
        )
    if "tools" in updates:
        _ensure_valid_tools(updates["tools"])

    for key, value in updates.items():
        setattr(agent, key, value)
    agent.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(agent)

    rule = await _get_rule_for_agent(db, agent.agent_id)
    return _agent_to_read(agent, rule)


# ── Subscription Rules ───────────────────────────────────────────


@router.put(
    "/{agent_id}/subscription-rule",
    response_model=SubscriptionRuleRead,
)
async def upsert_subscription_rule(
    agent_id: UUID,
    payload: SubscriptionRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """에이전트 구독 규칙을 생성/갱신 (에이전트당 1개)."""
    agent = await _load_owned_agent(db, agent_id, current_user)
    _ensure_valid_rule(payload)

    rule = await _get_rule_for_agent(db, agent.agent_id)
    now = datetime.now(timezone.utc)
    if rule is None:
        rule = AgentSubscriptionRule(
            agent_id=agent.agent_id,
            watch_domains=payload.watch_domains,
            watch_intents=payload.watch_intents,
            watch_tags=payload.watch_tags,
            watch_senders=payload.watch_senders,
            watch_roles=payload.watch_roles,
            ignore_senders=payload.ignore_senders,
            ignore_tags=payload.ignore_tags,
            min_priority=payload.min_priority,
            is_active=payload.is_active,
            updated_at=now,
        )
        db.add(rule)
    else:
        rule.watch_domains = payload.watch_domains
        rule.watch_intents = payload.watch_intents
        rule.watch_tags = payload.watch_tags
        rule.watch_senders = payload.watch_senders
        rule.watch_roles = payload.watch_roles
        rule.ignore_senders = payload.ignore_senders
        rule.ignore_tags = payload.ignore_tags
        rule.min_priority = payload.min_priority
        rule.is_active = payload.is_active
        rule.updated_at = now

    await db.flush()
    await db.refresh(rule)
    return SubscriptionRuleRead.model_validate(rule)


@router.get(
    "/{agent_id}/subscription-rule",
    response_model=Optional[SubscriptionRuleRead],
)
async def get_subscription_rule(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """에이전트 구독 규칙 조회 — 없으면 null 반환."""
    await _load_owned_agent(db, agent_id, current_user)
    rule = await _get_rule_for_agent(db, agent_id)
    if rule is None:
        return None
    return SubscriptionRuleRead.model_validate(rule)


# ── Runtime Invocation ───────────────────────────────────────────


@router.post("/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke(
    agent_id: UUID,
    payload: InvokeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    등록된 에이전트를 실제 LLM(RunYour AI) 으로 실행합니다.

    크리에이터는 이 엔드포인트를 통해 `tools`, `purpose`, `agent_card.system_prompt`
    구성이 제대로 동작하는지 Test 할 수 있습니다.
    """
    agent = await _load_owned_agent(db, agent_id, current_user)

    try:
        result = await invoke_agent(
            agent=agent,
            user_message=payload.message,
            model=payload.model,
            checkpoint_thread_id=payload.checkpoint_thread_id,
            resume=payload.resume,
            interrupt_after_node=payload.interrupt_after_node,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return InvokeResponse(
        agent_id=agent.agent_id,
        agent_name=agent.name,
        model_used=result["model_used"],
        input=payload.message,
        output=result["output"],
        tool_calls=result["tool_calls"],
        steps=result["steps"],
        transitions=result["transitions"],
        checkpoint=result["checkpoint"],
        graph=result["graph"],
        error=result["error"],
    )
