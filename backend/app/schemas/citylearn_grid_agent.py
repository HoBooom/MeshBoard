"""CityLearn Grid-Agent Pydantic 스키마.

Grid-Agent analyze/plan API와 LLM tool I/O에서 공유하는 데이터 구조 정의.
프런트엔드(frontend/src/api/citylearn.ts)와 호환되도록 snake_case JSON을 유지한다.

원본 설계: docs/architecture/01_paper_grid_agent.md, docs/architecture/03_recommended_architecture.md
Feature 추적: docs/architecture/feature_list.json (AM-schema-001)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Literal / Constant 정의 ──────────────────────────────────────────

ViolationType = Literal[
    "peak",
    "ramping",
    "soc",
    "mapping",
    "fairness",
    "invalid_action",
]

ActionMode = Literal["charge", "discharge", "hold"]

BaselineModel = Literal[
    "basic_rbc",
    "optimized_rbc",
    "basic_battery_rbc",
    "sacrbc",
    "sac",
    "marlisa",
]

AgentMeshMode = Literal[
    "not_configured",
    "demo_heuristic",
    "configured_agents",
    "grid_agent",
    "macro_mesh",
]

PlannerKind = Literal["heuristic", "llm"]

ValidationStatus = Literal["approved", "rejected", "fallback"]


# CityLearn `phase_all` 데이터셋 기준 step 범위 (1년 hourly = 8760)
CITYLEARN_MIN_STEP = 0
CITYLEARN_MAX_STEP = 8759

# Board chart window (hours). 1시간 ~ 1주.
BOARD_WINDOW_MIN = 1
BOARD_WINDOW_MAX = 168

# Plan replanning iteration 상한 (논문 권장값 + 안전 한도).
PLAN_ITERATIONS_MIN = 1
PLAN_ITERATIONS_MAX = 6

# Battery action 범위 (음수=방전, 양수=충전).
ACTION_MIN = -1.0
ACTION_MAX = 1.0

# Confidence/severity 범위.
UNIT_MIN = 0.0
UNIT_MAX = 1.0


# ── Core Domain Models ──────────────────────────────────────────────


class CityLearnViolation(BaseModel):
    """단일 violation 인스턴스.

    `current_value`/`limit_value`는 violation type에 따라 의미가 다르다
    (예: peak는 district net load kWh, soc는 building SOC 0~1).
    """

    type: ViolationType
    building_id: Optional[str] = Field(
        default=None,
        description="해당 violation이 building scope이면 building_id, district scope이면 None.",
    )
    severity: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)
    current_value: float
    limit_value: float
    description: str

    model_config = ConfigDict(extra="forbid")


class CityLearnAction(BaseModel):
    """Building 1개에 대한 배터리 action 제안."""

    building_id: str = Field(..., min_length=1)
    action: float = Field(..., ge=ACTION_MIN, le=ACTION_MAX)
    mode: ActionMode
    reason: str
    expected_effect: str
    confidence: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)

    model_config = ConfigDict(extra="forbid")


class CityLearnPlan(BaseModel):
    """한 step에 대해 district 전체로 묶인 action 묶음."""

    strategy_summary: str
    actions: List[CityLearnAction] = Field(default_factory=list)
    risk_assessment: str

    model_config = ConfigDict(extra="forbid")


class CityLearnValidationResult(BaseModel):
    """SandboxExecutor + ConstraintValidator 결과."""

    approved: bool
    status: ValidationStatus
    score_before: float
    score_after: float
    resolved_violations: List[CityLearnViolation] = Field(default_factory=list)
    remaining_violations: List[CityLearnViolation] = Field(default_factory=list)
    new_violations: List[CityLearnViolation] = Field(default_factory=list)
    clipped_actions: List[CityLearnAction] = Field(default_factory=list)
    forbidden_action_keys: List[str] = Field(
        default_factory=list,
        description='반복 금지 action key 목록. 형식: "{building_id}:{rounded_action}"',
    )
    feedback: str

    model_config = ConfigDict(extra="forbid")


class ControllableAsset(BaseModel):
    """Topology 분석 결과로 노출되는 제어 가능 자산."""

    building_id: str
    assigned_agent_id: Optional[UUID] = None
    assigned_agent_name: Optional[str] = None
    battery_soc: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)
    net_load_kwh: float
    pv_generation_kwh: float
    has_mapping: bool

    model_config = ConfigDict(extra="forbid")


class TopologySummary(BaseModel):
    """Grid-Agent 진입 시점의 토폴로지 요약."""

    workspace_id: UUID
    step: int = Field(..., ge=CITYLEARN_MIN_STEP, le=CITYLEARN_MAX_STEP)
    baseline_model: BaselineModel
    agent_mesh_mode: AgentMeshMode
    building_count: int = Field(..., ge=0)
    mapped_building_count: int = Field(..., ge=0)
    district_net_load_kwh: float
    controllable_assets: List[ControllableAsset] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PlanIteration(BaseModel):
    """Replanning loop 한 회차의 trace.

    LLM Planner가 연결되면 `planner_output`에 raw JSON 응답, `route_decision`에
    final/tool 분기 결과가 누적된다. Phase 1 deterministic 단계에서는 단일 iteration만 기록된다.
    """

    iteration: int = Field(..., ge=1, le=PLAN_ITERATIONS_MAX)
    planner_kind: PlannerKind
    planner_output: Optional[Dict[str, Any]] = None
    plan: CityLearnPlan
    validation: CityLearnValidationResult
    route_decision: Optional[str] = Field(
        default=None,
        description="LLM Planner의 분기 결정 (예: 'final', 'tool', 'fallback').",
    )

    model_config = ConfigDict(extra="forbid")


# ── API Request / Response ──────────────────────────────────────────


class GridAgentAnalyzeRequest(BaseModel):
    """POST /api/v1/citylearn/grid-agent/analyze 요청.

    Board snapshot과 동일한 step 좌표계를 사용한다.
    """

    workspace_id: UUID
    step: int = Field(..., ge=CITYLEARN_MIN_STEP, le=CITYLEARN_MAX_STEP)
    baseline_model: BaselineModel = "basic_rbc"
    agent_mesh_mode: AgentMeshMode = "demo_heuristic"
    window: int = Field(default=24, ge=BOARD_WINDOW_MIN, le=BOARD_WINDOW_MAX)

    model_config = ConfigDict(extra="forbid")


class GridAgentAnalyzeResponse(BaseModel):
    """analyze 응답: topology + initial violation만 반환 (preview-only)."""

    run_id: UUID
    requested_at: datetime
    topology: TopologySummary
    initial_violations: List[CityLearnViolation] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GridAgentPlanRequest(BaseModel):
    """POST /api/v1/citylearn/grid-agent/plan 요청.

    Phase 1: heuristic planner만 사용 (`use_llm_planner=False`).
    Phase 2 이후 LLM Planner와 replanning loop가 활성화된다.
    """

    workspace_id: UUID
    step: int = Field(..., ge=CITYLEARN_MIN_STEP, le=CITYLEARN_MAX_STEP)
    baseline_model: BaselineModel = "basic_rbc"
    agent_mesh_mode: AgentMeshMode = "demo_heuristic"
    window: int = Field(default=24, ge=BOARD_WINDOW_MIN, le=BOARD_WINDOW_MAX)
    max_iterations: int = Field(
        default=1,
        ge=PLAN_ITERATIONS_MIN,
        le=PLAN_ITERATIONS_MAX,
        description="Replanning 시도 횟수. Phase 1 deterministic은 1로 고정.",
    )
    use_llm_planner: bool = Field(
        default=False,
        description="True 시 agent_runtime 기반 LLM Planner 사용 (Phase 2+).",
    )
    forbidden_action_keys: List[str] = Field(
        default_factory=list,
        description="이전 run에서 누적된 금지 action key. 새 plan에 재주입된다.",
    )

    model_config = ConfigDict(extra="forbid")


class GridAgentPlanResponse(BaseModel):
    """plan 응답: 최종 plan + sandbox 검증 결과 + iteration trace + operator 요약."""

    run_id: UUID
    requested_at: datetime
    topology: TopologySummary
    initial_violations: List[CityLearnViolation] = Field(default_factory=list)
    iterations: List[PlanIteration] = Field(default_factory=list)
    final_plan: CityLearnPlan
    validation: CityLearnValidationResult
    operator_summary: str
    forbidden_action_keys: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "ACTION_MAX",
    "ACTION_MIN",
    "ActionMode",
    "AgentMeshMode",
    "BaselineModel",
    "BOARD_WINDOW_MAX",
    "BOARD_WINDOW_MIN",
    "CITYLEARN_MAX_STEP",
    "CITYLEARN_MIN_STEP",
    "CityLearnAction",
    "CityLearnPlan",
    "CityLearnValidationResult",
    "CityLearnViolation",
    "ControllableAsset",
    "GridAgentAnalyzeRequest",
    "GridAgentAnalyzeResponse",
    "GridAgentPlanRequest",
    "GridAgentPlanResponse",
    "PLAN_ITERATIONS_MAX",
    "PLAN_ITERATIONS_MIN",
    "PlanIteration",
    "PlannerKind",
    "TopologySummary",
    "UNIT_MAX",
    "UNIT_MIN",
    "ValidationStatus",
    "ViolationType",
]
