"""MACRO-Mesh 분산 협상 Pydantic 스키마 (AM-macro-001).

설계: docs/architecture/02_paper_macro_llm.md + 03_recommended_architecture.md.
Phase 3에서 17개 Building Battery Agent가 각자 proposal을 발의하고, Coordinator가
mean_field/conflict를 산출해 round 2 재제안을 유도하는 분산 협상 데이터 모델.

Grid-Agent 스키마(citylearn_grid_agent.py)와 building_id/action 표현을 통일한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.citylearn_grid_agent import (
    ACTION_MAX,
    ACTION_MIN,
    AgentMeshMode,
    BaselineModel,
    CityLearnAction,
    CityLearnPlan,
    CityLearnValidationResult,
    CityLearnViolation,
    CITYLEARN_MAX_STEP,
    CITYLEARN_MIN_STEP,
    PlanIteration,
    TopologySummary,
    UNIT_MAX,
    UNIT_MIN,
)


# ── Literals + Constants ────────────────────────────────────────────

ConflictType = Literal[
    "over_discharge",      # 다수 building이 동시 방전 → district SOC 위기
    "soc_risk",            # 특정 building이 SOC hard bound 위반 위험
    "fairness",            # 특정 building에 부담 집중
    "resource_contention", # 동일 자원 경합 (PV/grid)
]

ProposalKind = Literal["llm", "heuristic"]

# round_index 0/1 (max_rounds=2 기본)
ROUND_INDEX_MIN = 0
ROUND_INDEX_MAX = 1

# 협상 운영 한계
MAX_ROUNDS_DEFAULT = 2
NEGOTIATE_TIMEOUT_SECONDS = 30.0
OBSERVATION_WINDOW_DEFAULT = 24
OBSERVATION_WINDOW_MIN = 1
OBSERVATION_WINDOW_MAX = 168


# ── Core Models ─────────────────────────────────────────────────────


class BuildingProposal(BaseModel):
    """Building agent 한 명의 단일 round proposal."""

    building_id: str = Field(..., min_length=1)
    round_index: int = Field(..., ge=ROUND_INDEX_MIN, le=ROUND_INDEX_MAX)
    proposed_action: float = Field(..., ge=ACTION_MIN, le=ACTION_MAX)
    confidence: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)
    rationale: str
    expected_local_effect: str
    kind: ProposalKind = "llm"
    raw_output_preview: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class MeanFieldSummary(BaseModel):
    """한 round 종료 후 district 단위로 집계한 mean-field 통계."""

    round_index: int = Field(..., ge=ROUND_INDEX_MIN, le=ROUND_INDEX_MAX)
    proposal_count: int = Field(..., ge=0)
    mean_action: float
    stddev_action: float
    mean_abs_action: float
    discharge_count: int = Field(..., ge=0)
    charge_count: int = Field(..., ge=0)
    hold_count: int = Field(..., ge=0)
    critical_soc_ratio: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)
    expected_district_load_delta_kwh: float

    model_config = ConfigDict(extra="forbid")


class ConflictReport(BaseModel):
    """규칙 기반으로 탐지된 단일 conflict."""

    type: ConflictType
    severity: float = Field(..., ge=UNIT_MIN, le=UNIT_MAX)
    building_ids: List[str] = Field(default_factory=list)
    description: str

    model_config = ConfigDict(extra="forbid")


class NegotiationFeedback(BaseModel):
    """round 종료 후 각 building agent에게 주입할 피드백."""

    target_building_id: str
    mean_field: MeanFieldSummary
    conflicts: List[ConflictReport] = Field(default_factory=list)
    forbidden_action_keys: List[str] = Field(default_factory=list)
    instruction: str

    model_config = ConfigDict(extra="forbid")


class NegotiationRound(BaseModel):
    """단일 round의 모든 trace."""

    round_index: int = Field(..., ge=ROUND_INDEX_MIN, le=ROUND_INDEX_MAX)
    proposals: List[BuildingProposal] = Field(default_factory=list)
    mean_field: MeanFieldSummary
    conflicts: List[ConflictReport] = Field(default_factory=list)
    feedback_by_building: Dict[str, NegotiationFeedback] = Field(default_factory=dict)
    elapsed_seconds: float = Field(..., ge=0)

    model_config = ConfigDict(extra="forbid")


# ── API Request / Response ──────────────────────────────────────────


class MacroMeshNegotiateRequest(BaseModel):
    workspace_id: UUID
    step: int = Field(..., ge=CITYLEARN_MIN_STEP, le=CITYLEARN_MAX_STEP)
    baseline_model: BaselineModel = "basic_rbc"
    agent_mesh_mode: AgentMeshMode = "macro_mesh"
    window: int = Field(
        default=OBSERVATION_WINDOW_DEFAULT,
        ge=OBSERVATION_WINDOW_MIN,
        le=OBSERVATION_WINDOW_MAX,
    )
    max_rounds: int = Field(
        default=MAX_ROUNDS_DEFAULT,
        ge=1,
        le=ROUND_INDEX_MAX + 1,
    )
    use_llm_proposers: bool = Field(
        default=False,
        description="False 시 deterministic heuristic proposer (빠르고 결정적).",
    )

    model_config = ConfigDict(extra="forbid")


class MacroMeshNegotiateResponse(BaseModel):
    """negotiate API 응답 — 전체 trace 포함."""

    run_id: UUID
    requested_at: datetime
    topology: TopologySummary
    initial_violations: List[CityLearnViolation] = Field(default_factory=list)
    rounds: List[NegotiationRound] = Field(default_factory=list)
    merged_plan: CityLearnPlan
    plan_iteration_trace: List[PlanIteration] = Field(default_factory=list)
    validation: CityLearnValidationResult
    operator_summary: str
    forbidden_action_keys: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "BuildingProposal",
    "ConflictReport",
    "ConflictType",
    "MAX_ROUNDS_DEFAULT",
    "MacroMeshNegotiateRequest",
    "MacroMeshNegotiateResponse",
    "MeanFieldSummary",
    "NEGOTIATE_TIMEOUT_SECONDS",
    "NegotiationFeedback",
    "NegotiationRound",
    "OBSERVATION_WINDOW_DEFAULT",
    "OBSERVATION_WINDOW_MAX",
    "OBSERVATION_WINDOW_MIN",
    "ProposalKind",
    "ROUND_INDEX_MAX",
    "ROUND_INDEX_MIN",
]
