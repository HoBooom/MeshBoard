"""
MeshBoard — Agent-Mesh Message Broker

메시지를 저장하고 direct mention/subscription edge를 평가해 receipt를 생성합니다.
에이전트 fan-out은 요청 안에서 완료되지만 동시성과 개별 timeout을 제한합니다.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
import uuid
from functools import lru_cache
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentSubscriptionRule
from app.core.config import settings
from app.models.message import Message, MessageHeader, MessageReceipt
from app.models.workspace import WorkspaceAgent, WorkspaceEdge, WorkspaceNode
from app.models.workspace import Workspace
from app.models.conversation import Conversation
from app.models.interaction import Interaction
from app.schemas.message import PublishMessageRequest
from app.services.agent_runtime import AGENT_INVALID_RESPONSE_MESSAGE, invoke_agent
from app.services.policy_enforcement import resolve_agent_policy
from app.services.security_events import emit_security_event
from app.services.schema_compat import CURRENT_INTERACTION_SCHEMA
from app.services.subscription_rules import (
    SubscriptionEvent,
    SubscriptionRule,
    evaluate_subscription,
)
from sqlalchemy_utils import Ltree


MENTION_RE = re.compile(r"(?<!\S)@([^\s@]+)")
logger = logging.getLogger(__name__)


async def _invoke_routed_agent(
    agent_invoker,
    agent: Agent,
    user_message: str,
    semaphore,
    allowed_tool_ids_override=None,
) -> dict:
    """Bound broker fan-out so one message cannot exhaust LLM connections."""
    async with semaphore:
        kwargs = {"agent": agent, "user_message": user_message}
        # 도구 allow-list 축소는 정책 결과이므로 invoker 가 받아줄 수 있으면 항상 전달한다.
        # (invoker 의 정체가 아니라 시그니처로 판단해야 정책 강제가 테스트 대역에서도 유지된다.)
        if allowed_tool_ids_override is not None and _accepts_tool_override(agent_invoker):
            kwargs["allowed_tool_ids_override"] = allowed_tool_ids_override
        return await asyncio.wait_for(
            agent_invoker(**kwargs),
            timeout=settings.AGENT_INVOKE_TIMEOUT_SECONDS,
        )


@lru_cache(maxsize=8)
def _accepts_tool_override(invoker) -> bool:
    """invoker 가 allowed_tool_ids_override 인자를 받는지 확인합니다."""
    try:
        return "allowed_tool_ids_override" in inspect.signature(invoker).parameters
    except (TypeError, ValueError):
        return False


def _usage_from_result(result: dict) -> tuple[int, int]:
    """invoke 결과의 usage 를 (input, output) 토큰으로 정규화합니다.

    usage 를 돌려주지 않는 OpenAI-호환 서버나 테스트용 invoker 도 있으므로, 없으면 0 을 쓴다.
    0 은 "이 실행에서 토큰을 측정하지 못했다"는 뜻이며 합계를 왜곡하지 않는다.
    """
    usage = result.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0

    def _as_int(value) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return _as_int(usage.get("input_tokens")), _as_int(usage.get("output_tokens"))


async def _filter_by_subscription_rules(
    db: AsyncSession, header: MessageHeader, agent_ids: list
) -> list:
    """edge 로 매칭된 에이전트를 각자의 구독 규칙으로 한 번 더 거릅니다.

    Sandbox 시뮬레이터와 같은 평가 함수를 쓰므로 두 경로의 판정이 어긋나지 않는다.
    """
    if not agent_ids:
        return []

    rules = {
        rule.agent_id: SubscriptionRule.from_model(rule)
        for rule in (
            await db.execute(
                select(AgentSubscriptionRule).where(
                    AgentSubscriptionRule.agent_id.in_(agent_ids)
                )
            )
        ).scalars().all()
    }
    event = SubscriptionEvent(
        domain=header.domain,
        intent=header.intent,
        priority=header.priority,
        tags=tuple(header.tags or ()),
        sender_id=str(header.sender_id) if header.sender_id else None,
    )
    kept = []
    for agent_id in agent_ids:
        decision = evaluate_subscription(
            event, rules.get(agent_id), missing_rule_matches=True
        )
        if decision.matched:
            kept.append(agent_id)
        else:
            logger.debug(
                "Subscription rule filtered agent %s: %s", agent_id, decision.reason
            )
    return kept


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


def _explicit_agent_targets(
    workspace_agent_ids: list,
    agent_roles: dict,
    target_ids: list,
    target_roles: list[str],
) -> list:
    """Resolve explicit selectors while preserving workspace placement order."""
    requested_ids = set(target_ids or [])
    requested_roles = {role.casefold() for role in (target_roles or []) if role.strip()}
    return [
        agent_id
        for agent_id in workspace_agent_ids
        if agent_id in requested_ids
        or requested_roles.intersection(
            str(role).casefold() for role in agent_roles.get(agent_id, [])
        )
    ]


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
    conversation_id = payload.conversation_id
    if payload.workspace_id is not None and conversation_id is None:
        conversation = (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == payload.workspace_id,
                    Conversation.role == "workspace",
                    Conversation.state == "ACTIVE",
                )
                .order_by(Conversation.started_at)
            )
        ).scalars().first()
        if conversation is None:
            workspace = (
                await db.execute(
                    select(Workspace).where(Workspace.workspace_id == payload.workspace_id)
                )
            ).scalar_one()
            conversation = Conversation(
                workspace_id=workspace.workspace_id,
                initiator_id=workspace.owner_id,
                name=f"{workspace.name or 'Workspace'} activity",
                role="workspace",
                state="ACTIVE",
            )
            db.add(conversation)
            await db.flush()
        conversation_id = conversation.conversation_id

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
        conversation_id=conversation_id,
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

    all_workspace_agent_ids = list(
        (
            await db.execute(
                select(WorkspaceAgent.agent_id).where(WorkspaceAgent.workspace_id == header.workspace_id)
            )
        ).scalars().all()
    )
    active_agents = list(
        (
            await db.execute(
                select(Agent).where(
                    Agent.agent_id.in_(all_workspace_agent_ids),
                    Agent.status == "ACTIVE",
                )
            )
        ).scalars().all()
    )
    active_agent_by_id = {agent.agent_id: agent for agent in active_agents}
    workspace_agent_ids = [
        agent_id for agent_id in all_workspace_agent_ids if agent_id in active_agent_by_id
    ]
    workspace_agent_id_set = set(workspace_agent_ids)
    has_direct_mention, matched_agent_ids, matched_user_ids = await _direct_mentioned_targets(
        db,
        header.workspace_id,
        header.body_ref,
        workspace_agent_id_set,
    )
    has_explicit_selector = bool(header.target_ids or header.target_roles)
    if not has_direct_mention and has_explicit_selector:
        matched_agent_ids = _explicit_agent_targets(
            workspace_agent_ids,
            {
                agent_id: list(active_agent_by_id[agent_id].roles or [])
                for agent_id in workspace_agent_ids
            },
            list(header.target_ids or []),
            list(header.target_roles or []),
        )
        if header.target_ids:
            matched_user_ids = list(
                (
                    await db.execute(
                        select(WorkspaceNode.ref_id).where(
                            WorkspaceNode.workspace_id == header.workspace_id,
                            WorkspaceNode.node_type == "user",
                            WorkspaceNode.ref_id.in_(header.target_ids),
                        )
                    )
                ).scalars().all()
            )

    route_reason = (
        "matched direct @mention"
        if has_direct_mention
        else "matched explicit target"
        if has_explicit_selector
        else "matched workspace subscription edge"
    )
    receipt_ids = []

    if not has_direct_mention and not has_explicit_selector and header.sender_type in {"user", "agent"}:
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
            edge_matched = [
                agent_id
                for agent_id in dict.fromkeys(result.scalars().all())
                if agent_id in workspace_agent_id_set
            ]
            # edge 는 "누구의 말을 듣는가", 구독 규칙은 "그중 무엇에 반응하는가"이다.
            # 규칙이 없는 에이전트는 edge 만으로 수신한다(기존 동작 유지).
            matched_agent_ids = await _filter_by_subscription_rules(db, header, edge_matched)

    now = datetime.now(timezone.utc)
    root_id = uuid.uuid4()
    execution_tree_id = header.execution_tree_id or uuid.uuid4()
    header.execution_tree_id = execution_tree_id
    root_interaction = Interaction(
        interaction_id=root_id,
        schema_ver=CURRENT_INTERACTION_SCHEMA,
        conversation_id=header.conversation_id,
        execution_tree_id=execution_tree_id,
        tree_depth=0,
        tree_path=Ltree(root_id.hex),
        delegation_type="user_request" if header.sender_type == "user" else "peer",
        start_timestamp=header.sent_at,
        actor_type=header.sender_type,
        actor_id=header.sender_id,
        actor_name=header.sender_name or header.sender_type,
        target_type="broadcast",
        kind="message",
        prompt=_message_text_from_body_ref(header.body_ref)[:4000],
        involved_agents=list(matched_agent_ids),
        state="RUNNING",
        metadata_={"message_id": str(header.message_id), "routing_reason": route_reason},
    )
    db.add(root_interaction)
    await db.flush()

    handoff_by_agent = {}
    for agent_id in matched_agent_ids:
        handoff_id = uuid.uuid4()
        handoff = Interaction(
            interaction_id=handoff_id,
            schema_ver=CURRENT_INTERACTION_SCHEMA,
            conversation_id=header.conversation_id,
            parent_id=root_id,
            execution_tree_id=execution_tree_id,
            tree_depth=1,
            tree_path=Ltree(f"{root_id.hex}.{handoff_id.hex}"),
            delegation_type="orchestration",
            start_timestamp=now,
            actor_type=header.sender_type,
            actor_id=header.sender_id,
            actor_name=header.sender_name or header.sender_type,
            target_type="agent",
            target_id=agent_id,
            target_name=None,
            kind="handoff",
            involved_agents=[agent_id],
            state="RUNNING",
            metadata_={"reason": route_reason},
        )
        db.add(handoff)
        handoff_by_agent[agent_id] = handoff
    await db.flush()

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
            agent_id: active_agent_by_id[agent_id]
            for agent_id in matched_agent_ids
            if agent_id in active_agent_by_id
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

        invocation_targets = []
        for agent_id in matched_agent_ids:
            agent = agents.get(agent_id)
            agent_node = agent_nodes.get(agent_id)
            if agent is None or agent_node is None:
                continue

            # 정책은 어떤 invoker 를 쓰든 항상 강제한다. 실행 경계에서의 차단이 목적이므로
            # 호출 대상이 무엇인지에 따라 검사를 건너뛰면 안 된다.
            policy_decision = await resolve_agent_policy(db, agent, user_message)
            if not policy_decision.allowed:
                await emit_security_event(
                    "agent.policy_blocked",
                    severity="high",
                    attributes={
                        "agent_id": str(agent.agent_id),
                        "execution_tree_id": str(execution_tree_id),
                        "policy_ids": list(policy_decision.applied_policy_ids),
                        "violation_count": len(policy_decision.violations),
                    },
                )
                handoff = handoff_by_agent[agent.agent_id]
                handoff.target_name = agent.name
                handoff.state = "CANCELLED"
                handoff.complete_timestamp = datetime.now(timezone.utc)
                handoff.error_code = "POLICY_BLOCKED"
                handoff.error_message = "; ".join(policy_decision.violations)
                await _publish_agent_workspace_message(
                    db,
                    header,
                    agent,
                    "활성 정책에 의해 요청 처리가 차단되었습니다.",
                )
                agent_node.status = "active"
                agent_node.updated_at = datetime.now(timezone.utc)
                continue
            effective_message = policy_decision.message
            effective_tools = policy_decision.effective_tool_ids
            agent_node.status = "processing"
            agent_node.updated_at = datetime.now(timezone.utc)
            handoff = handoff_by_agent[agent.agent_id]
            handoff.target_name = agent.name
            invocation_targets.append(
                (agent, agent_node, effective_message, effective_tools, time.perf_counter())
            )
        # 아래 gather 로 동시에 실행되는 호출들을 하나의 parallel group 으로 묶는다.
        # 운영 분석은 이 그룹의 wall-clock 과 개별 duration 합을 비교해 실제 절약 시간을 낸다.
        # 대상이 1건이면 병렬 실행이 아니므로 그룹을 만들지 않는다(빈 그룹으로 통계를 흐리지 않기 위함).
        parallel_group_id = uuid.uuid4() if len(invocation_targets) > 1 else None
        if parallel_group_id is not None:
            for target_agent, *_ in invocation_targets:
                handoff_by_agent[target_agent.agent_id].parallel_group_id = parallel_group_id
        await db.flush()

        semaphore = asyncio.Semaphore(settings.AGENT_INVOKE_MAX_CONCURRENCY)
        invocation_results = await asyncio.gather(
            *(
                _invoke_routed_agent(agent_invoker, agent, message, semaphore, effective_tools)
                for agent, _, message, effective_tools, _ in invocation_targets
            ),
            return_exceptions=True,
        )

        for (agent, agent_node, _, _, started), result in zip(invocation_targets, invocation_results):
            handoff = handoff_by_agent[agent.agent_id]
            try:
                if isinstance(result, BaseException):
                    raise result
                if result.get("error"):
                    raise RuntimeError(str(result["error"]))
                answer = str(result.get("output") or "").strip() or AGENT_INVALID_RESPONSE_MESSAGE
                await _publish_agent_workspace_message(db, header, agent, answer)
                agent_node.status = "active"
                handoff.state = "COMPLETED"
                handoff.results = answer[:4000]
                # handoff 는 "에이전트 1회 호출"에 해당하므로 모델과 토큰 사용량을 여기에 기록한다.
                # 운영 분석의 모델별 집계가 이 행을 읽는다.
                handoff.model_used = result.get("model_used")
                token_input, token_output = _usage_from_result(result)
                handoff.token_input = token_input
                handoff.token_output = token_output
                for index, step in enumerate(result.get("steps") or [], start=1):
                    node = step.get("node")
                    if node not in {"agent_node", "mcp_tool_node"}:
                        continue
                    step_id = uuid.uuid4()
                    content = str(step.get("content") or "")[:4000]
                    db.add(
                        Interaction(
                            interaction_id=step_id,
                            schema_ver=CURRENT_INTERACTION_SCHEMA,
                            conversation_id=header.conversation_id,
                            parent_id=handoff.interaction_id,
                            execution_tree_id=execution_tree_id,
                            tree_depth=2,
                            tree_path=Ltree(
                                f"{root_id.hex}.{handoff.interaction_id.hex}.{step_id.hex}"
                            ),
                            delegation_type="pipeline",
                            actor_type="agent",
                            actor_id=agent.agent_id,
                            actor_name=agent.name,
                            kind="tool_result" if node == "mcp_tool_node" else "reasoning",
                            step_id=index,
                            results=content if node == "mcp_tool_node" else None,
                            reasoning_trace=content if node == "agent_node" else None,
                            tool_name=step.get("name"),
                            parameters={"node": node},
                            involved_agents=[agent.agent_id],
                            state="COMPLETED",
                            complete_timestamp=datetime.now(timezone.utc),
                            model_used=result.get("model_used"),
                        )
                    )
            except Exception as exc:
                logger.warning("Agent invocation failed: agent_id=%s error=%s", agent.agent_id, exc)
                await _publish_agent_workspace_message(db, header, agent, AGENT_INVALID_RESPONSE_MESSAGE)
                agent_node.status = "error"
                handoff.state = "FAILED"
                handoff.error_code = type(exc).__name__
                handoff.error_message = str(exc)[:2000]
            finally:
                handoff.complete_timestamp = datetime.now(timezone.utc)
                handoff.duration_ms = round((time.perf_counter() - started) * 1000)
                agent_node.updated_at = datetime.now(timezone.utc)
                await db.flush()
    elif header.sender_type in {"user", "agent"} and not matched_user_ids:
        recipient_name = (header.sender_name or "사용자").strip() or "사용자"
        await _publish_system_workspace_message(
            db,
            header,
            f"{recipient_name}님께 응답가능한 에이전트가 없습니다",
        )

    ignored_agent_ids = [
        agent_id for agent_id in all_workspace_agent_ids if agent_id not in set(matched_agent_ids)
    ]

    header.processed_count = len(matched_agent_ids)
    handoff_states = {handoff.state for handoff in handoff_by_agent.values()}
    root_interaction.state = (
        "FAILED"
        if "FAILED" in handoff_states
        else "CANCELLED"
        if handoff_states == {"CANCELLED"}
        else "COMPLETED"
    )
    root_interaction.complete_timestamp = datetime.now(timezone.utc)
    root_interaction.duration_ms = max(
        0,
        round((root_interaction.complete_timestamp - root_interaction.start_timestamp).total_seconds() * 1000),
    )
    await db.flush()
    return {
        "queued": True,
        "queue_message_id": header.message_id,
        "matched_agent_ids": matched_agent_ids,
        "receipt_ids": receipt_ids,
        "ignored_agent_ids": ignored_agent_ids,
    }
