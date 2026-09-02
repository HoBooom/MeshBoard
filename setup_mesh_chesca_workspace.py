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
    "Board에서 CHESCA 협상 시나리오(official / mesh / reserve / commitment / round-robin)와 "
    "OpenSynCity 정전 MPC mesh(outage_mpc_mesh, CityLearn 2022 phase_all + 정전 주입) 모드를 "
    "선택하고 Play로 실제 런타임을 step별 구동합니다."
)
TEMPLATE_ID = "mesh_chesca"
DATASET_ID = "citylearn_challenge_2023_phase_3_1"
# phase_3_1 = 6 buildings.
MESH_CHESCA_BUILDING_IDS = [f"Building_{i}" for i in range(1, 7)]

# CHESCA 전용 agent를 따로 시드하지 않고, 이미 시드된 citylearn agent를 역할만 바꿔 재사용한다.
COORDINATOR_AGENT_NAME = "City Grid Coordinator"
PEER_AGENT_NAME = "Building Battery Agent"
GUARD_AGENT_NAME = "CityLearn Constraint Guard"

# OpenSynCity(outage_mpc_mesh) 에이전틱 메시 전용 역할 agent. 없으면 이 스크립트가 생성한다.
# (블랙보드 broadcast 역할: 정전위험 감지 / 요금 예측 리드 / 탄소 예측 리드)
OUTAGE_AGENT_NAME = "City Outage Risk Agent"
PRICE_AGENT_NAME = "Price Forecast Agent"
CARBON_AGENT_NAME = "Carbon Forecast Agent"

SPECIALIZED_AGENT_SPECS = [
    {
        "name": OUTAGE_AGENT_NAME,
        "purpose": "시간대별 정전 빈도를 학습해 정전 위험창에서만 배터리 reserve를 선택적으로 켭니다.",
        "description": (
            "OpenSynCity 정전 회복력 전문 에이전트(OutageRiskAgent). 관측된 정전만으로 hour-of-day 위험도를 "
            "학습하고(causal), 위험창(저녁 피크)에서 reserve_floor를 블랙보드에 broadcast해 건물 MPC가 미리 "
            "비축하도록 유도합니다. 평상시 위험이 0이면 reserve를 끄고 순수 비용·탄소 최적화로 환원합니다."
        ),
        "metadata_": {"category": "OpenSynCity", "role": "outage_detector"},
        "roles": ["outage_detector", "broadcaster"],
    },
    {
        "name": PRICE_AGENT_NAME,
        "purpose": "구역 공통 전기요금을 예측해 모든 건물 에이전트에게 broadcast합니다.",
        "description": (
            "공유변수(SharedVarAgent·price) 리드. 환경 제공 1~3시간 예측 + 시간대 평균으로 앞으로 H시간 요금을 "
            "예측해 블랙보드에 게시하면, 각 건물 MPC가 이를 목적함수에 반영합니다."
        ),
        "metadata_": {"category": "OpenSynCity", "role": "price_lead"},
        "roles": ["price_lead", "broadcaster"],
    },
    {
        "name": CARBON_AGENT_NAME,
        "purpose": "구역 공통 탄소강도를 예측해 모든 건물 에이전트에게 broadcast합니다.",
        "description": (
            "공유변수(SharedVarAgent·carbon) 리드. 시간대 평균으로 앞으로 H시간 탄소강도를 예측해 블랙보드에 "
            "게시하면, 각 건물 MPC가 carbon_weight로 충전 시점을 친환경 시간대로 이동합니다."
        ),
        "metadata_": {"category": "OpenSynCity", "role": "carbon_lead"},
        "roles": ["carbon_lead", "broadcaster"],
    },
]


async def _ensure_agent(s, admin, spec: dict) -> Agent:
    """이름이 같은 agent가 있으면 재사용, 없으면 생성. (멱등)"""
    existing = (await s.execute(select(Agent).where(Agent.name == spec["name"]))).scalars().first()
    if existing is not None:
        return existing
    agent = Agent(
        owner_id=admin.user_id,
        name=spec["name"],
        version="0.1.0",
        purpose=spec["purpose"],
        description=spec["description"],
        approach="OpenSynCity agentic mesh (blackboard broadcast)",
        status="DRAFT",
        visibility="PRIVATE",
        metadata_=spec["metadata_"],
        roles=spec["roles"],
        tools=[],
        agent_card={"expected_input": {"step": "int", "hour": "int"}},
    )
    s.add(agent)
    await s.flush()
    print(f"   + 신규 agent 생성: {spec['name']}")
    return agent


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

        # OpenSynCity 메시 전용 역할 agent: 없으면 생성(멱등). 메시지 발행 sender 매핑 + 토폴로지에 사용.
        guard = (await s.execute(select(Agent).where(Agent.name == GUARD_AGENT_NAME))).scalars().first()
        outage_agent = await _ensure_agent(s, admin, SPECIALIZED_AGENT_SPECS[0])
        price_agent = await _ensure_agent(s, admin, SPECIALIZED_AGENT_SPECS[1])
        carbon_agent = await _ensure_agent(s, admin, SPECIALIZED_AGENT_SPECS[2])

        environment_template = {
            "id": TEMPLATE_ID,
            "name": "도시관리 mesh_chesca",
            "dataset_year": 2023,
            "dataset_id": DATASET_ID,
            "dataset_path": f"Final_mesh1-main/CHESCA-main/data/schemas/{DATASET_ID}",
            "building_count": len(MESH_CHESCA_BUILDING_IDS),
            "time_steps": 2208,
            "interval": "1 hour",
            "features": [
                "electrical_storage", "pv", "dhw_storage", "cooling_device",
                "mesh_negotiation", "outage_resilience",
            ],
            # board 시나리오(모드)는 GET /api/v1/mesh-chesca/scenarios 에서 동적으로 제공된다.
            # CHESCA 5종은 vendored CityLearn 2.1b12 워커, outage_mpc_mesh는 CityLearn_old_system
            # (2022 phase_all + 정전 주입) 메인 프로세스 런타임(app.services.agent_mesh_runtime)이 구동.
            "board_scenarios": [
                "chesca_official", "chesca_mesh", "reserve_contract_mesh",
                "commitment_mesh", "round_robin_commitment", "outage_mpc_mesh",
            ],
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
            # OpenSynCity 에이전틱 메시 토폴로지: Coordinator(블랙보드 허브)를 중심으로 건물 peer는
            # subscription, 공유변수/정전 리드는 broadcast, Guard는 validation 엣지로 연결한다.
            # (WorkspaceNode UNIQUE = workspace+type+ref_id → agent당 노드 1개)
            placements = [
                (coord, 1),
                (peer, len(MESH_CHESCA_BUILDING_IDS)),
                (outage_agent, 1),
                (price_agent, 1),
                (carbon_agent, 1),
            ]
            if guard is not None:
                placements.append((guard, 1))

            # WorkspaceAgent (멱등).
            for agent, qty in placements:
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
            for agent, _qty in placements:
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

            # Edge: 모두 Coordinator(블랙보드 허브)로 향한다. (source → coord)
            # DB는 edge_type='subscription'만 허용(ck_workspace_edges_edge_type)하므로 전부 subscription.
            coord_node = node_by_agent[coord.agent_id]
            edge_sources = [peer, outage_agent, price_agent, carbon_agent]
            if guard is not None:
                edge_sources.append(guard)
            for src_agent in edge_sources:
                edge_type = "subscription"
                src_node = node_by_agent[src_agent.agent_id]
                existing_edge = (
                    await s.execute(
                        select(WorkspaceEdge).where(
                            WorkspaceEdge.workspace_id == ws.workspace_id,
                            WorkspaceEdge.source_node_id == src_node.node_id,
                            WorkspaceEdge.target_node_id == coord_node.node_id,
                            WorkspaceEdge.edge_type == edge_type,
                        )
                    )
                ).scalars().first()
                if existing_edge is None:
                    s.add(
                        WorkspaceEdge(
                            workspace_id=ws.workspace_id,
                            source_node_id=src_node.node_id,
                            target_node_id=coord_node.node_id,
                            edge_type=edge_type,
                            status="active",
                        )
                    )

        await s.commit()

        print(f"   - template_id: {TEMPLATE_ID} · dataset: {DATASET_ID} · buildings: {len(MESH_CHESCA_BUILDING_IDS)}")
        if coord is not None and peer is not None:
            roles = ["Coordinator", f"Peer({len(MESH_CHESCA_BUILDING_IDS)})", "OutageRisk", "PriceLead", "CarbonLead"]
            if guard is not None:
                roles.append("Guard")
            print(f"   - 토폴로지 mesh: {' + '.join(roles)} → Coordinator 허브 (Node/Edge 배치 완료)")
        else:
            print("   - agent 배치는 건너뜀 (board 전용)")
        print(f"   - workspace_id: {ws.workspace_id}")
        print()
        print("👉 frontend에서 admin으로 로그인 → 위 워크스페이스 → Board → 시나리오 선택 후 Play.")
        print("   (OpenSynCity 정전 MPC Mesh 선택 시 매 step 에이전트 자연어 소통이 메시징 페이지에 발행됩니다.)")


if __name__ == "__main__":
    asyncio.run(setup())
