"""MACRO-Mesh negotiate 결과를 워크스페이스 메시지 피드로 펼쳐서 발행.

한 번의 negotiate API → 30~40+ 메시지로 분해:
  1. negotiate_start: 시작 알림
  2. round 별:
       a. round_start
       b. proposal × N (각 building이 sender)
       c. mean_field summary
       d. conflict × M
  3. merged_plan: 최종 plan
  4. negotiate_result: sandbox 검증 결과

각 메시지는 별도 MessageHeader + Message로 INSERT.
실패는 negotiate response를 막지 않는다 (silent skip + rollback).
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.message import Message, MessageHeader
from app.models.workspace import WorkspaceAgent
from app.services.citylearn_grid_agent_llm import COORDINATOR_AGENT_NAME
from app.services.citylearn_macro_mesh import BUILDING_AGENT_NAME, MacroMeshRunResult
from app.services.message_broker import build_inline_body_ref


logger = logging.getLogger(__name__)


async def publish_negotiation_messages(
    *,
    db: Optional[AsyncSession],
    workspace_id: UUID,
    result: MacroMeshRunResult,
    step: int,
    used_llm_proposers: bool,
) -> bool:
    if db is None:
        return False

    coord = (await db.execute(select(Agent).where(Agent.name == COORDINATOR_AGENT_NAME))).scalars().first()
    building = (await db.execute(select(Agent).where(Agent.name == BUILDING_AGENT_NAME))).scalars().first()

    coord_placed = None
    if coord is not None:
        coord_placed = (
            await db.execute(
                select(WorkspaceAgent).where(
                    WorkspaceAgent.workspace_id == workspace_id,
                    WorkspaceAgent.agent_id == coord.agent_id,
                )
            )
        ).scalars().first()
    building_placed = None
    if building is not None:
        building_placed = (
            await db.execute(
                select(WorkspaceAgent).where(
                    WorkspaceAgent.workspace_id == workspace_id,
                    WorkspaceAgent.agent_id == building.agent_id,
                )
            )
        ).scalars().first()

    coord_sender_id = coord.agent_id if (coord and coord_placed) else workspace_id
    coord_sender_type = "agent" if (coord and coord_placed) else "system"
    coord_sender_name = coord.name if (coord and coord_placed) else "MACRO-Mesh System"

    building_sender_id = building.agent_id if (building and building_placed) else workspace_id
    building_sender_type = "agent" if (building and building_placed) else "system"

    def _add(*, sender_id, sender_type, sender_name, intent, kind, message, extras, tags):
        body = {
            "kind": kind,
            "step": step,
            "message": message,
            "used_llm_proposers": used_llm_proposers,
            **extras,
        }
        body_ref = build_inline_body_ref(body)
        db.add(
            MessageHeader(
                sender_id=sender_id, sender_type=sender_type, sender_name=sender_name,
                domain="macro_mesh", intent=intent, priority="medium",
                tags=["macro_mesh", *tags],
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

    try:
        label = "LLM proposers" if used_llm_proposers else "Heuristic proposers"
        _add(
            sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
            intent="negotiate_start", kind="macro_mesh_start",
            message=f"[Step {step + 1}] MACRO-Mesh 분산 협상 시작 ({label}, max_rounds={len(result.rounds)})",
            extras={
                "round_count": len(result.rounds),
                "asset_count": len(result.topology.controllable_assets),
            },
            tags=["start"],
        )

        for r in result.rounds:
            _add(
                sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
                intent="round_start", kind="macro_mesh_round_start",
                message=f"[Step {step + 1}][round {r.round_index + 1}] {len(r.proposals)} building 병렬 proposal 수신 ({r.elapsed_seconds:.2f}s)",
                extras={"round_index": r.round_index, "elapsed_seconds": r.elapsed_seconds},
                tags=["round", f"round-{r.round_index}"],
            )

            for p in r.proposals:
                _add(
                    sender_id=building_sender_id, sender_type=building_sender_type,
                    sender_name=f"Battery Agent · {p.building_id}",
                    intent="proposal", kind="macro_mesh_proposal",
                    message=f"[round {r.round_index + 1}] {p.building_id}: {p.proposed_action:+.2f} (conf {p.confidence:.2f}) — {p.rationale[:80]}",
                    extras={
                        "round_index": r.round_index,
                        "building_id": p.building_id,
                        "proposed_action": p.proposed_action,
                        "confidence": p.confidence,
                        "rationale": p.rationale,
                        "expected_local_effect": p.expected_local_effect,
                        "kind": p.kind,
                    },
                    tags=["proposal", p.building_id, f"round-{r.round_index}"],
                )

            mf = r.mean_field
            _add(
                sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
                intent="mean_field", kind="macro_mesh_mean_field",
                message=f"[round {r.round_index + 1}] mean_field: discharge {mf.discharge_count} / charge {mf.charge_count} / hold {mf.hold_count}, std={mf.stddev_action:.2f}, critical_soc={mf.critical_soc_ratio:.2f}",
                extras={"round_index": r.round_index, "mean_field": mf.model_dump(mode="json")},
                tags=["mean_field", f"round-{r.round_index}"],
            )

            for c in r.conflicts:
                _add(
                    sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
                    intent="conflict", kind="macro_mesh_conflict",
                    message=f"[round {r.round_index + 1}] CONFLICT {c.type} (severity {c.severity:.2f}): {c.description[:120]}",
                    extras={
                        "round_index": r.round_index, "type": c.type, "severity": c.severity,
                        "building_ids": c.building_ids, "description": c.description,
                    },
                    tags=["conflict", c.type, f"round-{r.round_index}"],
                )

        _add(
            sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
            intent="merged_plan", kind="macro_mesh_merged_plan",
            message=f"[Step {step + 1}] merged plan: {len(result.merged_plan.actions)} actions — {result.merged_plan.strategy_summary[:80]}",
            extras={
                "actions": [
                    {"building_id": a.building_id, "action": round(a.action, 3), "mode": a.mode}
                    for a in result.merged_plan.actions
                ],
                "strategy_summary": result.merged_plan.strategy_summary,
                "risk_assessment": result.merged_plan.risk_assessment,
            },
            tags=["merged"],
        )

        _add(
            sender_id=coord_sender_id, sender_type=coord_sender_type, sender_name=coord_sender_name,
            intent="negotiate_result", kind="macro_mesh_result",
            message=f"[Step {step + 1}] {'승인' if result.validation.approved else '거절'} · score {result.validation.score_before:.2f}→{result.validation.score_after:.2f} · {len(result.merged_plan.actions)} actions · {len(result.rounds)} rounds",
            extras={
                "approved": result.validation.approved,
                "status": result.validation.status,
                "score_before": round(result.validation.score_before, 2),
                "score_after": round(result.validation.score_after, 2),
                "operator_summary": result.operator_summary,
                "feedback": result.validation.feedback,
            },
            tags=["result", "approved" if result.validation.approved else "rejected"],
        )

        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish_negotiation_messages: insert failed: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return False
