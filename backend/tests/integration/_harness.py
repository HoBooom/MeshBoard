"""실제 PostgreSQL 에 붙는 통합 테스트 공통 하네스.

이 디렉터리의 테스트는 브로커 라우팅·권한 강제처럼 **DB 없이는 검증할 수 없는** 경로를 다룬다.
ltree·JSONB·ARRAY 를 쓰기 때문에 SQLite 대체가 불가능하다.

각 테스트는 하나의 트랜잭션 안에서 실행되고 끝나면 롤백되므로, 실행 후 DB 상태가 그대로 남는다.
`docker compose up -d` 로 DB 가 떠 있지 않으면 조용히 skip 한다 — 새로 클론한 사람이
`unittest discover` 를 돌렸을 때 실패하지 않게 하기 위함이다.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.agent import Agent
from app.models.user import User, UserRole
from app.models.workspace import (
    Workspace,
    WorkspaceAgent,
    WorkspaceEdge,
    WorkspaceMember,
    WorkspaceNode,
)

_AVAILABILITY: Optional[str] = None
"""None = 미확인, "" = 사용 가능, 그 외 = skip 사유."""


async def database_available() -> str:
    """DB 사용 가능 여부를 한 번만 확인하고 skip 사유(없으면 빈 문자열)를 돌려줍니다."""
    global _AVAILABILITY
    if _AVAILABILITY is not None:
        return _AVAILABILITY

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            revision = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
        _AVAILABILITY = (
            ""
            if revision is not None
            else "alembic 마이그레이션이 적용되지 않았습니다 (uv run alembic upgrade head)"
        )
    except Exception as exc:  # noqa: BLE001 — 어떤 연결 실패든 skip 사유로 쓴다.
        _AVAILABILITY = (
            f"PostgreSQL 을 사용할 수 없습니다 ({type(exc).__name__}). "
            "docker compose up -d 후 재실행하세요."
        )
    finally:
        await engine.dispose()
    return _AVAILABILITY


class PostgresTestCase(unittest.IsolatedAsyncioTestCase):
    """트랜잭션 격리 테스트 케이스.

    세션은 열린 커넥션에 savepoint 모드로 붙으므로, 프로덕션 코드가 commit 을 호출해도
    바깥 트랜잭션은 유지되고 teardown 의 롤백 한 번으로 전부 되돌아간다.
    """

    async def asyncSetUp(self) -> None:
        # IsolatedAsyncioTestCase 는 루프를 debug 모드로 켠다. DB 왕복은 기본 임계치(100ms)를
        # 넘기기 쉬워 "slow callback" 경고가 테스트 출력에 쏟아지므로 끈다.
        asyncio.get_running_loop().set_debug(False)

        reason = await database_available()
        if reason:
            self.skipTest(reason)

        self.engine = create_async_engine(settings.DATABASE_URL, poolclass=None)
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(
            bind=self.connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

    async def asyncTearDown(self) -> None:
        await self.session.close()
        if self.transaction.is_active:
            await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    # ── fixtures ────────────────────────────────────────────────────────────
    # 이름·이메일은 unique 제약이 있으므로 매번 uuid 로 유일하게 만든다.

    async def make_user(self, *, roles: list[str] | None = None, state: str = "ACTIVE") -> User:
        tag = uuid.uuid4().hex[:12]
        user = User(
            name=f"user-{tag}",
            email=f"{tag}@test.local",
            login_id=f"login-{tag}",
            password_hash=hash_password("test-password"),
            state=state,
        )
        self.session.add(user)
        await self.session.flush()
        for role in roles or []:
            self.session.add(UserRole(user_id=user.user_id, role=role))
        await self.session.flush()
        await self.session.refresh(user, attribute_names=["role_entries"])
        return user

    async def make_agent(
        self,
        owner: User,
        *,
        name: str | None = None,
        roles: list[str] | None = None,
        tools: list[str] | None = None,
        status: str = "ACTIVE",
        visibility: str = "PRIVATE",
    ) -> Agent:
        agent = Agent(
            name=name or f"agent-{uuid.uuid4().hex[:12]}",
            version="1.0.0",
            purpose="integration fixture",
            owner_id=owner.user_id,
            status=status,
            visibility=visibility,
            roles=roles or [],
            tools=tools or [],
        )
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def make_workspace(self, owner: User, *, state: str = "ACTIVE") -> Workspace:
        workspace = Workspace(
            name=f"ws-{uuid.uuid4().hex[:8]}",
            owner_id=owner.user_id,
            state=state,
        )
        self.session.add(workspace)
        await self.session.flush()
        self.session.add(
            WorkspaceMember(
                workspace_id=workspace.workspace_id,
                user_id=owner.user_id,
                role="developer",
                granted_by=owner.user_id,
            )
        )
        await self.session.flush()
        return workspace

    async def place_agent(self, workspace: Workspace, agent: Agent) -> WorkspaceNode:
        """워크스페이스에 에이전트를 배치하고 대응하는 그래프 노드를 만든다."""
        self.session.add(
            WorkspaceAgent(workspace_id=workspace.workspace_id, agent_id=agent.agent_id)
        )
        node = WorkspaceNode(
            workspace_id=workspace.workspace_id,
            node_type="agent",
            ref_id=agent.agent_id,
            display_name=agent.name,
            status="active",
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def add_user_node(self, workspace: Workspace, user: User) -> WorkspaceNode:
        node = WorkspaceNode(
            workspace_id=workspace.workspace_id,
            node_type="user",
            ref_id=user.user_id,
            display_name=user.name,
            status="active",
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def subscribe(self, workspace: Workspace, *, subscriber: WorkspaceNode, publisher: WorkspaceNode) -> None:
        """subscriber 가 publisher 의 메시지를 받도록 구독 edge 를 만든다.

        브로커는 `source=구독자, target=발신자` 방향으로 edge 를 조회한다.
        """
        self.session.add(
            WorkspaceEdge(
                workspace_id=workspace.workspace_id,
                source_node_id=subscriber.node_id,
                target_node_id=publisher.node_id,
                edge_type="subscription",
                status="active",
            )
        )
        await self.session.flush()
