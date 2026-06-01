"""Grid-Agent 전용 새 워크스페이스 생성 + 자동 배치.

생성 결과
- Workspace 'Grid-Agent CityLearn' (owner=admin@meshboard.io, template_id=citylearn-2022)
- WorkspaceMember(admin, developer)
- WorkspaceAgent × 3: Coordinator(qty=1) / Guard(qty=1) / Building Battery Agent(qty=17)
- WorkspaceNode × 3 (UNIQUE constraint(workspace_id, node_type, ref_id) 때문에 ref_id별 1개)
- WorkspaceEdge: Building → Coordinator subscription, Coordinator → Guard subscription
- workspace.metadata_.agent_building_mapping에 Building_1~17 → Battery Agent agent_id 일대일 매핑

사용:
    uv --project backend run python setup_grid_agent_workspace.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.agent import Agent
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceAgent,
    WorkspaceEdge,
    WorkspaceMember,
    WorkspaceNode,
)


WORKSPACE_NAME = "Grid-Agent CityLearn"
WORKSPACE_DESCRIPTION = (
    "Grid-Agent / MACRO-Mesh 통합 검증용 워크스페이스. "
    "Coordinator + Constraint Guard + 17 Building Battery Agent가 자동 배치되며 "
    "grid_agent / macro_mesh agent-mesh mode + Play로 step별 plan/negotiate를 트리거합니다."
)
TEMPLATE_ID = "citylearn-2022"

# AM-engine-001의 phase_all 데이터셋과 일치하는 17 building.
CITYLEARN_BUILDING_IDS = [f"Building_{i}" for i in range(1, 18)]


async def setup() -> None:
    async with async_session_factory() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@meshboard.io"))
        ).scalars().first()
        if admin is None:
            print("❌ admin@meshboard.io 사용자가 없습니다. seed_agents.py 먼저 실행하세요.")
            sys.exit(1)

        coord = (await s.execute(select(Agent).where(Agent.name == "City Grid Coordinator"))).scalars().first()
        guard = (await s.execute(select(Agent).where(Agent.name == "CityLearn Constraint Guard"))).scalars().first()
        battery = (await s.execute(select(Agent).where(Agent.name == "Building Battery Agent"))).scalars().first()
        missing = [name for name, ag in [("Coordinator", coord), ("Guard", guard), ("Battery", battery)] if ag is None]
        if missing:
            print(f"❌ seed_grid_agents.py 먼저 실행하세요. 누락: {missing}")
            sys.exit(1)

        # 멱등: 이름 중복이면 기존 워크스페이스 재사용.
        ws = (
            await s.execute(select(Workspace).where(Workspace.name == WORKSPACE_NAME))
        ).scalars().first()

        agent_building_mapping = {
            "environment_template_id": TEMPLATE_ID,
            "central_controller_agents": [
                {"agent_id": str(coord.agent_id), "agent_name": coord.name},
                {"agent_id": str(guard.agent_id), "agent_name": guard.name},
            ],
            "buildings": [
                {
                    "building_id": bid,
                    "assigned_agent_id": str(battery.agent_id),
                    "assigned_agent_name": battery.name,
                    "metadata": {"battery_capacity": 6.4, "pv_nominal_power": 5.0},
                }
                for bid in CITYLEARN_BUILDING_IDS
            ],
        }
        ws_metadata = {
            "template_id": TEMPLATE_ID,
            "environment_template": {"id": TEMPLATE_ID, "name": "도시 관리 (CityLearn - 2022 Data)"},
            "agent_building_mapping": agent_building_mapping,
            "mapped_building_count": len(CITYLEARN_BUILDING_IDS),
        }

        if ws is None:
            ws = Workspace(
                workspace_id=uuid4(),
                name=WORKSPACE_NAME,
                description=WORKSPACE_DESCRIPTION,
                tags=["grid-agent", "citylearn", "auto-seeded"],
                metadata_=ws_metadata,
                owner_id=admin.user_id,
                state="ACTIVE",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            s.add(ws)
            await s.flush()
            print(f"✅ 새 워크스페이스 생성: {ws.workspace_id}")
        else:
            ws.metadata_ = ws_metadata
            await s.flush()
            print(f"♻️  기존 워크스페이스 재사용: {ws.workspace_id} (metadata 갱신)")

        # admin을 developer로 등록 (멱등).
        existing_member = (
            await s.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == ws.workspace_id,
                    WorkspaceMember.user_id == admin.user_id,
                )
            )
        ).scalars().first()
        if existing_member is None:
            s.add(
                WorkspaceMember(
                    workspace_id=ws.workspace_id,
                    user_id=admin.user_id,
                    role="creator",  # DB constraint: viewer/operator/creator
                    granted_by=admin.user_id,
                )
            )

        # WorkspaceAgent × 3 (멱등).
        for agent, qty in [(coord, 1), (guard, 1), (battery, 17)]:
            existing = (
                await s.execute(
                    select(WorkspaceAgent).where(
                        WorkspaceAgent.workspace_id == ws.workspace_id,
                        WorkspaceAgent.agent_id == agent.agent_id,
                    )
                )
            ).scalars().first()
            if existing is None:
                s.add(WorkspaceAgent(workspace_id=ws.workspace_id, agent_id=agent.agent_id, quantity=qty))
            else:
                existing.quantity = qty

        # WorkspaceNode × 3 (UNIQUE constraint: workspace_id + node_type + ref_id).
        node_by_agent: dict = {}
        for agent in [coord, guard, battery]:
            existing_node = (
                await s.execute(
                    select(WorkspaceNode).where(
                        WorkspaceNode.workspace_id == ws.workspace_id,
                        WorkspaceNode.node_type == "agent",
                        WorkspaceNode.ref_id == agent.agent_id,
                    )
                )
            ).scalars().first()
            if existing_node is None:
                node = WorkspaceNode(
                    workspace_id=ws.workspace_id,
                    node_type="agent",
                    ref_id=agent.agent_id,
                    display_name=agent.name,
                    status="active",
                )
                s.add(node)
                await s.flush()
                node_by_agent[agent.agent_id] = node
            else:
                existing_node.status = "active"
                node_by_agent[agent.agent_id] = existing_node

        # Edges: Building → Coordinator (subscription), Coordinator → Guard (subscription).
        for source_agent, target_agent in [(battery, coord), (coord, guard)]:
            source_node = node_by_agent[source_agent.agent_id]
            target_node = node_by_agent[target_agent.agent_id]
            existing_edge = (
                await s.execute(
                    select(WorkspaceEdge).where(
                        WorkspaceEdge.workspace_id == ws.workspace_id,
                        WorkspaceEdge.source_node_id == source_node.node_id,
                        WorkspaceEdge.target_node_id == target_node.node_id,
                        WorkspaceEdge.edge_type == "subscription",
                    )
                )
            ).scalars().first()
            if existing_edge is None:
                s.add(
                    WorkspaceEdge(
                        workspace_id=ws.workspace_id,
                        source_node_id=source_node.node_id,
                        target_node_id=target_node.node_id,
                        edge_type="subscription",
                        status="active",
                    )
                )

        await s.commit()

        print(f"   - WorkspaceAgent: 3종 (Coordinator/Guard/Battery×17)")
        print(f"   - WorkspaceNode: 3 (UNIQUE constraint로 ref_id당 1개)")
        print(f"   - WorkspaceEdge: Battery→Coordinator + Coordinator→Guard")
        print(f"   - agent_building_mapping: Building_1~17 → Battery Agent agent_id 일괄 매핑")
        print(f"   - workspace_id: {ws.workspace_id}")
        print()
        print("👉 frontend에서 admin 계정으로 로그인 후 위 workspace_id를 열면 map/board에 노드가 보입니다.")


if __name__ == "__main__":
    asyncio.run(setup())
