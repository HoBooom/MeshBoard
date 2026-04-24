from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentRead(BaseModel):
    """에이전트 목록 조회 및 상세 응답 스키마"""
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

    model_config = ConfigDict(from_attributes=True)
