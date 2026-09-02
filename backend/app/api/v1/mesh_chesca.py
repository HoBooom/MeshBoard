"""MESH-CHESCA board endpoints (mesh_chesca workspace template).

Drives the teammate's real CHESCA-vs-Mesh runtime (Final_mesh1-main) step-by-step and
returns a CityLearn-board-compatible snapshot plus a mesh negotiation trace, so the
existing CityLearn board UI can be reused for the "도시관리 mesh_chesca" template.

The CHESCA runtime (vendored CityLearn 2.1b12 + xgboost forecasting + battery tree-search)
is heavy and synchronous, so snapshot building runs in a worker thread to avoid blocking
the event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services import mesh_chesca_client
from app.services.mesh_chesca_client import MeshChescaWorkerError
# 주의: 아래 import는 상수/파일목록만 가져오며 citylearn(2.1b12)을 적재하지 않는다.
# 실제 런타임(get_mesh_chesca_board_snapshot 등)은 별도 워커 프로세스에서만 실행해
# 메인 프로세스의 citylearn(SACRBC용 구버전)과 충돌하지 않도록 한다.
from app.services.mesh_chesca_runtime import (
    DEFAULT_DATASET,
    DEFAULT_SCENARIO,
    SCENARIOS,
    available_datasets,
)
# OpenSynCity 정전 MPC mesh 시나리오는 별도 런타임(CityLearn_old_system, 메인 프로세스 in-process)이
# 처리한다. 상수/함수만 import하며 citylearn은 첫 호출 때 lazy 적재된다.
from app.services import agent_mesh_runtime
from app.services.agent_mesh_runtime import AgentMeshUnavailable, SCENARIO_ID as AGENT_MESH_SCENARIO_ID
from app.services.agent_mesh_publish import publish_agent_mesh_step
from app.services.agent_mesh_llm import narrate_reports, llm_narration_enabled


router = APIRouter(prefix="/mesh-chesca", tags=["mesh-chesca"])


@router.get("/scenarios")
async def mesh_chesca_scenarios(_: User = Depends(get_current_user)) -> Dict[str, Any]:
    """협상 시나리오(모드) 목록 + 사용 가능한 dataset."""
    return {
        "default_scenario": DEFAULT_SCENARIO,
        "default_dataset": DEFAULT_DATASET,
        "scenarios": [
            {"id": sid, "label": meta["label"], "description": meta["description"]}
            for sid, meta in SCENARIOS.items()
        ],
        "datasets": available_datasets(),
    }


@router.get("/status")
async def mesh_chesca_status(
    scenario: str = Query(DEFAULT_SCENARIO),
    dataset: str = Query(DEFAULT_DATASET),
    connect: bool = Query(False, description="true면 런타임을 실제로 초기화하며 상태를 확인"),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """CHESCA 런타임 연결 상태 (의존성/모델/dataset 적재 가능 여부)."""
    if scenario == AGENT_MESH_SCENARIO_ID:
        # 별도 런타임(메인 프로세스). dataset 파라미터는 무시(런타임이 2022 phase_all 고정).
        return await asyncio.to_thread(agent_mesh_runtime.runtime_status, connect=connect)
    try:
        return await asyncio.to_thread(
            mesh_chesca_client.status, scenario=scenario, dataset=dataset, connect=connect
        )
    except MeshChescaWorkerError as exc:
        return {
            "dataset": dataset,
            "scenario": scenario,
            "runner_connected": False,
            "runtime_error": str(exc),
        }


@router.get("/board")
async def mesh_chesca_board(
    step: int = Query(0, ge=0, le=8759),
    scenario: str = Query(DEFAULT_SCENARIO),
    dataset: str = Query(DEFAULT_DATASET),
    window: int = Query(72, ge=1, le=168),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """실제 CHESCA 런타임을 step까지 구동해 board 스냅샷 + mesh 협상 trace를 반환.

    런타임(vendored CityLearn 2.1b12 / xgboost 등)이 없거나 초기화에 실패하면 503을 돌려준다.
    """
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "unknown_scenario", "message": f"Unknown scenario '{scenario}'."},
        )

    # OpenSynCity 정전 MPC mesh: CHESCA 워커가 아니라 메인 프로세스 런타임으로 라우팅.
    # (dataset 파라미터는 무시 — 이 런타임은 2022 phase_all + 정전 주입 고정.)
    if scenario == AGENT_MESH_SCENARIO_ID:
        try:
            return await asyncio.to_thread(
                agent_mesh_runtime.get_agent_mesh_board_snapshot, step=step, window=window
            )
        except AgentMeshUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "agent_mesh_runtime_unavailable", "message": str(exc)},
            ) from exc

    try:
        return await asyncio.to_thread(
            mesh_chesca_client.board_snapshot,
            step=step,
            scenario=scenario,
            dataset=dataset,
            window=window,
        )
    except MeshChescaWorkerError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "mesh_chesca_runtime_unavailable", "message": str(exc)},
        ) from exc


@router.post("/publish")
async def mesh_chesca_publish(
    workspace_id: UUID = Query(..., description="메시지를 발행할 워크스페이스"),
    step: int = Query(0, ge=0, le=8759),
    scenario: str = Query(AGENT_MESH_SCENARIO_ID),
    window: int = Query(72, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """OpenSynCity(outage_mpc_mesh) 한 step의 board snapshot을 만들고, 에이전트 자연어 소통을
    워크스페이스 메시지 피드로 발행한 뒤, board snapshot을 그대로 반환.

    프론트는 이 한 번의 호출로 (1) board 렌더와 (2) 메시징 페이지 타임라인 갱신을 동시에 얻는다.
    outage_mpc_mesh 외 시나리오는 발행 없이 board snapshot만 돌려준다.
    """
    if scenario != AGENT_MESH_SCENARIO_ID:
        # 다른 시나리오는 발행 대상이 아님 — board 스냅샷만 반환(워커 경유).
        try:
            return await asyncio.to_thread(
                mesh_chesca_client.board_snapshot,
                step=step, scenario=scenario, dataset=DEFAULT_DATASET, window=window,
            )
        except MeshChescaWorkerError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "mesh_chesca_runtime_unavailable", "message": str(exc)},
            ) from exc

    try:
        snapshot = await asyncio.to_thread(
            agent_mesh_runtime.get_agent_mesh_board_snapshot, step=step, window=window
        )
    except AgentMeshUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "agent_mesh_runtime_unavailable", "message": str(exc)},
        ) from exc

    mesh = snapshot.get("mesh_chesca", {})
    reports = mesh.get("agent_reports", []) or []
    negotiation = mesh.get("negotiation")
    hour = int(negotiation.get("hour", (step % 24) + 1)) if negotiation else (step % 24) + 1

    # 로컬 Qwen narration: 결정론적 사실은 유지하고 표현만 LLM이 생성(전원). 비활성/실패 시 템플릿 유지.
    if llm_narration_enabled():
        reports = await narrate_reports(reports, hour=hour)
        mesh["agent_reports"] = reports  # board 패널에도 LLM 문장 반영

    published = await publish_agent_mesh_step(
        db=db,
        workspace_id=workspace_id,
        agent_reports=reports,
        negotiation=negotiation,
        step=step,
    )
    snapshot["published_messages"] = published
    snapshot["llm_narration"] = llm_narration_enabled()
    return snapshot
