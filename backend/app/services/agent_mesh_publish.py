"""OpenSynCity(outage_mpc_mesh) 자연어 소통 트레이스를 워크스페이스 메시지 피드로 발행.

board의 read-only GET /mesh-chesca/board 와 달리, 이 모듈은 한 step의 agent_reports(노트북
step_reports)를 실제 워크스페이스 메시지(MessageHeader + Message)로 INSERT 해서 메시징 페이지
타임라인에 에이전트들의 자연어 소통이 그대로 보이게 한다 (grid_agent / macro_mesh publish와 동일 패턴).

발행 구성(한 step):
  1. outage_risk_agent  : 정전 위험/예비 판단 (항상)
  2. price/carbon lead   : 다음 3시간 예측 broadcast (항상)
  3. building_b          : 행동(충/방전) + 근거 — 행동한 건물/정전 건물만, 최대 MAX_BUILDING_MSGS개

sender는 워크스페이스에 배치된 전용 agent로 매핑하고, 없으면 Coordinator, 그것도 없으면 system.
실패는 board 응답을 막지 않는다 (best-effort, 실패 시 rollback).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.message import Message, MessageHeader
from app.models.workspace import WorkspaceAgent
from app.services.message_broker import build_inline_body_ref


logger = logging.getLogger(__name__)

MAX_BUILDING_MSGS = 8

# agent_reports의 sender → 워크스페이스 배치 agent 이름 후보(우선순위 순). 없으면 Coordinator로 폴백.
_COORDINATOR_NAME = "City Grid Coordinator"
_SENDER_AGENT_NAMES: Dict[str, str] = {
    "outage_risk_agent": "City Outage Risk Agent",
    "price_agent": "Price Forecast Agent",
    "carbon_agent": "Carbon Forecast Agent",
}
_BUILDING_AGENT_NAME = "Building Battery Agent"


async def _placed_agents_by_name(db: AsyncSession, workspace_id: UUID) -> Dict[str, Agent]:
    """워크스페이스에 실제 배치(WorkspaceAgent)된 agent를 name→Agent 로 반환."""
    rows = (
        await db.execute(
            select(Agent)
            .join(WorkspaceAgent, WorkspaceAgent.agent_id == Agent.agent_id)
            .where(WorkspaceAgent.workspace_id == workspace_id)
        )
    ).scalars().all()
    return {a.name: a for a in rows}


async def publish_agent_mesh_step(
    *,
    db: Optional[AsyncSession],
    workspace_id: UUID,
    agent_reports: List[Dict[str, Any]],
    negotiation: Optional[Dict[str, Any]],
    step: int,
) -> int:
    """한 step의 agent_reports를 메시지로 발행. 발행한 메시지 수를 반환(실패 시 0)."""
    if db is None or not agent_reports:
        return 0

    try:
        placed = await _placed_agents_by_name(db, workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_agent_mesh_step: placement lookup failed: %s", exc)
        return 0

    coordinator = placed.get(_COORDINATOR_NAME)
    hour = int(negotiation.get("hour", (step % 24) + 1)) if negotiation else (step % 24) + 1

    def _sender_for(agent_key: str) -> tuple:
        """(sender_id, sender_type, sender_name) 결정."""
        if agent_key.startswith("building_"):
            ag = placed.get(_BUILDING_AGENT_NAME) or coordinator
        else:
            ag = placed.get(_SENDER_AGENT_NAMES.get(agent_key, ""), None) or coordinator
        if ag is not None:
            return ag.agent_id, "agent", ag.name
        return workspace_id, "system", "MESH City System"

    def _add(*, agent_key: str, display_name: str, role: str, reason: str, extras: Dict[str, Any], tags: List[str]) -> None:
        sender_id, sender_type, sender_name = _sender_for(agent_key)
        body = {
            "kind": "mesh_agent_report",
            "scenario": "outage_mpc_mesh",
            "step": step,
            "hour": hour,
            "agent": agent_key,
            "agent_label": display_name,
            "role": role,
            "message": reason,  # bodyPreview가 이 필드를 타임라인에 표시
            **extras,
        }
        body_ref = build_inline_body_ref(body)
        db.add(
            MessageHeader(
                sender_id=sender_id, sender_type=sender_type, sender_name=display_name or sender_name,
                domain="mesh_chesca", intent="mesh_agent_report", priority="medium",
                tags=["mesh_chesca", "outage_mpc_mesh", *tags],
                target_ids=[], target_roles=[],
                scope="workspace", workspace_id=workspace_id,
                body_ref=body_ref, processed_count=0,
            )
        )
        db.add(
            Message(
                workspace_id=workspace_id,
                participant_id=sender_id, participant_type=sender_type,
                content=body_ref,
            )
        )

    published = 0
    try:
        # 1) 정전 위험 감지 + 공유변수(요금/탄소) 리드 — 항상 발행.
        for rep in agent_reports:
            agent_key = str(rep.get("agent", ""))
            if agent_key.startswith("building_"):
                continue
            label = {
                "outage_risk_agent": "Outage Risk Agent",
                "price_agent": "Price Lead",
                "carbon_agent": "Carbon Lead",
            }.get(agent_key, agent_key)
            extras = {k: rep[k] for k in ("risk", "reserve_floor", "forecast_next3") if k in rep}
            _add(agent_key=agent_key, display_name=label, role=str(rep.get("role", "")),
                 reason=str(rep.get("reason", "")), extras=extras, tags=["shared_signal"])
            published += 1

        # 2) 건물 에이전트 — 행동했거나 정전 중인 건물만, 최대 MAX_BUILDING_MSGS개.
        building_reps = [r for r in agent_reports if str(r.get("agent", "")).startswith("building_")]

        def _acted(r: Dict[str, Any]) -> bool:
            return bool(r.get("outage")) or abs(float(r.get("action", 0.0) or 0.0)) > 1e-3

        actives = [r for r in building_reps if _acted(r)]
        # 정전 건물을 앞에 두고, 그다음 행동 크기 순.
        actives.sort(key=lambda r: (not r.get("outage"), -abs(float(r.get("action", 0.0) or 0.0))))
        for rep in actives[:MAX_BUILDING_MSGS]:
            agent_key = str(rep.get("agent", ""))
            try:
                bnum = int(agent_key.split("_")[1]) + 1
            except (ValueError, IndexError):
                bnum = 0
            label = f"Building_{bnum} Agent"
            extras = {k: rep[k] for k in ("action", "soc", "outage", "role_ko") if k in rep}
            _add(agent_key=agent_key, display_name=label, role=str(rep.get("role", "")),
                 reason=str(rep.get("reason", "")), extras=extras,
                 tags=["building", *(["outage"] if rep.get("outage") else [])])
            published += 1

        await db.commit()
        return published
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_agent_mesh_step failed at step %s: %s", step, exc)
        await db.rollback()
        return 0


__all__ = ["publish_agent_mesh_step"]
