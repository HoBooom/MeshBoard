from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


AGENT_STATUSES = {"DRAFT", "ACTIVE", "DEPRECATED", "SUSPENDED"}
AGENT_VISIBILITIES = {"PUBLIC", "DEPARTMENT", "PRIVATE"}
RULE_PRIORITIES = {"low", "medium", "high", "critical"}


# ── Subscription Rule Schemas ────────────────────────────────────


class SubscriptionRuleBase(BaseModel):
    """구독 규칙의 공통 필드. AGENT_SUBSCRIPTION_RULES 스키마 매핑."""

    watch_domains: List[str] = Field(default_factory=list, description="관심 도메인 (finance, hr 등)")
    watch_intents: List[str] = Field(default_factory=list, description="관심 인텐트 (data_request, alert 등)")
    watch_tags: List[str] = Field(default_factory=list, description="관심 태그")
    watch_senders: List[UUID] = Field(default_factory=list, description="특정 발신자 ID 구독")
    watch_roles: List[str] = Field(default_factory=list, description="특정 역할의 발신자 구독")

    ignore_senders: List[UUID] = Field(default_factory=list, description="블랙리스트 발신자")
    ignore_tags: List[str] = Field(default_factory=list, description="블랙리스트 태그")

    min_priority: str = Field("medium", description="최소 우선순위 (low/medium/high/critical)")
    is_active: bool = True


class SubscriptionRuleCreate(SubscriptionRuleBase):
    pass


class SubscriptionRuleRead(SubscriptionRuleBase):
    rule_id: UUID
    agent_id: UUID
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Agent Schemas ────────────────────────────────────────────────
#
# 주의: SQLAlchemy DeclarativeBase 의 `metadata` 속성과 충돌을 피하기 위해
# 응답 스키마(AgentRead) 는 필드 이름을 `metadata_` 로 그대로 노출하고,
# 요청 스키마(AgentCreate/AgentUpdate) 에서만 JSON 키 `metadata` 를 허용합니다.


class AgentRead(BaseModel):
    """에이전트 목록/상세 응답. ORM 속성 이름(`metadata_`) 그대로 직렬화."""

    agent_id: UUID
    name: str
    version: str
    purpose: Optional[str] = None
    description: Optional[str] = None
    approach: Optional[str] = None
    owner_id: UUID
    status: str
    visibility: str
    agent_card: Dict[str, Any]
    roles: List[str]
    collaborators: List[str]
    tools: List[str]
    metadata_: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    subscription_rule: Optional[SubscriptionRuleRead] = None

    model_config = ConfigDict(from_attributes=True)


class AgentCreate(BaseModel):
    """에이전트 신규 등록 요청. 초기 상태는 DRAFT."""

    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=50)
    purpose: Optional[str] = None
    description: Optional[str] = None
    approach: Optional[str] = None
    status: str = Field("DRAFT", description="DRAFT/ACTIVE/DEPRECATED/SUSPENDED")
    visibility: str = Field("PRIVATE", description="PUBLIC/DEPARTMENT/PRIVATE")

    agent_card: Dict[str, Any] = Field(default_factory=dict)
    roles: List[str] = Field(default_factory=list)
    collaborators: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    metadata_: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "metadata_"),
        serialization_alias="metadata",
    )

    subscription_rule: Optional[SubscriptionRuleCreate] = None

    model_config = ConfigDict(populate_by_name=True)


class AgentUpdate(BaseModel):
    """에이전트 수정 요청 (부분 수정 지원)."""

    name: Optional[str] = None
    version: Optional[str] = None
    purpose: Optional[str] = None
    description: Optional[str] = None
    approach: Optional[str] = None
    status: Optional[str] = None
    visibility: Optional[str] = None
    agent_card: Optional[Dict[str, Any]] = None
    roles: Optional[List[str]] = None
    collaborators: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    metadata_: Optional[Dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "metadata_"),
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class ToolDescriptor(BaseModel):
    """사용 가능한 도구(MCP) 카탈로그 항목."""

    id: str
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    mcp_definition: Dict[str, Any] = Field(default_factory=dict)


class InvokeRequest(BaseModel):
    """에이전트 실행 테스트 요청."""

    message: str = Field(..., min_length=1, description="에이전트에 전달할 메시지")
    model: Optional[str] = Field(None, description="사용할 LLM 모델 (미지정 시 기본값)")
    checkpoint_thread_id: Optional[str] = Field(
        None,
        description="기존 LangGraph 체크포인트 thread_id. 미지정 시 새 실행 생성.",
    )
    resume: bool = Field(False, description="true 이면 checkpoint_thread_id 의 다음 노드부터 재개")
    interrupt_after_node: Optional[str] = Field(
        None,
        description="agent_node 또는 mcp_tool_node 실행 직후 중단하여 체크포인트 저장",
    )


class InvokeResponse(BaseModel):
    """에이전트 실행 결과."""

    agent_id: UUID
    agent_name: str
    model_used: str
    input: str
    output: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    checkpoint: Dict[str, Any] = Field(default_factory=dict)
    graph: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
