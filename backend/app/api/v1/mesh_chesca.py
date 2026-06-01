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

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_user
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
