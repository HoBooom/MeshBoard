"""
MeshBoard — Agent-Mesh Message Broker

PH3-mesh-001 범위의 동기식 발행 브로커입니다. 이 단계에서는 메시지를
MESSAGE_HEADERS 에 기록하고, 이후 PH3-mesh-002 라우팅/큐 처리 단계에서
구독 규칙 평가와 receipt 생성을 붙일 수 있도록 얇은 서비스 경계를 둡니다.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSubscriptionRule
from app.models.message import Message, MessageHeader, MessageReceipt
from app.models.workspace import WorkspaceAgent
from app.schemas.message import PublishMessageRequest


PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def build_inline_body_ref(payload: dict) -> str:
    """payload 를 body_ref 에 저장 가능한 결정적 inline JSON 참조로 직렬화합니다."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"inline:json:{encoded}"


async def publish_message_header(
    db: AsyncSession,
    payload: PublishMessageRequest,
    *,
    sender_id,
    sender_name: Optional[str],
) -> MessageHeader:
    """검증된 발행 요청을 MESSAGE_HEADERS 행으로 저장합니다."""
    header = MessageHeader(
        sender_id=sender_id,
        sender_type=payload.sender_type,
        sender_name=payload.sender_name or sender_name,
        domain=payload.domain,
        intent=payload.intent,
        priority=payload.priority,
        tags=payload.tags,
        target_ids=payload.target_ids,
        target_roles=payload.target_roles,
        scope=payload.scope,
        execution_tree_id=payload.execution_tree_id,
        workspace_id=payload.workspace_id,
        conversation_id=payload.conversation_id,
        body_ref=build_inline_body_ref(payload.payload),
        expires_at=payload.expires_at,
        processed_count=0,
    )
    db.add(header)
    await db.flush()
    await db.refresh(header)
    return header


def _rule_matches_message(
    rule: AgentSubscriptionRule,
    header: MessageHeader,
) -> tuple[bool, str]:
    if not rule.is_active:
        return False, "subscription rule inactive"
    if rule.ignore_senders and header.sender_id in rule.ignore_senders:
        return False, "sender ignored"
    if rule.ignore_tags and set(rule.ignore_tags).intersection(header.tags or []):
        return False, "tag ignored"
    if rule.watch_domains and header.domain not in rule.watch_domains:
        return False, "domain not watched"
    if rule.watch_intents and header.intent not in rule.watch_intents:
        return False, "intent not watched"
    if rule.watch_tags and not set(rule.watch_tags).intersection(header.tags or []):
        return False, "tag not watched"
    if PRIORITY_RANK[header.priority] < PRIORITY_RANK[rule.min_priority]:
        return False, "priority below rule threshold"
    return True, "matched subscription rule"


async def route_workspace_message(
    db: AsyncSession,
    header: MessageHeader,
) -> dict:
    """workspace scope 메시지를 큐에 등록하고 구독 중인 에이전트 receipt 를 생성합니다."""
    if header.workspace_id is None:
        return {
            "queued": False,
            "queue_message_id": None,
            "matched_agent_ids": [],
            "receipt_ids": [],
            "ignored_agent_ids": [],
        }

    queued_message = Message(
        message_id=header.message_id,
        workspace_id=header.workspace_id,
        conversation_id=header.conversation_id,
        participant_id=header.sender_id,
        participant_type=header.sender_type,
        content=header.body_ref,
    )
    db.add(queued_message)

    result = await db.execute(
        select(WorkspaceAgent.agent_id, AgentSubscriptionRule)
        .outerjoin(
            AgentSubscriptionRule,
            AgentSubscriptionRule.agent_id == WorkspaceAgent.agent_id,
        )
        .where(WorkspaceAgent.workspace_id == header.workspace_id)
    )

    matched_agent_ids = []
    ignored_agent_ids = []
    receipt_ids = []
    for agent_id, rule in result.all():
        if rule is None:
            ignored_agent_ids.append(agent_id)
            continue
        matched, reason = _rule_matches_message(rule, header)
        if not matched:
            ignored_agent_ids.append(agent_id)
            continue
        receipt = MessageReceipt(
            message_id=header.message_id,
            agent_id=agent_id,
            decision="consumed",
            reason=reason,
        )
        db.add(receipt)
        await db.flush()
        matched_agent_ids.append(agent_id)
        receipt_ids.append(receipt.receipt_id)

    header.processed_count = len(matched_agent_ids)
    await db.flush()
    return {
        "queued": True,
        "queue_message_id": header.message_id,
        "matched_agent_ids": matched_agent_ids,
        "receipt_ids": receipt_ids,
        "ignored_agent_ids": ignored_agent_ids,
    }
