"""
MeshBoard — Agent-Mesh Message Broker

PH3-mesh-001 범위의 동기식 발행 브로커입니다. 이 단계에서는 메시지를
MESSAGE_HEADERS 에 기록하고, 이후 PH3-mesh-002 라우팅/큐 처리 단계에서
구독 규칙 평가와 receipt 생성을 붙일 수 있도록 얇은 서비스 경계를 둡니다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.message import Message, MessageHeader, MessageReceipt
from app.models.workspace import WorkspaceAgent, WorkspaceEdge, WorkspaceNode
from app.schemas.message import PublishMessageRequest
from app.services.agent_runtime import AGENT_INVALID_RESPONSE_MESSAGE, invoke_agent


MENTION_RE = re.compile(r"(?<!\S)@([^\s@]+)")


def build_inline_body_ref(payload: dict) -> str:
    """payload 를 body_ref 에 저장 가능한 결정적 inline JSON 참조로 직렬화합니다."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"inline:json:{encoded}"


def _message_text_from_body_ref(body_ref: str) -> str:
    if not body_ref.startswith("inline:json:"):
        return body_ref
    try:
        payload = json.loads(body_ref.replace("inline:json:", "", 1))
    except json.JSONDecodeError:
        return body_ref
    if isinstance(payload, dict):
        value = payload.get("message") or payload.get("question")
        if value:
            return str(value)
    return json.dumps(payload, ensure_ascii=False)


def _mention_key(display_name: str) -> str:
    return re.sub(r"\s+", "_", display_name.strip()).lower()


async def _direct_mentioned_targets(
    db: AsyncSession,
    workspace_id,
    body_ref: str,
    workspace_agent_id_set: set,
) -> tuple[bool, list, list]:
    tokens = [match.group(1).lower() for match in MENTION_RE.finditer(_message_text_from_body_ref(body_ref))]
    if not tokens:
        return False, [], []

    mentioned_nodes = (
        await db.execute(
            select(WorkspaceNode).where(
                WorkspaceNode.workspace_id == workspace_id,
                WorkspaceNode.node_type.in_(["agent", "user"]),
                WorkspaceNode.status != "error",
            )
        )
    ).scalars().all()
    agent_id_by_token = {
        _mention_key(node.display_name): node.ref_id
        for node in mentioned_nodes
        if node.node_type == "agent" and node.ref_id in workspace_agent_id_set
    }
    user_id_by_token = {
        _mention_key(node.display_name): node.ref_id
        for node in mentioned_nodes
        if node.node_type == "user"
    }

    matched_agent_ids = []
    matched_user_ids = []
    for token in tokens:
        agent_id = agent_id_by_token.get(token)
        if agent_id is not None and agent_id not in matched_agent_ids:
            matched_agent_ids.append(agent_id)
        user_id = user_id_by_token.get(token)
        if user_id is not None and user_id not in matched_user_ids:
            matched_user_ids.append(user_id)
    return True, matched_agent_ids, matched_user_ids


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


async def _publish_system_workspace_message(
    db: AsyncSession,
    source_header: MessageHeader,
    message: str,
) -> MessageHeader:
    system_header = MessageHeader(
        sender_id=source_header.sender_id,
        sender_type="system",
        sender_name="System",
        domain=source_header.domain,
        intent="routing_notice",
        priority="high",
        tags=list(dict.fromkeys([*(source_header.tags or []), "system", "routing_notice"])),
        target_ids=[source_header.sender_id],
        target_roles=[],
        scope=source_header.scope,
        execution_tree_id=source_header.execution_tree_id,
        workspace_id=source_header.workspace_id,
        conversation_id=source_header.conversation_id,
        body_ref=build_inline_body_ref(
            {
                "message": message,
                "in_reply_to": str(source_header.message_id),
                "severity": "error",
            }
        ),
        processed_count=0,
    )
    db.add(system_header)
    await db.flush()
    db.add(
        Message(
            message_id=system_header.message_id,
            workspace_id=system_header.workspace_id,
            conversation_id=system_header.conversation_id,
            participant_id=system_header.sender_id,
            participant_type="system",
            content=system_header.body_ref,
        )
    )
    return system_header


async def _publish_agent_workspace_message(
    db: AsyncSession,
    source_header: MessageHeader,
    agent: Agent,
    answer: str,
) -> MessageHeader:
    response_header = MessageHeader(
        sender_id=agent.agent_id,
        sender_type="agent",
        sender_name=agent.name,
        domain=source_header.domain,
        intent="agent_response",
        priority=source_header.priority,
        tags=list(dict.fromkeys([*(source_header.tags or []), "agent_response"])),
        target_ids=[source_header.sender_id],
        target_roles=[],
        scope=source_header.scope,
        execution_tree_id=source_header.execution_tree_id,
        workspace_id=source_header.workspace_id,
        conversation_id=source_header.conversation_id,
        body_ref=build_inline_body_ref(
            {
                "message": answer,
                "in_reply_to": str(source_header.message_id),
                "agent_id": str(agent.agent_id),
            }
        ),
        processed_count=0,
    )
    db.add(response_header)
    await db.flush()
    db.add(
        Message(
            message_id=response_header.message_id,
            workspace_id=source_header.workspace_id,
            conversation_id=source_header.conversation_id,
            participant_id=agent.agent_id,
            participant_type="agent",
            content=response_header.body_ref,
        )
    )
    return response_header


async def route_workspace_message(db: AsyncSession, header: MessageHeader, *, agent_invoker=invoke_agent) -> dict:
    """워크스페이스 메시지를 node subscription edge 기반 receipt 로 라우팅합니다."""
    if header.workspace_id is None:
        return {
            "queued": False,
            "queue_message_id": None,
            "matched_agent_ids": [],
            "receipt_ids": [],
            "ignored_agent_ids": [],
        }

    db.add(
        Message(
            message_id=header.message_id,
            workspace_id=header.workspace_id,
            conversation_id=header.conversation_id,
            participant_id=header.sender_id,
            participant_type=header.sender_type,
            content=header.body_ref,
        )
    )

    workspace_agent_ids = list(
        (
            await db.execute(
                select(WorkspaceAgent.agent_id).where(WorkspaceAgent.workspace_id == header.workspace_id)
            )
        ).scalars().all()
    )
    workspace_agent_id_set = set(workspace_agent_ids)
    has_direct_mention, matched_agent_ids, matched_user_ids = await _direct_mentioned_targets(
        db,
        header.workspace_id,
        header.body_ref,
        workspace_agent_id_set,
    )
    route_reason = "matched direct @mention" if matched_agent_ids else "matched workspace subscription edge"
    receipt_ids = []

    if not has_direct_mention and header.sender_type in {"user", "agent"}:
        sender_node = (
            await db.execute(
                select(WorkspaceNode).where(
                    WorkspaceNode.workspace_id == header.workspace_id,
                    WorkspaceNode.node_type == header.sender_type,
                    WorkspaceNode.ref_id == header.sender_id,
                )
            )
        ).scalar_one_or_none()
        if sender_node is not None:
            result = await db.execute(
                select(WorkspaceNode.ref_id)
                .join(WorkspaceEdge, WorkspaceEdge.source_node_id == WorkspaceNode.node_id)
                .where(
                    WorkspaceEdge.workspace_id == header.workspace_id,
                    WorkspaceEdge.target_node_id == sender_node.node_id,
                    WorkspaceEdge.edge_type == "subscription",
                    WorkspaceEdge.status == "active",
                    WorkspaceNode.workspace_id == header.workspace_id,
                    WorkspaceNode.node_type == "agent",
                    WorkspaceNode.status != "error",
                )
            )
            matched_agent_ids = [
                agent_id
                for agent_id in dict.fromkeys(result.scalars().all())
                if agent_id in workspace_agent_id_set
            ]

    for agent_id in matched_agent_ids:
        receipt = MessageReceipt(
            message_id=header.message_id,
            agent_id=agent_id,
            decision="consumed",
            reason=route_reason,
        )
        db.add(receipt)
        await db.flush()
        receipt_ids.append(receipt.receipt_id)

    if matched_agent_ids:
        agents = {
            agent.agent_id: agent
            for agent in (
                await db.execute(select(Agent).where(Agent.agent_id.in_(matched_agent_ids)))
            ).scalars().all()
        }
        agent_nodes = {
            node.ref_id: node
            for node in (
                await db.execute(
                    select(WorkspaceNode).where(
                        WorkspaceNode.workspace_id == header.workspace_id,
                        WorkspaceNode.node_type == "agent",
                        WorkspaceNode.ref_id.in_(matched_agent_ids),
                    )
                )
            ).scalars().all()
        }
        user_message = _message_text_from_body_ref(header.body_ref)

        for agent_id in matched_agent_ids:
            agent = agents.get(agent_id)
            agent_node = agent_nodes.get(agent_id)
            if agent is None or agent_node is None:
                continue

            agent_node.status = "processing"
            agent_node.updated_at = datetime.now(timezone.utc)
            await db.flush()

            try:
                result = await agent_invoker(agent=agent, user_message=user_message)
                if result.get("error"):
                    raise RuntimeError(str(result["error"]))
                answer = str(result.get("output") or "").strip() or AGENT_INVALID_RESPONSE_MESSAGE
                await _publish_agent_workspace_message(db, header, agent, answer)
                agent_node.status = "active"
            except Exception:
                await _publish_agent_workspace_message(db, header, agent, AGENT_INVALID_RESPONSE_MESSAGE)
                agent_node.status = "error"
            finally:
                agent_node.updated_at = datetime.now(timezone.utc)
                await db.flush()
    elif header.sender_type in {"user", "agent"} and not matched_user_ids:
        recipient_name = (header.sender_name or "사용자").strip() or "사용자"
        await _publish_system_workspace_message(
            db,
            header,
            f"{recipient_name}님께 응답가능한 에이전트가 없습니다",
        )

    ignored_agent_ids = [agent_id for agent_id in workspace_agent_ids if agent_id not in set(matched_agent_ids)]

    header.processed_count = len(matched_agent_ids)
    await db.flush()
    return {
        "queued": True,
        "queue_message_id": header.message_id,
        "matched_agent_ids": matched_agent_ids,
        "receipt_ids": receipt_ids,
        "ignored_agent_ids": ignored_agent_ids,
    }
