"""로컬 스택 전체를 한 번에 확인하는 검증 스크립트.

Ollama(로컬 LLM) → LangGraph 런타임 → 도구 실행 → 브로커 라우팅 → ltree 실행 트리 →
토큰/병렬 집계까지, 실제로 동작하는지를 눈으로 볼 수 있게 순서대로 실행하고 결과를 출력한다.

DB 에 쓴 내용은 마지막에 전부 롤백하므로 실행해도 데이터가 남지 않는다.

    uv run --project backend python backend/scripts/verify_local_stack.py

옵션:
    --skip-llm   실제 LLM 호출 없이 DB/브로커 경로만 확인한다(모델이 없을 때).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import httpx  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.interaction import Interaction  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import (  # noqa: E402
    Workspace,
    WorkspaceAgent,
    WorkspaceMember,
    WorkspaceNode,
)
from app.schemas.message import PublishMessageRequest  # noqa: E402
from app.services.agent_runtime import invoke_agent  # noqa: E402
from app.services.message_broker import (  # noqa: E402
    publish_message_header,
    route_workspace_message,
)

OK = "  ✅ "
NO = "  ❌ "
WARN = "  ⚠️  "


def section(title: str) -> None:
    print(f"\n{'─' * 68}\n{title}\n{'─' * 68}")


async def check_llm_backend() -> bool:
    section("1. LLM 백엔드")
    print(f"  base_url : {settings.llm_base_url}")
    print(f"  model    : {settings.llm_default_model}")
    if settings.llm_uses_external_gateway:
        print(f"{WARN}외부 게이트웨이가 활성화돼 있습니다 — 유료 호출이 발생합니다.")
        print("      로컬만 쓰려면 backend/.env 의 RUNYOUR_API_KEY 를 비우세요.")
        return True

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.llm_base_url.replace("/v1", "") + "/api/tags")
            models = {m["name"] for m in response.json().get("models", [])}
    except Exception as exc:  # noqa: BLE001
        print(f"{NO}로컬 LLM 서버에 연결할 수 없습니다: {type(exc).__name__}")
        print("      'ollama serve' 를 실행했는지 확인하세요.")
        return False

    print(f"{OK}서버 응답 정상 (설치된 모델 {len(models)}개)")
    if settings.llm_default_model not in models:
        print(f"{NO}모델 '{settings.llm_default_model}' 이 없습니다.")
        print(f"      ollama pull {settings.llm_default_model}")
        return False
    print(f"{OK}모델 '{settings.llm_default_model}' 사용 가능")
    return True


async def check_agent_runtime() -> bool:
    section("2. 에이전트 런타임 (LangGraph + 도구 실행)")
    agent = SimpleNamespace(
        agent_id=uuid.uuid4(),
        name="Verify Agent",
        version="1.0.0",
        purpose="검증용 계산 에이전트",
        approach=None,
        description=None,
        roles=["verifier"],
        tools=["calculate"],
        agent_card={},
    )
    try:
        result = await invoke_agent(agent=agent, user_message="17 곱하기 23을 계산해줘.")
    except Exception as exc:  # noqa: BLE001
        print(f"{NO}실행 실패: {type(exc).__name__}: {exc}")
        return False

    if result.get("error"):
        print(f"{NO}런타임 오류: {result['error']}")
        return False

    nodes = [step.get("node") for step in result["steps"]]
    usage = result["usage"]
    print(f"{OK}응답: {result['output'][:80]}")
    print(f"{OK}그래프 경로: {' → '.join(nodes)}")
    print(f"{OK}도구 호출: {result['tool_calls']}")
    if usage["input_tokens"] or usage["output_tokens"]:
        print(f"{OK}토큰 사용량: input={usage['input_tokens']} output={usage['output_tokens']}")
    else:
        print(f"{WARN}이 백엔드는 usage 를 보고하지 않아 토큰이 0으로 기록됩니다.")
    if "mcp_tool_node" not in nodes:
        print(f"{WARN}모델이 도구를 쓰지 않고 바로 답했습니다(작은 모델에서 가끔 발생).")
    return True


async def check_broker_and_trace(session: AsyncSession, *, use_llm: bool) -> bool:
    section("3. 브로커 라우팅 · 실행 트리 · 집계")

    tag = uuid.uuid4().hex[:8]
    user = User(
        name=f"verify-{tag}",
        email=f"{tag}@verify.local",
        login_id=f"verify-{tag}",
        password_hash=hash_password("verify-password"),
        state="ACTIVE",
    )
    session.add(user)
    await session.flush()

    workspace = Workspace(name=f"verify-ws-{tag}", owner_id=user.user_id, state="ACTIVE")
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=workspace.workspace_id,
            user_id=user.user_id,
            role="developer",
            granted_by=user.user_id,
        )
    )

    agents = []
    for index in (1, 2):
        agent = Agent(
            name=f"Verify Bot {tag}-{index}",
            version="1.0.0",
            purpose="검증용 에이전트",
            owner_id=user.user_id,
            status="ACTIVE",
            visibility="PRIVATE",
            roles=["verifier"],
            tools=["calculate"],
        )
        session.add(agent)
        await session.flush()
        session.add(
            WorkspaceAgent(workspace_id=workspace.workspace_id, agent_id=agent.agent_id)
        )
        session.add(
            WorkspaceNode(
                workspace_id=workspace.workspace_id,
                node_type="agent",
                ref_id=agent.agent_id,
                display_name=agent.name,
                status="active",
            )
        )
        agents.append(agent)
    await session.flush()

    async def stub(agent, user_message, allowed_tool_ids_override=None):
        return {
            "model_used": "stub-model",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "output": f"{agent.name} 처리 완료",
            "tool_calls": [],
            "steps": [{"node": "agent_node", "content": "stub"}],
            "transitions": [],
            "error": None,
        }

    header = await publish_message_header(
        session,
        PublishMessageRequest(
            sender_type="user",
            sender_id=user.user_id,
            domain="ops",
            intent="request",
            scope="workspace",
            workspace_id=workspace.workspace_id,
            payload={"message": "두 에이전트 모두 응답해줘"},
            target_roles=["verifier"],
        ),
        sender_id=user.user_id,
        sender_name=user.name,
    )
    started = datetime.now(timezone.utc)
    routing = await route_workspace_message(
        session, header, agent_invoker=(invoke_agent if use_llm else stub)
    )
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    print(f"{OK}라우팅된 에이전트 {len(routing['matched_agent_ids'])}개 "
          f"(무시 {len(routing['ignored_agent_ids'])}개), {elapsed:.1f}s")
    print(f"{OK}receipt {len(routing['receipt_ids'])}건 기록")

    rows = (
        await session.execute(
            select(Interaction)
            .where(Interaction.execution_tree_id == header.execution_tree_id)
            .order_by(Interaction.tree_depth)
        )
    ).scalars().all()
    print(f"{OK}실행 트리 {len(rows)}행")
    for row in rows:
        indent = "     " + "  " * row.tree_depth
        print(f"{indent}└ depth={row.tree_depth} {row.kind:<12} {row.state:<10} "
              f"{(row.actor_name or '')[:18]:<18} path={str(row.tree_path)[:24]}…")

    handoffs = [r for r in rows if r.kind == "handoff"]
    tokens = sum((r.token_input or 0) + (r.token_output or 0) for r in handoffs)
    if tokens:
        print(f"{OK}토큰이 실행 트리에 기록됨: 합계 {tokens} "
              f"(모델: {', '.join({r.model_used or '?' for r in handoffs})})")
    else:
        print(f"{NO}토큰이 기록되지 않았습니다.")

    groups = {r.parallel_group_id for r in handoffs if r.parallel_group_id}
    if len(handoffs) > 1 and len(groups) == 1:
        print(f"{OK}병렬 실행 {len(handoffs)}건이 하나의 그룹으로 묶임: {next(iter(groups))}")
    elif len(handoffs) > 1:
        print(f"{NO}병렬 그룹이 기록되지 않았습니다.")

    total = (
        await session.execute(
            select(func.count()).select_from(Interaction).where(
                Interaction.execution_tree_id == header.execution_tree_id,
                Interaction.kind == "handoff",
                Interaction.model_used.is_not(None),
            )
        )
    ).scalar_one()
    print(f"{OK}운영 분석이 집계할 호출 행: {total}건 "
          f"(GET /api/v1/operations/analytics 가 이 행들을 읽습니다)")
    return bool(tokens)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm", action="store_true", help="실제 LLM 호출을 건너뜁니다")
    args = parser.parse_args()

    print("MeshBoard 로컬 스택 검증")
    llm_ok = True
    if not args.skip_llm:
        llm_ok = await check_llm_backend()
        if llm_ok:
            llm_ok = await check_agent_runtime()
        if not llm_ok:
            print(f"\n{WARN}LLM 검증에 실패했습니다. DB/브로커 경로만 계속 확인합니다.")

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                revision = (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
                print(f"\n  DB 마이그레이션 리비전: {revision}")
                broker_ok = await check_broker_and_trace(session, use_llm=False)
            finally:
                await session.close()
                await transaction.rollback()
        print(f"\n{OK}DB 변경사항은 전부 롤백했습니다 — 데이터가 남지 않습니다.")
    except Exception as exc:  # noqa: BLE001
        print(f"\n{NO}DB 검증 실패: {type(exc).__name__}: {exc}")
        print("      docker compose up -d 후 'uv run alembic upgrade head' 를 실행하세요.")
        return 1
    finally:
        await engine.dispose()

    section("결과")
    print(f"  LLM 런타임      : {'통과' if llm_ok else '실패'}")
    print(f"  브로커/트레이스 : {'통과' if broker_ok else '실패'}")
    return 0 if (llm_ok and broker_ok) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
