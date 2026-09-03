"""워크스페이스 밖에서 일어나는 단일 에이전트 실행의 실행 트리 기록.

브로커(`message_broker.route_workspace_message`)는 워크스페이스 메시지 라우팅을 트리로 남기지만,
에이전트를 직접 호출하는 `POST /agents/{id}/invoke` 경로는 아무 기록도 남기지 않았다.
같은 실행인데 진입점에 따라 추적 가능 여부가 갈리면 "모든 실행 경로를 남긴다"는 설계가 성립하지 않는다.

트리 모양은 브로커와 동일하게 맞춘다 — 운영 화면의 실행 트리 조회가 두 경로를 구분 없이 읽는다.

    root(user_request, depth 0)
      └ handoff(depth 1)          ← 에이전트 1회 호출. 모델·토큰·소요시간이 여기 붙는다.
          └ reasoning/tool_result(depth 2)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_utils import Ltree

from app.models.agent import Agent
from app.models.interaction import Interaction
from app.services.schema_compat import CURRENT_INTERACTION_SCHEMA

_MAX_TEXT = 4000


def _usage(result: dict[str, Any]) -> tuple[int, int]:
    usage = result.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0

    def _as_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return _as_int(usage.get("input_tokens")), _as_int(usage.get("output_tokens"))


async def record_direct_invocation(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    actor_name: str,
    agent: Agent,
    prompt: str,
    started_at: datetime,
    result: Optional[dict[str, Any]] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    state: str = "COMPLETED",
) -> uuid.UUID:
    """직접 호출 1건을 실행 트리로 남기고 execution_tree_id 를 돌려줍니다.

    `result` 가 없으면(정책 차단·실행 실패) 트리는 root 와 handoff 만 갖고, 실패 사유가 handoff 에 남는다.
    """
    completed_at = datetime.now(timezone.utc)
    duration_ms = max(0, round((completed_at - started_at).total_seconds() * 1000))
    execution_tree_id = uuid.uuid4()
    root_id = uuid.uuid4()
    handoff_id = uuid.uuid4()

    db.add(
        Interaction(
            interaction_id=root_id,
            schema_ver=CURRENT_INTERACTION_SCHEMA,
            conversation_id=None,
            execution_tree_id=execution_tree_id,
            tree_depth=0,
            tree_path=Ltree(root_id.hex),
            delegation_type="user_request",
            start_timestamp=started_at,
            complete_timestamp=completed_at,
            duration_ms=duration_ms,
            actor_type="user",
            actor_id=actor_id,
            actor_name=actor_name,
            target_type="agent",
            target_id=agent.agent_id,
            target_name=agent.name,
            kind="message",
            prompt=prompt[:_MAX_TEXT],
            involved_agents=[agent.agent_id],
            state=state,
            metadata_={"entrypoint": "agent_invoke"},
        )
    )

    token_input, token_output = _usage(result or {})
    db.add(
        Interaction(
            interaction_id=handoff_id,
            schema_ver=CURRENT_INTERACTION_SCHEMA,
            conversation_id=None,
            parent_id=root_id,
            execution_tree_id=execution_tree_id,
            tree_depth=1,
            tree_path=Ltree(f"{root_id.hex}.{handoff_id.hex}"),
            delegation_type="orchestration",
            start_timestamp=started_at,
            complete_timestamp=completed_at,
            duration_ms=duration_ms,
            actor_type="user",
            actor_id=actor_id,
            actor_name=actor_name,
            target_type="agent",
            target_id=agent.agent_id,
            target_name=agent.name,
            kind="handoff",
            involved_agents=[agent.agent_id],
            state=state,
            results=(str(result.get("output") or "")[:_MAX_TEXT] if result else None),
            error_code=error_code,
            error_message=(error_message[:2000] if error_message else None),
            model_used=(result or {}).get("model_used"),
            token_input=token_input,
            token_output=token_output,
            metadata_={"entrypoint": "agent_invoke"},
        )
    )
    await db.flush()

    for index, step in enumerate((result or {}).get("steps") or [], start=1):
        node = step.get("node")
        if node not in {"agent_node", "mcp_tool_node"}:
            continue
        step_id = uuid.uuid4()
        content = str(step.get("content") or "")[:_MAX_TEXT]
        db.add(
            Interaction(
                interaction_id=step_id,
                schema_ver=CURRENT_INTERACTION_SCHEMA,
                conversation_id=None,
                parent_id=handoff_id,
                execution_tree_id=execution_tree_id,
                tree_depth=2,
                tree_path=Ltree(f"{root_id.hex}.{handoff_id.hex}.{step_id.hex}"),
                delegation_type="pipeline",
                start_timestamp=started_at,
                complete_timestamp=completed_at,
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
                model_used=(result or {}).get("model_used"),
                metadata_={"entrypoint": "agent_invoke"},
            )
        )
    await db.flush()
    return execution_tree_id
