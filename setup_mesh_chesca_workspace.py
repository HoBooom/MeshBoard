"""mesh_chesca 전용 워크스페이스 생성 + 자동 배치.

생성 결과
- Workspace 'MESH-CHESCA City' (owner=admin@meshboard.io, template_id=mesh_chesca)
- WorkspaceMember(admin, creator)
- (가능하면) WorkspaceAgent: Coordinator(qty=1) + Building peer agent(qty=6) 재사용
- WorkspaceNode/Edge: Building peer → Coordinator subscription
- workspace.metadata_.environment_template.id = 'mesh_chesca' → frontend가 board view + CHESCA 패널을 렌더

board 자체는 실제 CHESCA 런타임(/api/v1/mesh-chesca/board)에서 구동되므로 agent 배치가
없어도 동작한다. 배치는 topology map / 메시지 sender 표시를 위한 보조 요소.

사용:
    uv --project backend run python setup_mesh_chesca_workspace.py
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


WORKSPACE_NAME = "MESH-CHESCA City"
WORKSPACE_DESCRIPTION = (
    "CityLearn 2023 기반 CHESCA 컨트롤러 + P2P flex 협상(mesh) 도시관리 워크스페이스. "
    "Board에서 CHESCA 협상 시나리오(official / mesh / reserve / commitment / round-robin)를 "
    "선택하고 Play로 실제 CHESCA 런타임을 step별 구동합니다."
)
TEMPLATE_ID = "mesh_chesca"
DATASET_ID = "citylearn_challenge_2023_phase_3_1"
# phase_3_1 = 6 buildings.
MESH_CHESCA_BUILDING_IDS = [f"Building_{i}" for i in range(1, 7)]

# CHESCA 전용 agent를 따로 시드하지 않고, 이미 시드된 citylearn agent를 역할만 바꿔 재사용한다.
COORDINATOR_AGENT_NAME = "City Grid Coordinator"
PEER_AGENT_NAME = "Building Battery Agent"


async def setup() -> None:
    async with async_session_factory() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@meshboard.io"))
        ).scalars().first()
        if admin is None:
            print("❌ admin@meshboard.io 사용자가 없습니다. seed_agents.py 먼저 실행하세요.")
            sys.exit(1)

        coord = (await s.execute(select(Agent).where(Agent.name == COORDINATOR_AGENT_NAME))).scalars().first()
        peer = (await s.execute(select(Agent).where(Agent.name == PEER_AGENT_NAME))).scalars().first()
        if coord is None or peer is None:
            print(
                "⚠️  CHESCA 역할로 재사용할 agent가 없습니다 "
                f"(누락: {[n for n, a in [(COORDINATOR_AGENT_NAME, coord), (PEER_AGENT_NAME, peer)] if a is None]}). "
                "워크스페이스는 board 전용으로 생성하고 agent 배치는 건너뜁니다. "
                "(원하면 seed_grid_agents.py 실행 후 다시 돌리세요.)"
            )

        environment_template = {
            "id": TEMPLATE_ID,
            "name": "도시관리 mesh_chesca",
            "dataset_year": 2023,
            "dataset_id": DATASET_ID,
            "dataset_path": f"Final_mesh1-main/CHESCA-main/data/schemas/{DATASET_ID}",
            "building_count": len(MESH_CHESCA_BUILDING_IDS),
            "time_steps": 2208,
            "interval": "1 hour",
            "features": ["electrical_storage", "pv", "dhw_storage", "cooling_device", "mesh_negotiation"],
        }
        agent_building_mapping = None
        if coord is not None and peer is not None:
            agent_building_mapping = {
                "environment_template_id": TEMPLATE_ID,
                "central_controller_agents": [
                    {"agent_id": str(coord.agent_id), "agent_name": coord.name},
                ],
                "buildings": [
                    {
                        "building_id": bid,
                        "assigned_agent_id": str(peer.agent_id),
                        "assigned_agent_name": peer.name,
                        "metadata": {"role": "chesca_peer"},
                    }
                    for bid in MESH_CHESCA_BUILDING_IDS
                ],
            }
        ws_metadata = {
            "template_id": TEMPLATE_ID,
            "environment_template": environment_template,
            "mesh_chesca_dataset": DATASET_ID,
            "mapped_building_count": len(MESH_CHESCA_BUILDING_IDS),
        }
        if agent_building_mapping is not None:
            ws_metadata["agent_building_mapping"] = agent_building_mapping

        # 멱등: 이름 중복이면 기존 워크스페이스 재사용.
        ws = (
            await s.execute(select(Workspace).where(Workspace.name == WORKSPACE_NAME))
        ).scalars().first()
        if ws is None:
            ws = Workspace(
                workspace_id=uuid4(),
                name=WORKSPACE_NAME,
                description=WORKSPACE_DESCRIPTION,
                tags=["mesh-chesca", "citylearn-2023", "auto-seeded"],
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

        # admin 멤버 등록 (멱등).
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
                    role="creator",
                    granted_by=admin.user_id,
                )
            )

        if coord is not None and peer is not None:
            # WorkspaceAgent (멱등).
            for agent, qty in [(coord, 1), (peer, len(MESH_CHESCA_BUILDING_IDS))]:
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

            # WorkspaceNode (UNIQUE: workspace_id + node_type + ref_id).
            node_by_agent: dict = {}
            for agent in [coord, peer]:
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

            # Edge: peer → coordinator (subscription).
            source_node = node_by_agent[peer.agent_id]
            target_node = node_by_agent[coord.agent_id]
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

        print(f"   - template_id: {TEMPLATE_ID} · dataset: {DATASET_ID} · buildings: {len(MESH_CHESCA_BUILDING_IDS)}")
        if coord is not None and peer is not None:
            print("   - WorkspaceAgent: Coordinator(1) + Peer(6), Node/Edge 배치 완료")
        else:
            print("   - agent 배치는 건너뜀 (board 전용)")
        print(f"   - workspace_id: {ws.workspace_id}")
        print()
        print("👉 frontend에서 admin으로 로그인 → 위 워크스페이스 → Board → CHESCA 시나리오 선택 후 Play.")


if __name__ == "__main__":
    asyncio.run(setup())
